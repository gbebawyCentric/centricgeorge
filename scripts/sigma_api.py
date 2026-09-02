#!/usr/bin/env python3
"""Push/pull workbook code representations through the Sigma REST API.

Standard library only, so it runs anywhere python3 does.

    export SIGMA_CLIENT_ID=...      # Sigma > Administration > APIs & Embed Secrets
    export SIGMA_CLIENT_SECRET=...

    python3 scripts/sigma_api.py whoami
    python3 scripts/sigma_api.py get <workbookId> -o sigma/reference_spec.yaml
    python3 scripts/sigma_api.py create --spec sigma/workbook_spec.yaml
    python3 scripts/sigma_api.py update <workbookId> --spec sigma/workbook_spec.yaml

`create` and `update` refuse to run without --confirm unless SIGMA_ASSUME_YES=1,
since both write to a live Sigma org.

Run `get` against an existing workbook first. It is the fastest way to see the
beta's exact field names, and Centric already has one to copy the shape from:
"Centric West - Ecom KPI QA" (workbook id 6vUEJAG6qufed10qtaM140). If anything
in the response disagrees with what build_spec.py emits, fix the builders at the
top of that file and rebuild.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_SPEC = REPO / "sigma" / "workbook_spec.yaml"

# Sigma's API host is region-specific: AWS US is aws-api.sigmacomputing.com,
# other regions carry a prefix (e.g. aws-eu.sigmacomputing.com). Override with
# SIGMA_API_BASE if this org sits elsewhere.
API_BASE = os.environ.get("SIGMA_API_BASE", "https://aws-api.sigmacomputing.com")

TOKEN_PATH = "/v2/auth/token"
# Workbook code representation endpoints (private beta):
#   GET    /v2/workbooks/{workbookId}/spec   getWorkbookSpec
#   POST   /v2/workbooks/spec                createWorkbookSpec
#   PATCH  /v2/workbooks/{workbookId}/spec   updateWorkbookSpec
SPEC_COLLECTION_PATH = "/v2/workbooks/spec"


def _spec_path(workbook_id: str) -> str:
    return f"/v2/workbooks/{urllib.parse.quote(workbook_id)}/spec"


class SigmaError(RuntimeError):
    pass


def _request(method: str, path: str, token: str | None = None, body: bytes | None = None,
             content_type: str | None = None, form: bool = False) -> tuple[int, bytes]:
    url = API_BASE.rstrip("/") + path
    req = urllib.request.Request(url, data=body, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if content_type:
        req.add_header("Content-Type", content_type)
    elif form:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:2000]
        raise SigmaError(f"{method} {path} -> HTTP {e.code}\n{detail}") from e
    except urllib.error.URLError as e:
        # A blocked CONNECT and a wrong region look nothing alike; say which.
        raise SigmaError(
            f"{method} {path} -> could not reach {API_BASE}: {e.reason}\n"
            "If this environment routes through an egress proxy, "
            "the Sigma API host has to be on its allowlist."
        ) from e


def get_token() -> str:
    cid = os.environ.get("SIGMA_CLIENT_ID")
    secret = os.environ.get("SIGMA_CLIENT_SECRET")
    if not cid or not secret:
        raise SigmaError("set SIGMA_CLIENT_ID and SIGMA_CLIENT_SECRET first")
    payload = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": cid,
        "client_secret": secret,
    }).encode()
    _, raw = _request("POST", TOKEN_PATH, body=payload, form=True)
    token = json.loads(raw).get("access_token")
    if not token:
        raise SigmaError(f"no access_token in response: {raw[:400]!r}")
    return token


# --------------------------------------------------------------------------
# Spec file loading
# --------------------------------------------------------------------------

def load_spec(path: Path) -> tuple[str, str]:
    """Return (body, content_type) for a .yaml or .json spec file.

    YAML is sent as-is rather than converted, so the file the reviewer reads in
    the pull request is byte-for-byte the file Sigma receives.
    """
    text = path.read_text()
    if path.suffix in (".yaml", ".yml"):
        return text, "application/yaml"
    if path.suffix == ".json":
        json.loads(text)  # fail here rather than at the API on a typo
        return text, "application/json"
    raise SigmaError(f"unsupported spec extension {path.suffix!r} (use .yaml or .json)")


def _confirm(action: str, args) -> None:
    if args.confirm or os.environ.get("SIGMA_ASSUME_YES") == "1":
        return
    raise SigmaError(
        f"{action} writes to the live Sigma org at {API_BASE}.\n"
        "Re-run with --confirm (or SIGMA_ASSUME_YES=1) once that is intended."
    )


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def cmd_whoami(args) -> int:
    token = get_token()
    _, raw = _request("GET", "/v2/whoami", token=token)
    print(json.dumps(json.loads(raw), indent=2))
    return 0


def cmd_get(args) -> int:
    token = get_token()
    _, raw = _request("GET", _spec_path(args.workbook_id), token=token)
    if args.out:
        out = Path(args.out)
        out.write_bytes(raw)
        print(f"wrote {out} ({len(raw):,} bytes)")
    else:
        sys.stdout.write(raw.decode("utf-8", "replace"))
    return 0


def cmd_create(args) -> int:
    spec_path = Path(args.spec)
    body, ctype = load_spec(spec_path)
    if args.dry_run:
        print(f"POST {API_BASE}{SPEC_COLLECTION_PATH}  ({ctype}, {len(body):,} bytes)")
        print(f"spec: {spec_path}")
        return 0
    _confirm("create", args)
    token = get_token()
    _, raw = _request("POST", SPEC_COLLECTION_PATH, token=token,
                      body=body.encode(), content_type=ctype)
    resp = json.loads(raw) if raw.strip().startswith(b"{") else {"raw": raw.decode()}
    print(json.dumps(resp, indent=2))
    wid = resp.get("workbookId") or resp.get("id")
    if wid:
        print(f"\nworkbook created: {wid}\n"
              f"record it in docs/schedule-setup.md and use "
              f"`sigma_api.py update {wid}` from here on.")
    return 0


def cmd_update(args) -> int:
    spec_path = Path(args.spec)
    body, ctype = load_spec(spec_path)
    if args.dry_run:
        print(f"PATCH {API_BASE}{_spec_path(args.workbook_id)}  "
              f"({ctype}, {len(body):,} bytes)")
        print(f"spec: {spec_path}")
        return 0
    _confirm("update", args)
    token = get_token()
    _, raw = _request("PATCH", _spec_path(args.workbook_id), token=token,
                      body=body.encode(), content_type=ctype)
    print(raw.decode("utf-8", "replace") or "(empty response)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("whoami", help="check credentials and region").set_defaults(func=cmd_whoami)

    p_get = sub.add_parser("get", help="fetch a workbook's code representation")
    p_get.add_argument("workbook_id")
    p_get.add_argument("-o", "--out", help="write to this file instead of stdout")
    p_get.set_defaults(func=cmd_get)

    p_create = sub.add_parser("create", help="create a workbook from a spec file")
    p_create.add_argument("--spec", default=str(DEFAULT_SPEC))
    p_create.add_argument("--dry-run", action="store_true")
    p_create.add_argument("--confirm", action="store_true")
    p_create.set_defaults(func=cmd_create)

    p_update = sub.add_parser("update", help="update an existing workbook from a spec file")
    p_update.add_argument("workbook_id")
    p_update.add_argument("--spec", default=str(DEFAULT_SPEC))
    p_update.add_argument("--dry-run", action="store_true")
    p_update.add_argument("--confirm", action="store_true")
    p_update.set_defaults(func=cmd_update)

    args = ap.parse_args()
    try:
        return args.func(args)
    except SigmaError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
