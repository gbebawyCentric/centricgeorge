"""Repair the L4W measures in the Merchandising workbook.

The five L4W base columns on the SALES_TRANSACTIONS element are gated on
`[INSIDE DATE RANGE]` as well as on the four-week lookback, which clamps the
window to whatever the DATE-Control is set to. Any selection shorter than four
weeks makes L4W identical to the selected range. See docs/merchandising-l4w.md.

The fix drops `[INSIDE DATE RANGE]` and bounds the window at [DATE RANGE END]
instead, which is exactly what the MTD / YTD / LAST 12 MONTHS columns beside it
already do.

    set -a && . ./.env && set +a
    python3 scripts/fix_merchandising_l4w.py              # show the diff, send nothing
    python3 scripts/fix_merchandising_l4w.py --apply      # write it back

--apply DOES NOT CURRENTLY WORK against this workbook, and should not be forced
through. Its spec does not survive a round-trip: a GET of it, PUT back
unmodified, is rejected, and at least one of the reasons is that GET drops a
column name the workbook depends on. Since PUT replaces the document wholesale,
anything else GET drops would be silently written away across all 112 elements.
Make the four edits in the Sigma UI instead — docs/merchandising-l4w.md lists
them, and the diff this prints is exactly that change.

This edits a live production workbook, so it refuses to apply unless every
formula it expects to rewrite is found exactly as recorded below, it writes the
pre-change spec to a backup file first, and it diffs the spec on read-back.
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sigma_client import SigmaClient, SigmaError, fail  # noqa: E402

WORKBOOK_ID = "7gixjFsPWIiP0Be4S31grs"
ELEMENT_ID = "4NTRg6lY30"  # the SALES_TRANSACTIONS table
ELEMENT_NAME = "SALES_TRANSACTIONS"

# The clamp, and what replaces it. Bounding on [DATE RANGE END] keeps L4W from
# running past the report date while letting it reach back a full four weeks.
CLAMP = "and [INSIDE DATE RANGE]"
BOUND = "and [Reporting Date] <= [DATE RANGE END]"

# Column id -> name, for the four columns that carry the clamp. [L4W NET SALES]
# is derived from two of these and needs no edit.
CLAMPED_COLUMNS = {
    "9peS6Tq_yI": "L4W SALES QTY",
    "3Y9lcWbZ3h": "L4W SALES RETAIL",
    "zGK2nUFdjf": "L4W SALES DISCOUNT",
    "sFNu4tPbfQ": "L4W COGS",
}

# `>=` against four-weeks-before-the-end-date spans 29 days, not 28. Correcting
# it changes a reported definition rather than a defect, so it is opt-in.
WINDOW_COLUMN_ID = "gC1UthO2Rw"  # "4 WEEKS AGO"
WINDOW_BEFORE = 'DateAdd("week", -4, [DATE RANGE END])'
WINDOW_AFTER = 'DateAdd("day", 1, DateAdd("week", -4, [DATE RANGE END]))'

# Some pivot-tables carry axisTotals entries pointing at ids that are not a
# dimension on that element — the elements look to have been copied from the
# size pivots without the column coming along. GET emits them, PUT rejects them
# ("is not a declared row or column dimension"), so the workbook's own spec does
# not round-trip and they have to come out before anything can be written back.
# They are inert: a total on an axis that does not exist.
#
# The same id IS a live dimension on other elements, where the total renders, so
# this is decided per element rather than by matching the id.
GRAND_TOTAL_AXES = {"grand-row-total", "grand-column-total", "grand-total"}


def find_element(spec: dict) -> dict:
    for element in spec["document"]["elements"]:
        if element.get("id") == ELEMENT_ID:
            return element
    for element in spec["document"]["elements"]:
        if element.get("name") == ELEMENT_NAME:
            return element
    raise SigmaError(
        f"no element {ELEMENT_ID} / {ELEMENT_NAME!r} in the workbook — "
        "it may have been renamed or rebuilt; re-check before editing."
    )


def patch(spec: dict, fix_window_length: bool) -> list[tuple[str, str, str]]:
    """Rewrite the clamped formulas in place. Returns (name, before, after)."""
    columns = {column["id"]: column for column in find_element(spec)["columns"]}
    changes: list[tuple[str, str, str]] = []

    for column_id, name in CLAMPED_COLUMNS.items():
        column = columns.get(column_id)
        if column is None:
            raise SigmaError(f"column {name} ({column_id}) is gone from the element.")

        before = column["formula"]
        if before.count(CLAMP) != 1:
            raise SigmaError(
                f"{name} does not contain {CLAMP!r} exactly once — it reads:\n"
                f"  {before}\n"
                "Someone has already edited it. Re-read the formula before applying."
            )

        after = before.replace(CLAMP, BOUND)
        column["formula"] = after
        changes.append((name, before, after))

    if fix_window_length:
        column = columns.get(WINDOW_COLUMN_ID)
        if column is None or column["formula"] != WINDOW_BEFORE:
            raise SigmaError(
                f"[4 WEEKS AGO] does not read {WINDOW_BEFORE!r}; refusing to "
                "change the window length."
            )
        column["formula"] = WINDOW_AFTER
        changes.append(("4 WEEKS AGO", WINDOW_BEFORE, WINDOW_AFTER))

    return changes


def declared_axes(element: dict) -> set[str]:
    """Ids PUT will accept as an axisTotals target on this element."""
    ids = {c["id"] for c in element.get("columns", []) or [] if "id" in c}
    for key in ("rowsBy", "columnsBy", "rows", "values"):
        for entry in element.get(key) or []:
            if isinstance(entry, str):
                ids.add(entry)
            elif isinstance(entry, dict):
                ids.add(entry.get("columnId") or entry.get("id"))
    return ids - {None}


def drop_dangling_axis_totals(spec: dict) -> list[tuple[str, list[str]]]:
    """Strip axisTotals that name no dimension. Returns (element id, axis ids)."""
    dropped = []
    for element in spec["document"]["elements"]:
        totals = element.get("axisTotals")
        if not totals:
            continue
        declared = declared_axes(element) | GRAND_TOTAL_AXES
        kept = [t for t in totals if t.get("axisId") in declared]
        if len(kept) != len(totals):
            gone = [t["axisId"] for t in totals if t.get("axisId") not in declared]
            element["axisTotals"] = kept
            dropped.append((element["id"], gone))
    return dropped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="send the PATCH; without it the diff is printed and nothing is sent",
    )
    parser.add_argument(
        "--fix-window-length",
        action="store_true",
        help="also narrow the window from 29 days to 28 (changes the definition)",
    )
    parser.add_argument(
        "--workbook-id",
        default=WORKBOOK_ID,
        help=f"workbook to edit (default {WORKBOOK_ID})",
    )
    parser.add_argument(
        "--backup-dir",
        default=".",
        help="where to write the pre-change spec (default: current directory)",
    )
    args = parser.parse_args()

    client = SigmaClient()

    try:
        spec = client.get_workbook_spec(args.workbook_id)
    except SigmaError as exc:
        fail(str(exc), exc.body)

    original = json.dumps(spec, indent=2, ensure_ascii=False, sort_keys=True)
    version = spec.get("documentVersion")
    print(f'"{spec.get("name")}" — document version {version}')

    try:
        changes = patch(spec, args.fix_window_length)
    except SigmaError as exc:
        fail(str(exc))

    for name, before, after in changes:
        print(f"\n  {name}")
        print(f"    - {before}")
        print(f"    + {after}")

    dangling = drop_dangling_axis_totals(spec)
    if dangling:
        print(f"\n  dropping {sum(len(a) for _, a in dangling)} dangling axisTotals:")
        for element_id, axes in dangling:
            print(f"    {element_id}: {', '.join(axes)}")
        print("    (PUT rejects these; they name no dimension on those elements)")

    if not args.apply:
        updated = json.dumps(spec, indent=2, ensure_ascii=False, sort_keys=True)
        diff = list(
            difflib.unified_diff(
                original.splitlines(), updated.splitlines(), "before", "after", n=1
            )
        )
        print(f"\n{len(changes)} formula(s) would change, {len(diff)} spec diff lines.")
        print("dry run — nothing sent to Sigma. Re-run with --apply to write it.")
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = Path(args.backup_dir) / f"merchandising_spec_v{version}_{stamp}.json"
    backup.write_text(original + "\n")
    print(f"\nwrote pre-change spec to {backup}")

    try:
        client.update_workbook_document(args.workbook_id, spec["document"])
    except SigmaError as exc:
        fail(str(exc), exc.body)

    # The PUT replaces the document wholesale, so read it back and account for
    # every difference. Anything here that is not one of the edits above is
    # something the round-trip lost.
    after_spec = client.get_workbook_spec(args.workbook_id)
    print(f"applied. document version {version} -> {after_spec.get('documentVersion')}")

    diff = list(
        difflib.unified_diff(
            original.splitlines(),
            json.dumps(after_spec, indent=2, ensure_ascii=False, sort_keys=True).splitlines(),
            "before",
            "after",
            n=0,
        )
    )
    changed = [line for line in diff if line[:1] in "+-" and line[:3] not in ("---", "+++")]
    print(f"{len(changed)} changed spec line(s) on read-back:")
    for line in changed:
        print(f"  {line[:200]}")


if __name__ == "__main__":
    main()
