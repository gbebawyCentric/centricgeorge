"""Assemble the workbook-as-code spec for the Daily Ecom Mail workbook.

The SQL for each element lives in sql/*.sql — one canonical, runnable copy that
can be tested directly against Snowflake — and is inlined here at build time so
the emitted spec is self-contained, which is what the API requires.

    python3 scripts/build_spec.py            # write sigma/workbook_spec.json
    python3 scripts/build_spec.py --stdout   # print it instead
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = REPO_ROOT / "sql"
SPEC_PATH = REPO_ROOT / "sigma" / "workbook_spec.json"

WORKBOOK_NAME = "Centric West — Daily Ecom Mail"

# Snowflake connection backing every element (CENTRIC_SNOWPATH_PRD).
CONNECTION_ID = "0a226657-a09f-4684-9465-820374fb6c30"

# Accent used for the banner, table headers and section rules. The source
# emails are themed per brand (Hudson #1B3A4B, Favorite Daughter #6B1D32,
# Joe's #111111); a single workbook renders one theme for all three, so this is
# the neutral default. See docs/data-mapping.md for the per-brand option.
ACCENT = "#1B3A4B"

BRANDS = ["Hudson", "FD", "Joe's"]


def read_sql(name: str) -> str:
    return (SQL_DIR / f"{name}.sql").read_text().rstrip() + "\n"


def build_spec() -> dict:
    return {
        "name": WORKBOOK_NAME,
        "description": (
            "Daily ecom recap for Hudson, Favorite Daughter and Joe's. Mirrors the "
            "daily recap email: narrative header, four plan-tracked KPI tiles, promo "
            "block, performance grid, FD retail/DTC split, and top 10 sold/returned. "
            "Pick a brand and report date, then schedule one send per brand."
        ),
        "controls": [
            {
                "id": "ctl_brand",
                "type": "list",
                "label": "Brand",
                "values": BRANDS,
                "defaultValue": "Hudson",
                "allowMultiple": False,
                "allowEmpty": False,
            },
            {
                "id": "ctl_report_date",
                "type": "date",
                "label": "Report date",
                # Sends run the morning after, so the default is the day being
                # reported on, not the day the send fires.
                "defaultValue": "yesterday",
            },
        ],
        "dataSources": [
            {
                "id": f"ds_{name}",
                "type": "sql",
                "connectionId": CONNECTION_ID,
                "sql": read_sql(f"el_{name}"),
                "parameters": {
                    "brand_label": {"control": "ctl_brand"},
                    "report_date": {"control": "ctl_report_date"},
                },
            }
            for name in (
                "header",
                "kpi_tiles",
                "promo",
                "performance_grid",
                "channel_dtc",
                "top_sold",
                "top_returned",
            )
        ],
        "pages": [
            {
                "id": "page_mail",
                "name": "Daily Ecom Mail",
                "elements": _elements(),
            }
        ],
    }


def _elements() -> list[dict]:
    """Page elements, top to bottom, in the order the email reads."""
    elements: list[dict] = []

    # --- banner ---------------------------------------------------------
    elements.append(
        {
            "id": "txt_header",
            "type": "text",
            "dataSource": "ds_header",
            "layout": {"x": 0, "y": 0, "width": 12, "height": 4},
            "style": {"background": ACCENT, "color": "#FFFFFF"},
            "content": [
                {"text": "{{BRAND_DISPLAY_NAME}}", "size": 28, "bold": True},
                {"text": "DAILY ECOM RECAP", "size": 11, "letterSpacing": 1.4},
                {"text": "{{SCOPE_LINE}}", "size": 13},
                {
                    "text": "Today = {{TODAY_LABEL}} · Same Day LY = "
                            "{{SAME_DAY_LY_LABEL}} (same weekday)",
                    "size": 13,
                },
                {
                    # The narrative paragraph the email opens with.
                    "text": (
                        "Yesterday's ecom demand was {{YESTERDAY_DEMAND:currency_kmb}} "
                        "vs plan {{Y_DEMAND_PLAN:currency_kmb}} "
                        "({{PCT_YEST_VS_PLAN:percent}}) and {{PCT_YEST_VS_LY:percent}} "
                        "to same-day LY. "
                        "MTD ecom demand is {{MTD_DEMAND:currency_kmb}} vs month plan "
                        "{{TOTAL_MONTH_PLAN:currency_kmb}} "
                        "({{PCT_MTD_VS_PLAN:percent}} to MTD plan, "
                        "{{PCT_MTD_VS_LY:percent}} to LY MTD)."
                    ),
                    "size": 14,
                    "callout": True,
                },
            ],
        }
    )

    # --- four KPI tiles --------------------------------------------------
    # One element per tile, each bound to a single row of ds_kpi_tiles, so the
    # row of cards matches the email rather than rendering as a table.
    tiles = [
        ("kpi_yest_vs_plan", 1, "Yesterday vs plan"),
        ("kpi_yest_vs_ly", 2, "Yesterday vs LY"),
        ("kpi_mtd_vs_plan", 3, "MTD vs plan"),
        ("kpi_mtd_vs_ly", 4, "MTD vs LY"),
    ]
    elements.append(
        {
            "id": "txt_kpi_heading",
            "type": "text",
            "layout": {"x": 0, "y": 4, "width": 12, "height": 1},
            "content": [{"text": "ECOM KPIs (PLAN-TRACKED)", "size": 12, "color": "#6A6A6A"}],
        }
    )
    for index, (element_id, tile_order, label) in enumerate(tiles):
        elements.append(
            {
                "id": element_id,
                "type": "kpi",
                "dataSource": "ds_kpi_tiles",
                "filter": {"column": "TILE_ORDER", "equals": tile_order},
                "layout": {"x": index * 3, "y": 5, "width": 3, "height": 2},
                "label": label,
                "valueColumn": "PCT_VALUE",
                "format": "percent",
                "nullDisplay": "—",
                "subtitleColumns": ["PRIMARY_AMT", "COMPARE_AMT"],
                # Same red/green/grey cards as the email.
                "conditionalFormatting": [
                    {"when": {"column": "TREND", "equals": "up"},
                     "background": "#E7F6EC", "color": "#0B7A3B"},
                    {"when": {"column": "TREND", "equals": "down"},
                     "background": "#FDECEA", "color": "#C62828"},
                    {"when": {"column": "TREND", "equals": "none"},
                     "background": "#F4F4F4", "color": "#555555"},
                ],
            }
        )

    # --- promo block -----------------------------------------------------
    elements.append(
        {
            "id": "txt_promo",
            "type": "text",
            "dataSource": "ds_promo",
            "layout": {"x": 0, "y": 7, "width": 12, "height": 2},
            "style": {"borderLeft": ACCENT, "background": "#FAFAFA"},
            "content": [
                {"text": "PROMO & EMAIL", "size": 12, "color": "#6A6A6A"},
                {
                    "text": "Promo: {{PROMO_TEXT|— (none on Marketing Calendar for this day)}}",
                    "size": 13,
                },
                {"text": "Email: {{EMAIL_TEXT|—}}", "size": 13},
                {
                    "text": (
                        "Promo purchase (discounts applied): "
                        "{{PROMO_DISCOUNT_AMT:currency_kmb}} across {{PROMO_ORDERS}} "
                        "orders (Shopify TOTALDISCOUNT)"
                    ),
                    "size": 13,
                },
            ],
        }
    )

    # --- performance grid ------------------------------------------------
    elements.append(
        {
            "id": "tbl_performance",
            "type": "table",
            "dataSource": "ds_performance_grid",
            "layout": {"x": 0, "y": 9, "width": 12, "height": 5},
            "title": "Performance detail — ecom only",
            "headerStyle": {"background": ACCENT, "color": "#FFFFFF"},
            "nullDisplay": "—",
            "columns": [
                {"column": "METRIC", "label": "Metric", "align": "left", "bold": True},
                {"column": "YESTERDAY", "label": "Yesterday", "align": "right"},
                {"column": "SAME_DAY_LY", "label": "Same Day LY", "align": "right"},
                {"column": "MTD", "label": "MTD", "align": "right"},
                {"column": "LY_MTD", "label": "LY MTD", "align": "right"},
                {"column": "TOTAL_MONTH_PLAN", "label": "Month Plan", "align": "right"},
                {"column": "TO_GO_VS_PLAN", "label": "To-Go $", "align": "right"},
                {"column": "PCT_PLAN_ACHIEVED", "label": "% Achieved",
                 "align": "right", "format": "percent"},
            ],
        }
    )
    elements.append(
        {
            "id": "txt_kpi_note",
            "type": "text",
            "layout": {"x": 0, "y": 14, "width": 12, "height": 1},
            "content": [
                {
                    "text": "KPI additions in progress: Margin $/%, Media Spend, "
                            "CAC/CPO, Traffic, CVR, Net $.",
                    "size": 12,
                    "color": "#888888",
                }
            ],
        }
    )

    # --- retail / DTC (Favorite Daughter only) ---------------------------
    # FD is the only brand whose boutiques run on Shopify, so this element is
    # empty for the other two and hidden rather than shown blank.
    elements.append(
        {
            "id": "tbl_channel_dtc",
            "type": "table",
            "dataSource": "ds_channel_dtc",
            "layout": {"x": 0, "y": 15, "width": 12, "height": 3},
            "title": "Retail + total DTC",
            "headerStyle": {"background": ACCENT, "color": "#FFFFFF"},
            "hideWhenEmpty": True,
            "columns": [
                {"column": "CHANNEL", "label": "Channel", "align": "left", "bold": True},
                {"column": "Y_DEMAND", "label": "Yesterday demand",
                 "align": "right", "format": "currency"},
                {"column": "Y_ORDERS", "label": "Yday orders", "align": "right"},
                {"column": "MTD_DEMAND", "label": "MTD demand",
                 "align": "right", "format": "currency"},
            ],
        }
    )

    # --- top 10 sold / returned, side by side ----------------------------
    elements.append(
        {
            "id": "tbl_top_sold",
            "type": "table",
            "dataSource": "ds_top_sold",
            "layout": {"x": 0, "y": 18, "width": 6, "height": 6},
            "title": "Top 10 sold",
            "headerStyle": {"background": ACCENT, "color": "#FFFFFF"},
            "columns": [
                {"column": "RANK_IN_DAY", "label": "#", "align": "left", "width": 40},
                {"column": "STYLE_COLOR", "label": "Style / colour", "align": "left"},
                {"column": "UNITS", "label": "Units", "align": "right"},
                {"column": "DEMAND_AMT", "label": "Demand $",
                 "align": "right", "format": "currency"},
            ],
        }
    )
    elements.append(
        {
            "id": "tbl_top_returned",
            "type": "table",
            "dataSource": "ds_top_returned",
            "layout": {"x": 6, "y": 18, "width": 6, "height": 6},
            "title": "Top 10 returned",
            "headerStyle": {"background": ACCENT, "color": "#FFFFFF"},
            "emptyMessage": "No rows for this day.",
            "columns": [
                {"column": "RANK_IN_DAY", "label": "#", "align": "left", "width": 40},
                {"column": "STYLE_COLOR", "label": "Style / colour", "align": "left"},
                {"column": "UNITS", "label": "Units", "align": "right"},
            ],
        }
    )

    # --- footer ----------------------------------------------------------
    elements.append(
        {
            "id": "txt_footer",
            "type": "text",
            "layout": {"x": 0, "y": 24, "width": 12, "height": 2},
            "content": [
                {
                    "text": (
                        "Daily send (no weekend rollups). LY = same weekday (−364). "
                        "Promo from Marketing Calendar; promo purchase $ = Shopify "
                        "TOTALDISCOUNT. Top 10 returned is Shopify refunds only — not "
                        "the Loop return rate, which is not yet in Snowflake."
                    ),
                    "size": 12,
                    "color": "#8A8A8A",
                }
            ],
        }
    )

    return elements


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stdout", action="store_true", help="print the spec instead of writing it"
    )
    args = parser.parse_args()

    spec = build_spec()
    rendered = json.dumps(spec, indent=2, ensure_ascii=False) + "\n"

    if args.stdout:
        print(rendered, end="")
        return

    SPEC_PATH.parent.mkdir(parents=True, exist_ok=True)
    SPEC_PATH.write_text(rendered)
    element_count = sum(len(page["elements"]) for page in spec["pages"])
    print(
        f"wrote {SPEC_PATH.relative_to(REPO_ROOT)} "
        f"({len(spec['dataSources'])} data sources, {element_count} elements)"
    )


if __name__ == "__main__":
    main()
