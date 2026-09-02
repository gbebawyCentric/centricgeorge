"""Create or update the Daily Ecom Mail workbook in Sigma.

    set -a && . ./.env && set +a
    python3 scripts/deploy.py --dry-run   # build and validate locally, no API call
    python3 scripts/deploy.py             # create, or update if it already exists

The deploy is idempotent: it looks the workbook up by name first and PATCHes
when it is already there, so re-running does not leave duplicates behind.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_spec import WORKBOOK_NAME, build_spec  # noqa: E402
from sigma_client import SigmaClient, SigmaError, fail  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="build the spec and print a summary without calling the API",
    )
    parser.add_argument(
        "--workbook-id",
        help="update this workbook id directly instead of looking it up by name",
    )
    parser.add_argument(
        "--workspace-id",
        default=os.environ.get("SIGMA_WORKSPACE_ID"),
        help="workspace to create the workbook in (defaults to $SIGMA_WORKSPACE_ID)",
    )
    args = parser.parse_args()

    spec = build_spec()
    element_count = sum(len(page["elements"]) for page in spec["pages"])
    print(f'built spec for "{spec["name"]}"')
    print(f"  {len(spec['dataSources'])} data sources, {element_count} elements")

    if args.dry_run:
        print("\ndry run — nothing sent to Sigma.")
        return

    client = SigmaClient()

    try:
        workbook_id = args.workbook_id
        if not workbook_id:
            existing = client.find_workbook_by_name(WORKBOOK_NAME)
            workbook_id = existing.get("workbookId") if existing else None

        if workbook_id:
            print(f"\nupdating existing workbook {workbook_id} ...")
            result = client.update_workbook_from_spec(workbook_id, spec)
        else:
            print("\ncreating new workbook ...")
            result = client.create_workbook_from_spec(spec, args.workspace_id)
            workbook_id = result.get("workbookId", "?")

        print(f"done. workbook id: {workbook_id}")
        if result.get("url"):
            print(f"  {result['url']}")

    except SigmaError as exc:
        # The spec endpoints reject with a body naming the offending field.
        # Print it in full — it is what tells you how to correct the spec.
        fail(str(exc), exc.body)


if __name__ == "__main__":
    main()
