"""Minimal Sigma REST API client for workbook-as-code.

Credentials are read from the environment (see .env.example). They are never
read from the command line, so they do not end up in shell history.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# Centric Brands is on Azure East US 2 (Virginia), so the default below is the
# Azure-US host. Administration → Account → General Settings → Site is where
# that is recorded; the cloud cannot be inferred from the app URL, which is
# app.sigmacomputing.com on every cloud.
#
# Getting this wrong does not announce itself. A credential aimed at a cloud it
# was not issued on is simply unknown to that host, so the token endpoint
# answers with the same HTTP 400 "Invalid access/refresh token" it returns for
# a client id of "deadbeef" — it reads as a bad secret and sends you looking in
# the wrong place. If auth fails, confirm this host before touching the secret.
#
# Per https://help.sigmacomputing.com/reference/get-started-sigma-api:
#   Azure-US (default)  https://api.us.azure.sigmacomputing.com
#   Azure-EU            https://api.eu.azure.sigmacomputing.com
#   Azure-CA            https://api.ca.azure.sigmacomputing.com
#   Azure-UK            https://api.uk.azure.sigmacomputing.com
#   Azure-AU            https://api.au.azure.sigmacomputing.com
#   AWS-US West         https://aws-api.sigmacomputing.com
#   AWS-US East         https://api.us-a.aws.sigmacomputing.com
#   AWS-CA              https://api.ca.aws.sigmacomputing.com
#   AWS-EU              https://api.eu.aws.sigmacomputing.com
#   AWS-UK              https://api.uk.aws.sigmacomputing.com
#   AWS-AU              https://api.au.aws.sigmacomputing.com
#   GCP-US              https://api.sigmacomputing.com
#   GCP-KSA             https://api.sa.gcp.sigmacomputing.com
DEFAULT_BASE_URL = "https://api.us.azure.sigmacomputing.com"


class SigmaError(RuntimeError):
    """An API call failed. Carries the server's response body when there is one."""

    def __init__(self, message: str, status: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status = status
        self.body = body


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SigmaError(
            f"{name} is not set. Copy .env.example to .env, fill it in, then "
            f"re-run with:  set -a && . ./.env && set +a"
        )
    return value


class SigmaClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = (
            base_url
            or os.environ.get("SIGMA_API_BASE_URL", "").strip()
            or DEFAULT_BASE_URL
        ).rstrip("/")
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    # -- auth ---------------------------------------------------------------

    def _get_token(self) -> str:
        # Reuse the token until it is nearly expired; Sigma's default TTL is an
        # hour and a deploy makes several calls.
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token

        client_id = _require_env("SIGMA_CLIENT_ID")
        client_secret = _require_env("SIGMA_CLIENT_SECRET")

        payload = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            }
        ).encode()

        request = urllib.request.Request(
            f"{self.base_url}/v2/auth/token",
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise SigmaError(
                "Authentication failed. Check SIGMA_CLIENT_ID / SIGMA_CLIENT_SECRET "
                f"and that SIGMA_API_BASE_URL ({self.base_url}) matches your Sigma cloud.",
                exc.code,
                detail,
            ) from exc
        except urllib.error.URLError as exc:
            raise SigmaError(
                f"Could not reach {self.base_url}: {exc.reason}. "
                "Confirm the host is reachable from this machine."
            ) from exc

        self._token = body["access_token"]
        self._token_expires_at = time.time() + int(body.get("expires_in", 3600))
        return self._token

    # -- requests -----------------------------------------------------------

    def request(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers={
                "Authorization": f"Bearer {self._get_token()}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method=method,
        )

        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                raw = response.read().decode()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            # The spec endpoints return a validation body explaining exactly
            # which field they rejected; surfacing it verbatim is the fastest
            # way to correct the spec.
            raise SigmaError(
                f"{method} {path} failed with HTTP {exc.code}.", exc.code, detail
            ) from exc
        except urllib.error.URLError as exc:
            raise SigmaError(f"Could not reach {self.base_url}: {exc.reason}") from exc

    # -- workbook spec ------------------------------------------------------

    def get_workbook_spec(self, workbook_id: str) -> dict:
        """Code representation of an existing workbook."""
        return self.request("GET", f"/v2/workbooks/{workbook_id}/spec")

    # Both calls below were verified against the live API on 3 Sep 2026 by
    # creating and then updating a throwaway workbook. The request shapes are
    # not what this file previously guessed:
    #
    #   - the body is {name, folderId, document}, not a {"spec": …} wrapper
    #   - folderId is required, and there is no workspaceId on this endpoint
    #   - updates are PUT; PATCH on the same path answers 404
    #   - documentVersion is server-assigned and must not be sent
    #
    # docs/spec-schema.md carries the document schema and the evidence.

    def create_workbook_from_spec(self, name: str, document: dict, folder_id: str) -> dict:
        """Create a workbook. Returns {"workbookId": …}; other fields come back null."""
        return self.request(
            "POST",
            "/v2/workbooks/spec",
            {"name": name, "folderId": folder_id, "document": document},
        )

    def update_workbook_from_spec(self, workbook_id: str, document: dict) -> dict:
        """Replace a workbook's document. Returns {"success": true, "workbookId": …}."""
        return self.request(
            "PUT", f"/v2/workbooks/{workbook_id}/spec", {"document": document}
        )

    def find_workbook_by_name(self, name: str) -> dict | None:
        """Look up a workbook by exact name so deploys are idempotent."""
        page = self.request("GET", "/v2/workbooks?limit=500")
        for entry in page.get("entries", []):
            if entry.get("name") == name:
                return entry
        return None


def fail(message: str, detail: str | None = None) -> None:
    print(f"error: {message}", file=sys.stderr)
    if detail:
        print(detail, file=sys.stderr)
    sys.exit(1)
