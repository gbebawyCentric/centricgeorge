"""Create or update the Daily Ecom Mail workbooks in Sigma — one per brand.

    set -a && . ./.env && set +a
    python3 scripts/deploy.py --dry-run      # build and summarise, no API call
    python3 scripts/deploy.py                # all three brands
    python3 scripts/deploy.py --brand FD     # just one

Each deploy is idempotent: the workbook is looked up by name first and replaced
in place when it is already there, so re-running does not leave duplicates.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import brands as brand_config  # noqa: E402
from brands import Brand  # noqa: E402
from build_spec import REPO_ROOT, build_spec, workbook_name  # noqa: E402
from sigma_client import SigmaClient, SigmaError, fail  # noqa: E402

# brand id -> workbook id, written after each create.
#
# The workbook listing lags behind a create by some seconds, so looking a
# workbook up by name right after making it can come back empty and produce a
# second copy. Recording the id here makes a re-run idempotent even when the
# previous run failed partway through.
STATE_PATH = REPO_ROOT / "sigma" / "deployed.json"


def load_state() -> dict[str, str]:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {}


def save_state(state: dict[str, str]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def summarise(spec: dict) -> str:
    elements = spec["document"]["elements"]
    tables = [e for e in elements if e.get("kind") in ("table", "kpi-chart")]
    formulas = sum(len(e["columns"]) for e in tables)
    return (
        f"{len(elements)} elements, {len(tables)} data elements, "
        f"{formulas} column formulas"
    )


def deploy_one(
    client: SigmaClient | None,
    brand: Brand,
    workspace_id: str | None,
    folder_id: str | None,
    dry_run: bool,
    state: dict[str, str],
) -> None:
    spec = build_spec(brand)
    print(f'\n{brand.display_name}: "{spec["name"]}"')
    print(f"  {summarise(spec)}")

    if dry_run or client is None:
        return

    # Prefer the recorded id; fall back to a name lookup for workbooks made
    # before this state file existed, or made from another checkout.
    workbook_id = state.get(brand.brand_id)
    if workbook_id:
        try:
            client.get_workbook_spec(workbook_id)
        except SigmaError:
            workbook_id = None
    if not workbook_id:
        existing = client.find_workbook_by_name(workbook_name(brand))
        workbook_id = existing.get("workbookId") if existing else None

    if workbook_id:
        print(f"  updating {workbook_id} ...")
        result = client.update_workbook_from_spec(workbook_id, spec)
    else:
        print("  creating ...")
        result = client.create_workbook_from_spec(spec, workspace_id, folder_id)
        workbook_id = result.get("workbookId", "?")

    state[brand.brand_id] = workbook_id
    save_state(state)

    print(f"  done: {workbook_id}")
    if result.get("url"):
        print(f"  {result['url']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brand", help="deploy one brand (Hudson / FD / Joe's)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="build the specs and print a summary without calling the API",
    )
    parser.add_argument(
        "--workspace-id",
        default=os.environ.get("SIGMA_WORKSPACE_ID"),
        help="workspace to create the workbooks in (defaults to $SIGMA_WORKSPACE_ID)",
    )
    parser.add_argument(
        "--folder-id",
        default=os.environ.get("SIGMA_FOLDER_ID"),
        help=(
            "folder to create the workbooks in (defaults to $SIGMA_FOLDER_ID). "
            "Use this for a personal folder, which has no workspace id. "
            "Takes precedence over --workspace-id."
        ),
    )
    args = parser.parse_args()

    targets = [brand_config.get(args.brand)] if args.brand else list(brand_config.BRANDS)
    if args.folder_id and not args.dry_run:
        print(f"target folder: {args.folder_id}")

    client = None if args.dry_run else SigmaClient()
    state = load_state()

    try:
        for brand in targets:
            deploy_one(client, brand, args.workspace_id, args.folder_id,
                       args.dry_run, state)
    except SigmaError as exc:
        # The spec endpoints reject with a body naming the offending field.
        # Print it in full — it is what tells you how to correct the spec.
        fail(str(exc), exc.body)

    if args.dry_run:
        print("\ndry run — nothing sent to Sigma.")


if __name__ == "__main__":
    main()
