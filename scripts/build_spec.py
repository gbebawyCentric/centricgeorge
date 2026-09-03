"""Assemble the workbook-as-code spec for the Daily Ecom Mail workbook.

The spec shape here is the one the Sigma API actually returns, read off a live
workbook rather than guessed:

    {"name", "description", "document": {
        "schemaVersion", "kind", "elements", "pages", "layout"}}

Three things about it are easy to get wrong and are worth stating plainly,
because the previous version of this file got all three wrong:

* ``elements`` is a **flat** list on the document, not nested inside pages.
  A page is only ``{id, name, pageWidth}``; the page an element belongs to is
  decided by ``layout``, not by nesting.
* ``layout`` is an **XML string** describing a 24-column CSS grid, one
  ``<Element>`` per element id. There is no per-element x/y/width/height.
* A table's data comes from ``source.kind = "warehouse-table"`` naming a
  ``[database, schema, table]`` path — **not** from inlined SQL. Each column
  carries a Sigma ``formula``.

That last point is why ``sql/`` is no longer inlined: the queries are ported to
Sigma column formulas here. ``sql/`` stays as the runnable Snowflake copy of the
same logic, and the ``PORTED FROM`` comments below tie each formula back to it.

    python3 scripts/build_spec.py            # write sigma/workbook_spec.json
    python3 scripts/build_spec.py --stdout   # print it instead
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = REPO_ROOT / "sigma" / "workbook_spec.json"

WORKBOOK_NAME = "Centric West — Daily Ecom Mail"

# Connection backing every element. This is "Centric Brands POC", which is the
# connection the existing Centric West - Ecom KPI QA workbook uses to read these
# exact SANDBOX.SBX_RRAJASEKAR tables, so it is known to resolve them.
#
# docs/data-mapping.md names CENTRIC_SNOWPATH_PRD (0a226657-…) instead. Both
# connections exist; only this one is demonstrated against these tables.
CONNECTION_ID = "82dc9446-e21c-4484-987d-79b52a490e2a"

DATABASE = "SANDBOX"
SCHEMA = "SBX_RRAJASEKAR"

# Accent used in the heading text. The source emails are themed per brand
# (Hudson #1B3A4B, Favorite Daughter #6B1D32, Joe's #111111); one workbook
# renders one theme for all three. See docs/data-mapping.md.
ACCENT = "#1B3A4B"
MUTED = "#6A6A6A"

# BRAND_ID -> BRAND_LABEL. ECOM_DAILY_PROMO is keyed by brand id while every
# other table is keyed by label, so the promo element derives a label column to
# bind to the same Brand control.
BRAND_ID_TO_LABEL = {
    "hudson-jeans": "Hudson",
    "favorite-daughter": "FD",
    "joes-jeans": "Joe's",
}

BRAND_ID_TO_DISPLAY_NAME = {
    "hudson-jeans": "Hudson Jeans",
    "favorite-daughter": "Favorite Daughter",
    "joes-jeans": "Joe's Jeans",
}


# --------------------------------------------------------------------------
# Sigma formula helpers
# --------------------------------------------------------------------------

def col(table: str, column: str) -> str:
    """A source column reference, e.g. [TB_SIGMA_DAILY_PULSE/DEMAND_AMT]."""
    return f"[{table}/{column}]"


def quote(value: str) -> str:
    """A Sigma string literal. Sigma escapes a double quote by doubling it."""
    return '"' + value.replace('"', '""') + '"'


def switch(subject: str, mapping: dict[str, str], default: str) -> str:
    """Switch(subject, k1, v1, k2, v2, …, default) — the port target for a
    SQL ``CASE <expr> WHEN … THEN …`` with a constant subject."""
    arms = ", ".join(f"{quote(k)}, {v}" for k, v in mapping.items())
    return f"Switch({subject}, {arms}, {default})"


def trend(pct: str) -> str:
    """PORTED FROM sql/el_kpi_tiles.sql — the CASE that colours each card.

        CASE WHEN PCT_VALUE IS NULL THEN 'none'
             WHEN PCT_VALUE > 0     THEN 'up'
             WHEN PCT_VALUE < 0     THEN 'down'
             ELSE 'flat' END
    """
    return (
        f'If(IsNull({pct}), "none", '
        f'If({pct} > 0, "up", '
        f'If({pct} < 0, "down", "flat")))'
    )


def style_color(table: str) -> str:
    """PORTED FROM sql/el_top_sold.sql and sql/el_top_returned.sql —
    ``STYLE || ' — ' || COLOR``."""
    return f'Concat({col(table, "STYLE")}, " — ", {col(table, "COLOR")})'


def column(column_id: str, formula: str, name: str) -> dict:
    return {"id": column_id, "formula": formula, "name": name}


def text_element(element_id: str, body: str, color: str = ACCENT) -> dict:
    return {
        "id": element_id,
        "kind": "text",
        "body": f'<p class="p-large"><span style="color: {color}">{body}</span></p>',
    }


def table_element(element_id: str, name: str, table: str, columns: list[dict]) -> dict:
    return {
        "id": element_id,
        "kind": "table",
        "source": {
            "connectionId": CONNECTION_ID,
            "kind": "warehouse-table",
            "path": [DATABASE, SCHEMA, table],
        },
        "columns": columns,
        "name": name,
        "order": [c["id"] for c in columns],
        "visibleAsSource": False,
    }


# --------------------------------------------------------------------------
# Elements
# --------------------------------------------------------------------------

GLANCE = "TB_SIGMA_QA_GLANCE_BRAND"
KPI_LONG = "TB_SIGMA_QA_KPI_LONG_BRAND"
CHANNEL_FD = "TB_SIGMA_CHANNEL_FD"
TOP_STYLES = "TB_SIGMA_DAILY_TOP_STYLES"
TOP_RETURNS = "TB_SIGMA_TOP_RETURNS"
PROMO = "ECOM_DAILY_PROMO"

# Every table the two controls filter, and the column each one filters on.
# TB_SIGMA_DAILY_TOP_STYLES and TB_SIGMA_TOP_RETURNS carry both DT_PT and
# REPORT_DATE; the two are equal on every row today (checked across all 870 and
# 145 rows), so REPORT_DATE is used throughout and one date control binds to
# every element uniformly.
BRAND_FILTER_TARGETS = [
    ("tbl_glance", "BRAND_LABEL"),
    ("tbl_performance", "BRAND_LABEL"),
    ("tbl_channel_dtc", "BRAND_LABEL"),
    ("tbl_top_sold", "BRAND_LABEL"),
    ("tbl_top_returned", "BRAND_LABEL"),
    ("tbl_promo", "BRAND_LABEL"),
]

DATE_FILTER_TARGETS = [
    ("tbl_glance", "REPORT_DATE"),
    ("tbl_performance", "REPORT_DATE"),
    ("tbl_channel_dtc", "REPORT_DATE"),
    ("tbl_top_sold", "REPORT_DATE"),
    ("tbl_top_returned", "REPORT_DATE"),
    ("tbl_promo", "PROMO_DATE"),
]


def _filters(targets: list[tuple[str, str]]) -> list[dict]:
    return [
        {"source": {"kind": "table", "elementId": element_id}, "columnId": column_id}
        for element_id, column_id in targets
    ]


def _controls() -> list[dict]:
    return [
        {
            "kind": "control",
            "controlId": "Brand",
            "id": "ctrl_brand",
            "name": "Brand",
            "controlType": "list",
            "mode": "include",
            "selectionMode": "single",
            "value": None,
            "filters": _filters(BRAND_FILTER_TARGETS),
            "source": {
                "kind": "source",
                "source": {"kind": "table", "elementId": "tbl_glance"},
                "columnId": "BRAND_LABEL",
            },
        },
        {
            "kind": "control",
            "controlId": "ReportDate",
            "id": "ctrl_dates",
            "name": "Report date",
            "controlType": "date-range",
            "mode": "between",
            "includeNulls": "always",
            "filters": _filters(DATE_FILTER_TARGETS),
        },
    ]


def _glance_element() -> dict:
    """PORTED FROM sql/el_header.sql and sql/el_kpi_tiles.sql.

    Both queries read one row of TB_SIGMA_QA_GLANCE_BRAND for the selected brand
    and day; the brand/date join in each is now the two controls. What the SQL
    computed in its SELECT list is ported to column formulas below.

    The four KPI tiles were a UNION ALL that turned that single row into four
    rows, one per tile. A UNION generates rows and so has no column-formula
    equivalent — but it does not need one: the four values are already four
    columns of this row, so each tile reads its own column and its own ported
    TREND formula.
    """
    return table_element(
        "tbl_glance",
        "Ecom KPIs (plan-tracked)",
        GLANCE,
        [
            column("BRAND_LABEL", col(GLANCE, "BRAND_LABEL"), "Brand"),
            column("REPORT_DATE", col(GLANCE, "REPORT_DATE"), "Report date"),
            # CASE g.BRAND_ID WHEN 'hudson-jeans' THEN 'Hudson Jeans' … ELSE BRAND_LABEL
            column(
                "BRAND_DISPLAY_NAME",
                switch(
                    col(GLANCE, "BRAND_ID"),
                    {k: quote(v) for k, v in BRAND_ID_TO_DISPLAY_NAME.items()},
                    col(GLANCE, "BRAND_LABEL"),
                ),
                "Brand display name",
            ),
            # DATEADD(day, -364, REPORT_DATE) — LY is the same weekday last year.
            column(
                "SAME_DAY_LY_DATE",
                f'DateAdd("day", -364, {col(GLANCE, "REPORT_DATE")})',
                "Same day LY",
            ),
            column("YESTERDAY_DEMAND", col(GLANCE, "YESTERDAY_DEMAND"), "Yesterday demand $"),
            column("Y_DEMAND_PLAN", col(GLANCE, "Y_DEMAND_PLAN"), "Yesterday plan $"),
            column("SAME_DAY_LY_DEMAND", col(GLANCE, "SAME_DAY_LY_DEMAND"), "Same day LY $"),
            column("PCT_YEST_VS_PLAN", col(GLANCE, "PCT_YEST_VS_PLAN"), "Yest vs plan"),
            column("TREND_YEST_VS_PLAN", trend(col(GLANCE, "PCT_YEST_VS_PLAN")), "Trend — yest vs plan"),
            column("PCT_YEST_VS_LY", col(GLANCE, "PCT_YEST_VS_LY"), "Yest vs LY"),
            column("TREND_YEST_VS_LY", trend(col(GLANCE, "PCT_YEST_VS_LY")), "Trend — yest vs LY"),
            column("MTD_DEMAND", col(GLANCE, "MTD_DEMAND"), "MTD demand $"),
            column("LY_MTD_DEMAND", col(GLANCE, "LY_MTD_DEMAND"), "LY MTD $"),
            column("TOTAL_MONTH_PLAN", col(GLANCE, "TOTAL_MONTH_PLAN"), "Month plan $"),
            column("PCT_MTD_VS_PLAN", col(GLANCE, "PCT_MTD_VS_PLAN"), "MTD vs plan"),
            column("TREND_MTD_VS_PLAN", trend(col(GLANCE, "PCT_MTD_VS_PLAN")), "Trend — MTD vs plan"),
            column("PCT_MTD_VS_LY", col(GLANCE, "PCT_MTD_VS_LY"), "MTD vs LY"),
            column("TREND_MTD_VS_LY", trend(col(GLANCE, "PCT_MTD_VS_LY")), "Trend — MTD vs LY"),
            column("TO_GO_VS_PLAN", col(GLANCE, "TO_GO_VS_PLAN"), "To-go $"),
            column("PCT_PLAN_ACHIEVED", col(GLANCE, "PCT_PLAN_ACHIEVED"), "% plan achieved"),
        ],
    )


def _performance_element() -> dict:
    """PORTED FROM sql/el_performance_grid.sql.

    The query's hand-rolled sort CASE is dropped: TB_SIGMA_QA_KPI_LONG_BRAND
    already carries METRIC_SORT (Demand Sales 1, Orders 2, Units 3, UPT 4,
    AOV 5, AUR 6), which is the same order.

    Not ported — the Demand Plan row. The email's grid carries one, assembled by
    UNION-ing the glance plan columns in at sort position 2. There is no
    'Demand Plan' metric in this table, and a column formula cannot add a row.
    Its figures are on tbl_glance above (Yesterday plan $, Month plan $, To-go $,
    % plan achieved); making it a grid row needs an upstream view. See README.
    """
    return table_element(
        "tbl_performance",
        "Performance detail — ecom only",
        KPI_LONG,
        [
            column("BRAND_LABEL", col(KPI_LONG, "BRAND_LABEL"), "Brand"),
            column("REPORT_DATE", col(KPI_LONG, "REPORT_DATE"), "Report date"),
            column("METRIC_SORT", col(KPI_LONG, "METRIC_SORT"), "Order"),
            column("METRIC", col(KPI_LONG, "METRIC"), "Metric"),
            column("YESTERDAY", col(KPI_LONG, "YESTERDAY"), "Yesterday"),
            column("SAME_DAY_LY", col(KPI_LONG, "SAME_DAY_LY"), "Same Day LY"),
            column("MTD", col(KPI_LONG, "MTD"), "MTD"),
            column("LY_MTD", col(KPI_LONG, "LY_MTD"), "LY MTD"),
            column("TOTAL_MONTH_PLAN", col(KPI_LONG, "TOTAL_MONTH_PLAN"), "Month Plan"),
            column("TO_GO_VS_PLAN", col(KPI_LONG, "TO_GO_VS_PLAN"), "To-Go $"),
            column("PCT_PLAN_ACHIEVED", col(KPI_LONG, "PCT_PLAN_ACHIEVED"), "% Achieved"),
        ],
    )


def _channel_element() -> dict:
    """PORTED FROM sql/el_channel_dtc.sql — the CHANNEL ordering CASE.

    Favorite Daughter only; TB_SIGMA_CHANNEL_FD holds rows for it alone, so the
    element is empty for Hudson and Joe's.
    """
    return table_element(
        "tbl_channel_dtc",
        "Retail + total DTC",
        CHANNEL_FD,
        [
            column("BRAND_LABEL", col(CHANNEL_FD, "BRAND_LABEL"), "Brand"),
            column("REPORT_DATE", col(CHANNEL_FD, "REPORT_DATE"), "Report date"),
            column(
                "CHANNEL_ORDER",
                switch(
                    col(CHANNEL_FD, "CHANNEL"),
                    {
                        "Ecom (website)": "1",
                        "Retail (POS / boutiques)": "2",
                        "Total DTC": "3",
                    },
                    "99",
                ),
                "Order",
            ),
            column("CHANNEL", col(CHANNEL_FD, "CHANNEL"), "Channel"),
            column("Y_DEMAND", col(CHANNEL_FD, "Y_DEMAND"), "Yesterday demand"),
            column("Y_ORDERS", col(CHANNEL_FD, "Y_ORDERS"), "Yday orders"),
            column("MTD_DEMAND", col(CHANNEL_FD, "MTD_DEMAND"), "MTD demand"),
        ],
    )


def _top_sold_element() -> dict:
    """PORTED FROM sql/el_top_sold.sql — the STYLE_COLOR concatenation.

    The query's ``WHERE RANK_IN_DAY <= 10`` is not expressed here: a filter is
    not a column formula, and this schema has no demonstrated per-element filter
    key. RANK_IN_DAY is kept as the first column so the top 10 read off the top;
    add the filter in the UI if the tail is unwanted.
    """
    return table_element(
        "tbl_top_sold",
        "Top 10 sold",
        TOP_STYLES,
        [
            column("BRAND_LABEL", col(TOP_STYLES, "BRAND_LABEL"), "Brand"),
            column("REPORT_DATE", col(TOP_STYLES, "REPORT_DATE"), "Report date"),
            column("RANK_IN_DAY", col(TOP_STYLES, "RANK_IN_DAY"), "#"),
            column("STYLE_COLOR", style_color(TOP_STYLES), "Style / colour"),
            column("UNITS", col(TOP_STYLES, "QTY"), "Units"),
            column("DEMAND_AMT", col(TOP_STYLES, "DEMAND_AMT"), "Demand $"),
        ],
    )


def _top_returned_element() -> dict:
    """PORTED FROM sql/el_top_returned.sql. Shopify refunds only — not the Loop
    return rate, which is not in Snowflake. Same RANK_IN_DAY note as top sold."""
    return table_element(
        "tbl_top_returned",
        "Top 10 returned",
        TOP_RETURNS,
        [
            column("BRAND_LABEL", col(TOP_RETURNS, "BRAND_LABEL"), "Brand"),
            column("REPORT_DATE", col(TOP_RETURNS, "REPORT_DATE"), "Report date"),
            column("RANK_IN_DAY", col(TOP_RETURNS, "RANK_IN_DAY"), "#"),
            column("STYLE_COLOR", style_color(TOP_RETURNS), "Style / colour"),
            column("UNITS", col(TOP_RETURNS, "QTY"), "Units"),
        ],
    )


def _promo_element() -> dict:
    """PORTED FROM sql/el_promo.sql — the scheduled-copy half only.

    ECOM_DAILY_PROMO is keyed by BRAND_ID while every other table is keyed by
    BRAND_LABEL, so BRAND_LABEL is derived here to bind to the same control.
    NULLIF(TRIM(COALESCE(…))) is ported to the If/Trim below, so a blank cell
    reads as the email's em dash rather than an empty string.

    Not ported — the promo purchase figures (PROMO_DISCOUNT_AMT, PROMO_ORDERS).
    The query gets them by de-duplicating SHOPIFY_ORDERS_ADF to the latest row
    per order id with ROW_NUMBER(), joining that to TB_SIGMA_ORDERS_QA, then
    aggregating. That is a cross-table join and aggregation, not a column
    formula, and TB_SIGMA_ORDERS_QA carries no TOTALDISCOUNT to aggregate on its
    own. It needs an upstream view. See README.
    """
    promo_text = col(PROMO, "PROMO_TEXT")
    email_text = col(PROMO, "EMAIL_TEXT")
    return table_element(
        "tbl_promo",
        "Promo & email",
        PROMO,
        [
            column(
                "BRAND_LABEL",
                switch(
                    col(PROMO, "BRAND_ID"),
                    {k: quote(v) for k, v in BRAND_ID_TO_LABEL.items()},
                    col(PROMO, "BRAND_ID"),
                ),
                "Brand",
            ),
            column("PROMO_DATE", col(PROMO, "PROMO_DATE"), "Date"),
            column(
                "PROMO_TEXT",
                f'If(Trim(Coalesce({promo_text}, "")) = "", '
                f'"— (none on Marketing Calendar for this day)", {promo_text})',
                "Promo",
            ),
            column(
                "EMAIL_TEXT",
                f'If(Trim(Coalesce({email_text}, "")) = "", "—", {email_text})',
                "Email",
            ),
        ],
    )


def _elements() -> list[dict]:
    """Every element, in the order the email reads."""
    return [
        text_element("txt_title", "Centric West — Daily ecom recap"),
        text_element(
            "txt_sub",
            "Brand-owned website sales. Hudson excludes the Nordstrom marketplace; "
            "Favorite Daughter shows its retail boutiques separately below. "
            "LY = same weekday last year (−364 days). Pick a brand and a report "
            "date; a scheduled export per brand sends the recap.",
            MUTED,
        ),
        *_controls(),
        text_element("txt_kpi_heading", "Ecom KPIs (plan-tracked)"),
        _glance_element(),
        text_element("txt_promo_heading", "Promo & email"),
        _promo_element(),
        text_element("txt_perf_heading", "Performance detail — ecom only"),
        _performance_element(),
        text_element(
            "txt_kpi_note",
            "KPI additions in progress: Margin $/%, Media Spend, CAC/CPO, "
            "Traffic, CVR, Net $. These rows are present but blank on purpose.",
            MUTED,
        ),
        text_element(
            "txt_channel_heading",
            "Retail + total DTC — Favorite Daughter only",
        ),
        _channel_element(),
        text_element("txt_top_sold_heading", "Top 10 sold"),
        _top_sold_element(),
        text_element("txt_top_returned_heading", "Top 10 returned"),
        _top_returned_element(),
        text_element(
            "txt_footer",
            "Daily send (no weekend rollups). Promo copy from the Marketing "
            "Calendar. Top 10 returned is Shopify refunds only — not the Loop "
            "return rate, which is not yet in Snowflake.",
            "#8A8A8A",
        ),
        text_element(
            "txt_gaps",
            "Not reproduced from SQL: the Demand Plan grid row and the promo "
            "purchase totals. Both need an upstream view — see the README.",
            "#8A8A8A",
        ),
    ]


# --------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------

PAGE_ID = "page_mail"

# Grid rows each element occupies. Controls sit side by side on one row; every
# other element spans the full 24 columns.
ELEMENT_HEIGHTS = {
    "txt_title": 1,
    "txt_sub": 2,
    "txt_kpi_heading": 1,
    "tbl_glance": 12,
    "txt_promo_heading": 1,
    "tbl_promo": 8,
    "txt_perf_heading": 1,
    "tbl_performance": 16,
    "txt_kpi_note": 1,
    "txt_channel_heading": 1,
    "tbl_channel_dtc": 8,
    "txt_top_sold_heading": 1,
    "tbl_top_sold": 14,
    "txt_top_returned_heading": 1,
    "tbl_top_returned": 14,
    "txt_footer": 2,
    "txt_gaps": 1,
}

CONTROL_COLUMNS = {
    "ctrl_brand": (1, 7),
    "ctrl_dates": (7, 16),
}


def _layout(elements: list[dict]) -> str:
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        f'<Page type="grid" gridTemplateColumns="repeat(24, 1fr)" '
        f'gridTemplateRows="auto" id="{PAGE_ID}">',
    ]

    row = 1
    for element in elements:
        element_id = element["id"]
        if element_id in CONTROL_COLUMNS:
            start, end = CONTROL_COLUMNS[element_id]
            # Both controls share one row; only advance past the last of them.
            lines.append(
                f'  <Element elementId="{element_id}" gridColumn="{start} / {end}" '
                f'gridRow="{row} / {row + 1}"/>'
            )
            if element_id == list(CONTROL_COLUMNS)[-1]:
                row += 1
            continue

        height = ELEMENT_HEIGHTS[element_id]
        lines.append(
            f'  <Element elementId="{element_id}" gridColumn="1 / 25" '
            f'gridRow="{row} / {row + height}"/>'
        )
        row += height

    lines.append("</Page>")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------

def build_spec() -> dict:
    elements = _elements()
    return {
        "name": WORKBOOK_NAME,
        "description": (
            "Daily ecom recap for Hudson, Favorite Daughter and Joe's. Mirrors the "
            "daily recap email: KPI tiles, promo block, performance grid, FD "
            "retail/DTC split, and top 10 sold/returned. Pick a brand and report "
            "date, then schedule one send per brand."
        ),
        "document": {
            "schemaVersion": 1,
            "kind": "workbook",
            "elements": elements,
            "pages": [
                {"id": PAGE_ID, "name": "Daily Ecom Mail", "pageWidth": "full"}
            ],
            "layout": _layout(elements),
        },
    }


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

    elements = spec["document"]["elements"]
    tables = [e for e in elements if e.get("kind") == "table"]
    formulas = sum(len(e["columns"]) for e in tables)
    print(
        f"wrote {SPEC_PATH.relative_to(REPO_ROOT)} "
        f"({len(elements)} elements, {len(tables)} tables, {formulas} column formulas)"
    )


if __name__ == "__main__":
    main()
