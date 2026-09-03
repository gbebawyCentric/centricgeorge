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
        "--folder-id",
        default=os.environ.get("SIGMA_FOLDER_ID"),
        help=(
            "folder to create the workbook in (defaults to $SIGMA_FOLDER_ID). "
            "Required on create — the API rejects a spec without one. Find one "
            "with GET /v2/files?typeFilters=folder, or read folderId off an "
            "existing workbook's spec."
        ),
    )
    args = parser.parse_args()

    spec = build_spec()

    # build_spec.py was written to a guessed schema and has not been ported yet.
    # Fail here with a pointer rather than sending a body the API will reject.
    if "document" not in spec:
        fail(
            "build_spec() still emits the old guessed shape (name / dataSources / "
            "pages / elements). The API wants {name, folderId, document}. See "
            "docs/spec-schema.md for the real schema and the remaining gaps."
        )

    document = spec["document"]
    print(f'built spec for "{spec["name"]}"')
    print(f"  {len(document['pages'])} page(s), {len(document['elements'])} elements")

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
            result = client.update_workbook_from_spec(workbook_id, spec["document"])
        else:
            if not args.folder_id:
                fail(
                    "a folder is required to create a workbook. Pass --folder-id "
                    "or set SIGMA_FOLDER_ID."
                )
            print("\ncreating new workbook ...")
            result = client.create_workbook_from_spec(
                spec["name"], spec["document"], args.folder_id
            )
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
