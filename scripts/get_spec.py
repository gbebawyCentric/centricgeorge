"""Dump the code representation of an existing Sigma workbook.

Run this first. Workbooks-as-code is in private beta and its schema is not
publicly documented, so the authoritative reference for the spec shape is a
real workbook from this org:

    set -a && . ./.env && set +a
    python3 scripts/get_spec.py 6vUEJAG6qufed10qtaM140 -o reference_spec.json

That id is the existing "Centric West - Ecom KPI QA" workbook. Compare its
structure against sigma/workbook_spec.json and adjust the builder in
scripts/build_spec.py to match before deploying.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sigma_client import SigmaClient, SigmaError, fail  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook_id", help="workbook id (the tail of the workbook URL)")
    parser.add_argument("-o", "--output", help="write to this file instead of stdout")
    args = parser.parse_args()

    try:
        spec = SigmaClient().get_workbook_spec(args.workbook_id)
    except SigmaError as exc:
        fail(str(exc), exc.body)

    rendered = json.dumps(spec, indent=2, ensure_ascii=False) + "\n"

    if args.output:
        Path(args.output).write_text(rendered)
        print(f"wrote {args.output}")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
