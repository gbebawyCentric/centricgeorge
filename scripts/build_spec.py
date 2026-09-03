"""Assemble the Daily Ecom Mail workbook spec — one workbook per brand.

The recap emails are three separately themed documents (Hudson navy, Favorite
Daughter maroon, Joe's black), so this builds one workbook per brand rather than
one report with a brand picker. Per-brand differences live in brands.py; the SQL
that column formulas cannot express lives in sources.py.

    python3 scripts/build_spec.py                 # write all three
    python3 scripts/build_spec.py --brand FD      # just one
    python3 scripts/build_spec.py --brand FD --stdout

Schema notes, all learned by deploying against the live API:

* ``elements`` is a flat list on ``document``; the page an element belongs to is
  decided by ``layout``, and every element must appear there. To keep one off
  the report, put it on a page marked ``visibility: "hidden"``.
* ``layout`` is an XML string — a ``<Page>`` per page holding ``<Element>`` and
  ``<Container>`` nodes on a 24-column grid.
* A text element is ``<p>`` only; the inline set is ``<u> <sub> <sup> <span>
  <a>`` and a ``<span style>`` may carry only color, background-color,
  font-size and font-family. No ``<h1>``, no letter-spacing, and no data
  binding — which is why the email's narrative paragraph is not reproduced.
* A table's ``source`` is ``warehouse-table``, ``sql`` or ``table`` (another
  element). Inline SQL columns are addressed ``[Custom SQL/COLUMN]``.
* ``display`` is rejected on anything but a pivot-table.
* A ``kpi-chart`` cannot reference another element's columns by name, so each
  card reads its own source directly.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import brands as brand_config
import sources
from brands import Brand

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_DIR = REPO_ROOT / "sigma"

# Connection backing every element: "Centric Brands POC", the one the existing
# Ecom KPI QA workbook uses to read these SANDBOX.SBX_RRAJASEKAR tables.
CONNECTION_ID = "82dc9446-e21c-4484-987d-79b52a490e2a"

DATABASE = "SANDBOX"
SCHEMA = "SBX_RRAJASEKAR"

# Neutrals taken from the rendered email.
ON_ACCENT = "#FFFFFF"
INK = "#111111"
MUTED = "#6A6A6A"
BODY = "#555555"
FAINT = "#888888"
GREEN = "#0B7A3B"
RED = "#C62828"

CURRENCY = {"kind": "number", "formatString": "$,.0f", "currencySymbol": "$"}
PERCENT = {"kind": "number", "formatString": ",.1%"}
INTEGER = {"kind": "number", "formatString": ",d"}
DECIMAL = {"kind": "number", "formatString": ",.2f"}
DATE = {"kind": "datetime", "formatString": "%m/%d/%Y"}

# The 44px square thumbnail the email prints beside each product row.
THUMBNAIL = {"type": "fixed", "height": 44, "width": 44, "preserveAspectRatio": "preserve"}

GLANCE = "TB_SIGMA_QA_GLANCE_BRAND"
CHANNEL_FD = "TB_SIGMA_CHANNEL_FD"
PROMO = "ECOM_DAILY_PROMO"


# --------------------------------------------------------------------------
# Formula helpers
# --------------------------------------------------------------------------

def col(table_name: str, column_name: str) -> str:
    return f"[{table_name}/{column_name}]"


def sql_col(column_name: str) -> str:
    """Inline-sql sources are always addressed under the literal qualifier
    "Custom SQL"; a bare [COLUMN] resolves to type `error`."""
    return f"[Custom SQL/{column_name}]"


def quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def switch(subject: str, mapping: dict[str, str], default: str) -> str:
    arms = ", ".join(f"{quote(k)}, {v}" for k, v in mapping.items())
    return f"Switch({subject}, {arms}, {default})"


def trend(pct: str) -> str:
    """PORTED FROM sql/el_kpi_tiles.sql — the CASE behind each card's colour."""
    return (
        f'If(IsNull({pct}), "none", '
        f'If({pct} > 0, "up", If({pct} < 0, "down", "flat")))'
    )


# --------------------------------------------------------------------------
# Element constructors
# --------------------------------------------------------------------------

def column(
    column_id: str,
    formula: str,
    name: str,
    fmt: dict | None = None,
    hidden: bool = False,
    image: dict | None = None,
) -> dict:
    entry: dict = {"id": column_id, "formula": formula, "name": name}
    if fmt:
        entry["format"] = fmt
    if image:
        entry["image"] = image
    if hidden:
        # The key columns the controls filter on have to exist but would
        # otherwise turn the report back into a data dump.
        entry["hidden"] = True
    return entry


def text(
    element_id: str,
    body: str,
    color: str = INK,
    font_size: int | None = None,
) -> dict:
    style = f"color: {color}"
    if font_size:
        style += f"; font-size: {font_size}px"
    return {
        "id": element_id,
        "kind": "text",
        "body": f'<p class="p-large"><span style="{style}">{body}</span></p>',
    }


def heading(element_id: str, label: str) -> dict:
    """The small grey uppercase section rules the email uses."""
    return text(element_id, label.upper(), MUTED, 12)


def warehouse(table_name: str) -> dict:
    return {
        "connectionId": CONNECTION_ID,
        "kind": "warehouse-table",
        "path": [DATABASE, SCHEMA, table_name],
    }


def sql(statement: str) -> dict:
    return {"connectionId": CONNECTION_ID, "kind": "sql", "statement": statement}


def table(
    element_id: str,
    name: str,
    source: dict,
    columns: list[dict],
    *,
    sort: list[dict] | None = None,
    conditional_formats: list[dict] | None = None,
    banding: bool = True,
) -> dict:
    element: dict = {
        "id": element_id,
        "kind": "table",
        "source": source,
        "columns": columns,
        "name": name,
        "order": [c["id"] for c in columns],
        "visibleAsSource": True,
    }
    if sort:
        element["sort"] = sort
    if conditional_formats:
        element["conditionalFormats"] = conditional_formats
    if banding:
        element["tableStyle"] = {"banding": "shown"}
    return element


def kpi_card(
    element_id: str,
    label: str,
    source: dict,
    brand_formula: str,
    date_formula: str,
    value_formula: str,
    comparison_formula: str | None = None,
    fmt: dict | None = CURRENCY,
) -> dict:
    """One of the email's cards: a big value, and the change against a
    comparison value under it. Each card reads its own source because a
    kpi-chart cannot reference another element's columns by name."""
    columns = [
        column("BRAND_LABEL", brand_formula, "Brand", hidden=True),
        column("REPORT_DATE", date_formula, "Report date", DATE, hidden=True),
        column("kpi_value", value_formula, label, fmt),
    ]
    element: dict = {
        "id": element_id,
        "kind": "kpi-chart",
        "source": source,
        "columns": columns,
        "value": {"columnId": "kpi_value"},
    }
    if comparison_formula:
        columns.append(column("kpi_compare", comparison_formula, "vs", fmt))
        element["comparisonColumn"] = {"columnId": "kpi_compare"}
    return element


# --------------------------------------------------------------------------
# Data elements
# --------------------------------------------------------------------------

# (element id, label, value column, comparison column) on the glance table —
# the four pairings the email's cards show.
KPI_CARDS = [
    ("kpi_yest_vs_plan", "Yesterday vs plan", "YESTERDAY_DEMAND", "Y_DEMAND_PLAN"),
    ("kpi_yest_vs_ly", "Yesterday vs LY", "YESTERDAY_DEMAND", "SAME_DAY_LY_DEMAND"),
    ("kpi_mtd_vs_plan", "MTD vs plan", "MTD_DEMAND", "TOTAL_MONTH_PLAN"),
    ("kpi_mtd_vs_ly", "MTD vs LY", "MTD_DEMAND", "LY_MTD_DEMAND"),
]


def _kpi_cards() -> list[dict]:
    return [
        kpi_card(
            element_id, label, warehouse(GLANCE),
            col(GLANCE, "BRAND_LABEL"), col(GLANCE, "REPORT_DATE"),
            f'Sum({col(GLANCE, value_column)})',
            f'Sum({col(GLANCE, compare_column)})',
        )
        for element_id, label, value_column, compare_column in KPI_CARDS
    ]


def _promo_cards() -> list[dict]:
    return [
        kpi_card("kpi_promo_amt", "Promo purchase (discounts applied)",
                 sql(sources.PROMO_TOTALS), sql_col("BRAND_LABEL"),
                 sql_col("REPORT_DATE"), f'Sum({sql_col("PROMO_DISCOUNT_AMT")})',
                 fmt=CURRENCY),
        kpi_card("kpi_promo_orders", "Orders with a discount",
                 sql(sources.PROMO_TOTALS), sql_col("BRAND_LABEL"),
                 sql_col("REPORT_DATE"), f'Sum({sql_col("PROMO_ORDERS")})',
                 fmt=INTEGER),
    ]


def _retail_added_cards() -> list[dict]:
    """The email's "Retail boutiques added $11.3k / 37 orders yesterday" line.
    Not included in the ecom figures above it."""
    return [
        kpi_card("kpi_retail_amt", "Retail boutiques added (yesterday)",
                 sql(sources.RETAIL_ADDED), sql_col("BRAND_LABEL"),
                 sql_col("REPORT_DATE"), f'Sum({sql_col("DEMAND_AMT")})',
                 fmt=CURRENCY),
        kpi_card("kpi_retail_orders", "Retail orders (yesterday)",
                 sql(sources.RETAIL_ADDED), sql_col("BRAND_LABEL"),
                 sql_col("REPORT_DATE"), f'Sum({sql_col("ORDERS")})',
                 fmt=INTEGER),
    ]


def _promo_element() -> dict:
    """PORTED FROM sql/el_promo.sql — the scheduled-copy half.

    ECOM_DAILY_PROMO is keyed by BRAND_ID while every other table is keyed by
    BRAND_LABEL, so a label is derived here to bind to the same control.
    NULLIF(TRIM(COALESCE(…))) becomes the If/Trim below.
    """
    promo_text = col(PROMO, "PROMO_TEXT")
    email_text = col(PROMO, "EMAIL_TEXT")
    labels = {b.brand_id: quote(b.label) for b in brand_config.BRANDS}
    return table(
        "tbl_promo",
        "Scheduled promo copy",
        warehouse(PROMO),
        [
            column("BRAND_LABEL",
                   switch(col(PROMO, "BRAND_ID"), labels, col(PROMO, "BRAND_ID")),
                   "Brand", hidden=True),
            column("PROMO_DATE", col(PROMO, "PROMO_DATE"), "Date", DATE, hidden=True),
            column("PROMO_TEXT",
                   f'If(Trim(Coalesce({promo_text}, "")) = "", '
                   f'"— (none on Marketing Calendar for this day)", {promo_text})',
                   "Promo"),
            column("EMAIL_TEXT",
                   f'If(Trim(Coalesce({email_text}, "")) = "", "—", {email_text})',
                   "Email"),
        ],
        banding=False,
    )


def _performance_element() -> dict:
    """PORTED FROM sql/el_performance_grid.sql. Ordering uses the table's own
    METRIC_SORT; the Demand Plan row needs the UNION in sources.PERFORMANCE."""
    return table(
        "tbl_performance",
        "Performance detail — ecom only",
        sql(sources.PERFORMANCE),
        [
            column("BRAND_LABEL", sql_col("BRAND_LABEL"), "Brand", hidden=True),
            column("REPORT_DATE", sql_col("REPORT_DATE"), "Report date", DATE, hidden=True),
            column("METRIC_SORT", sql_col("METRIC_SORT"), "Order", hidden=True),
            column("METRIC", sql_col("METRIC"), "Metric"),
            column("YESTERDAY", sql_col("YESTERDAY"), "Yesterday", DECIMAL),
            column("SAME_DAY_LY", sql_col("SAME_DAY_LY"), "Same Day LY", DECIMAL),
            column("MTD", sql_col("MTD"), "MTD", DECIMAL),
            column("LY_MTD", sql_col("LY_MTD"), "LY MTD", DECIMAL),
            column("TOTAL_MONTH_PLAN", sql_col("TOTAL_MONTH_PLAN"), "Month Plan", CURRENCY),
            column("TO_GO_VS_PLAN", sql_col("TO_GO_VS_PLAN"), "To-Go $", CURRENCY),
            column("PCT_PLAN_ACHIEVED", sql_col("PCT_PLAN_ACHIEVED"), "% Achieved", PERCENT),
        ],
        sort=[{"columnId": "METRIC_SORT", "direction": "ascending", "nulls": "last"}],
        conditional_formats=[
            {"type": "single", "columnIds": ["PCT_PLAN_ACHIEVED"], "condition": "<",
             "value": 1, "style": {"color": RED}, "includeValues": True},
            {"type": "single", "columnIds": ["PCT_PLAN_ACHIEVED"], "condition": ">=",
             "value": 1, "style": {"color": GREEN}, "includeValues": True},
        ],
    )


def _channel_element() -> dict:
    """PORTED FROM sql/el_channel_dtc.sql — the CHANNEL ordering CASE."""
    return table(
        "tbl_channel_dtc",
        "Retail + total DTC",
        warehouse(CHANNEL_FD),
        [
            column("BRAND_LABEL", col(CHANNEL_FD, "BRAND_LABEL"), "Brand", hidden=True),
            column("REPORT_DATE", col(CHANNEL_FD, "REPORT_DATE"), "Report date", DATE, hidden=True),
            column("CHANNEL_ORDER",
                   switch(col(CHANNEL_FD, "CHANNEL"),
                          {"Ecom (website)": "1",
                           "Retail (POS / boutiques)": "2",
                           "Total DTC": "3"}, "99"),
                   "Order", hidden=True),
            column("CHANNEL", col(CHANNEL_FD, "CHANNEL"), "Channel"),
            column("Y_DEMAND", col(CHANNEL_FD, "Y_DEMAND"), "Yesterday demand", CURRENCY),
            column("Y_ORDERS", col(CHANNEL_FD, "Y_ORDERS"), "Yday orders", INTEGER),
            column("MTD_DEMAND", col(CHANNEL_FD, "MTD_DEMAND"), "MTD demand", CURRENCY),
        ],
        sort=[{"columnId": "CHANNEL_ORDER", "direction": "ascending", "nulls": "last"}],
    )


def _top_sold_element() -> dict:
    """PORTED FROM sql/el_top_sold.sql, with the product thumbnail added."""
    return table(
        "tbl_top_sold",
        "Top 10 sold",
        sql(sources.TOP_SOLD),
        [
            column("BRAND_LABEL", sql_col("BRAND_LABEL"), "Brand", hidden=True),
            column("REPORT_DATE", sql_col("REPORT_DATE"), "Report date", DATE, hidden=True),
            column("RANK_IN_DAY", sql_col("RANK_IN_DAY"), "#", INTEGER),
            column("IMAGE_URL", sql_col("IMAGE_URL"), " ", image=THUMBNAIL),
            column("STYLE_COLOR", sql_col("STYLE_COLOR"), "Style / colour"),
            column("UNITS", sql_col("UNITS"), "Units", INTEGER),
            column("DEMAND_AMT", sql_col("DEMAND_AMT"), "Demand $", CURRENCY),
        ],
        sort=[{"columnId": "RANK_IN_DAY", "direction": "ascending", "nulls": "last"}],
    )


def _top_returned_element() -> dict:
    """PORTED FROM sql/el_top_returned.sql. Shopify refunds only — not the Loop
    return rate, which is not in Snowflake."""
    return table(
        "tbl_top_returned",
        "Top 10 returned",
        sql(sources.TOP_RETURNED),
        [
            column("BRAND_LABEL", sql_col("BRAND_LABEL"), "Brand", hidden=True),
            column("REPORT_DATE", sql_col("REPORT_DATE"), "Report date", DATE, hidden=True),
            column("RANK_IN_DAY", sql_col("RANK_IN_DAY"), "#", INTEGER),
            column("IMAGE_URL", sql_col("IMAGE_URL"), " ", image=THUMBNAIL),
            column("STYLE_COLOR", sql_col("STYLE_COLOR"), "Style / colour"),
            column("UNITS", sql_col("UNITS"), "Units", INTEGER),
        ],
        sort=[{"columnId": "RANK_IN_DAY", "direction": "ascending", "nulls": "last"}],
    )


def _store_element(index: int, store: str, label: str) -> dict:
    """One column of the email's "Top 5 MTD retail styles" block."""
    return table(
        f"tbl_store_{index}",
        label,
        sql(sources.retail_styles(store)),
        [
            column("REPORT_DATE", sql_col("REPORT_DATE"), "Report date", DATE, hidden=True),
            column("RANK_IN_MONTH", sql_col("RANK_IN_MONTH"), "#", INTEGER, hidden=True),
            column("IMAGE_URL", sql_col("IMAGE_URL"), " ", image=THUMBNAIL),
            column("STYLE_COLOR", sql_col("STYLE_COLOR"), "Style / colour"),
            column("UNITS", sql_col("UNITS"), "Units", INTEGER),
            column("AMT", sql_col("AMT"), "$", CURRENCY),
        ],
        sort=[{"columnId": "RANK_IN_MONTH", "direction": "ascending", "nulls": "last"}],
        banding=False,
    )


# --------------------------------------------------------------------------
# Controls
# --------------------------------------------------------------------------

def _controls(brand: Brand, element_ids: set[str]) -> list[dict]:
    """Brand and Report date.

    The Brand control defaults to this workbook's brand. The banner around it is
    fixed, so switching it changes the numbers but not the theme; a scheduled
    export per brand pins it anyway.

    The per-store retail elements are already scoped to one boutique and carry
    no BRAND_LABEL, so only the date control touches them.
    """
    filterable = sorted(
        eid for eid in element_ids if eid.startswith(("tbl_", "kpi_"))
    )

    brand_targets = [
        (eid, "BRAND_LABEL") for eid in filterable
        if not eid.startswith("tbl_store_")
    ]
    date_targets = [
        (eid, "PROMO_DATE" if eid == "tbl_promo" else "REPORT_DATE")
        for eid in filterable
    ]

    def filters(targets: list[tuple[str, str]]) -> list[dict]:
        return [
            {"source": {"kind": "table", "elementId": eid}, "columnId": cid}
            for eid, cid in targets
        ]

    return [
        {
            "kind": "control", "controlId": "Brand", "id": "ctrl_brand",
            "name": "Brand", "controlType": "list", "mode": "include",
            "selectionMode": "single", "value": brand.label,
            "filters": filters(brand_targets),
            "source": {
                "kind": "source",
                "source": {"kind": "table", "elementId": "tbl_performance"},
                "columnId": "BRAND_LABEL",
            },
        },
        {
            "kind": "control", "controlId": "ReportDate", "id": "ctrl_dates",
            "name": "Report date", "controlType": "date-range",
            "mode": "between", "includeNulls": "always",
            "filters": filters(date_targets),
        },
    ]


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------

PAGE = "page_mail"


def _report_elements(brand: Brand) -> list[tuple[dict, int, int, int]]:
    """Elements in email order, each with (grid column start, end, row span).
    A run of entries that do not start at column 1 shares a row."""
    rows: list[tuple[dict, int, int, int]] = []

    def add(element: dict, start: int = 1, end: int = 25, span: int = 1) -> None:
        rows.append((element, start, end, span))

    if brand.has_shopify_retail:
        # No <b> — the inline set is <u> <sub> <sup> <span> <a> only.
        add(text("txt_retail_added",
                 "Retail boutiques are shown separately below and are NOT "
                 "included in the ecom figures.", BODY, 13))
        retail_amt, retail_orders = _retail_added_cards()
        add(retail_amt, 1, 13, 3)
        add(retail_orders, 13, 25, 3)

    add(heading("txt_glance_heading", "At a glance — ecom (plan-tracked)"))
    for index, card in enumerate(_kpi_cards()):
        add(card, 1 + index * 6, 7 + index * 6, 3)

    add(heading("txt_promo_heading", "Promo &amp; email"))
    add(_promo_element(), 1, 13, 4)
    promo_amt, promo_orders = _promo_cards()
    add(promo_amt, 13, 19, 4)
    add(promo_orders, 19, 25, 4)

    add(heading("txt_perf_heading", "Performance detail — ecom only"))
    add(_performance_element(), 1, 25, 12)
    add(text("txt_kpi_note",
             "KPI additions in progress: Margin $/%, Media Spend, CAC/CPO, "
             "Traffic, CVR, Net $ — those rows are present but blank on purpose.",
             FAINT, 12))

    if brand.has_shopify_retail:
        add(heading("txt_channel_heading", "Retail + total DTC"))
        add(_channel_element(), 1, 25, 5)
        add(text("txt_channel_note",
                 "Retail = Shopify orders tied to a physical location "
                 "(Madison Ave / Nashville / Beverly Hills).", FAINT, 12))
        add(heading("txt_stores_heading", "Top 5 MTD retail styles"))
        width = 24 // max(len(brand.stores), 1)
        for index, (store, label) in enumerate(brand.stores):
            start = 1 + index * width
            end = start + width if index < len(brand.stores) - 1 else 25
            add(_store_element(index, store, label), start, end, 8)
    elif brand.retail_note:
        add(heading("txt_channel_heading", "Retail (DTC)"))
        add(text("txt_retail_note", brand.retail_note, BODY, 13))

    add(heading("txt_top_heading", "Top 10 — style / colour / units (yesterday ecom)"))
    add(_top_sold_element(), 1, 13, 12)
    add(_top_returned_element(), 13, 25, 12)

    add(text("txt_footer",
             "Daily send (no weekend rollups). LY = same weekday (−364). Promo "
             "copy from the Marketing Calendar; promo purchase $ = Shopify "
             "TOTALDISCOUNT on in-scope orders. Top 10 returned is Shopify "
             "refunds only — not the Loop return rate, which is not yet in "
             "Snowflake.", FAINT, 12), 1, 25, 2)

    return rows


def _elements(brand: Brand) -> tuple[list[dict], list[tuple[dict, int, int, int]]]:
    report = _report_elements(brand)
    element_ids = {element["id"] for element, *_ in report}

    banner = [
        {"id": "ctr_banner", "kind": "container",
         "style": {"backgroundColor": brand.accent}},
        text("txt_title", brand.display_name, ON_ACCENT, 28),
        text("txt_kicker", "DAILY ECOM RECAP", ON_ACCENT, 11),
        text("txt_scope", brand.scope_line, ON_ACCENT, 13),
    ]
    controls = _controls(brand, element_ids)
    return banner + controls + [element for element, *_ in report], report


def _layout(report: list[tuple[dict, int, int, int]]) -> str:
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        f'<Page type="grid" gridTemplateColumns="repeat(24, 1fr)" '
        f'gridTemplateRows="auto" id="{PAGE}">',
        '  <Container elementId="ctr_banner" type="grid" gridColumn="1 / 25" '
        'gridRow="1 / 5" gridTemplateColumns="repeat(24, 1fr)" gridTemplateRows="auto">',
        '    <Element elementId="txt_title" gridColumn="1 / 25" gridRow="1 / 2"/>',
        '    <Element elementId="txt_kicker" gridColumn="1 / 25" gridRow="2 / 3"/>',
        '    <Element elementId="txt_scope" gridColumn="1 / 25" gridRow="3 / 5"/>',
        "  </Container>",
        '  <Element elementId="ctrl_brand" gridColumn="1 / 7" gridRow="5 / 6"/>',
        '  <Element elementId="ctrl_dates" gridColumn="7 / 16" gridRow="5 / 6"/>',
    ]

    row = 6
    index = 0
    while index < len(report):
        run = [report[index]]
        index += 1
        while index < len(report) and report[index][1] != 1:
            run.append(report[index])
            index += 1
        span = max(entry[3] for entry in run)
        for element, start, end, _ in run:
            lines.append(
                f'  <Element elementId="{element["id"]}" gridColumn="{start} / {end}" '
                f'gridRow="{row} / {row + span}"/>'
            )
        row += span

    lines.append("</Page>")
    return "\n".join(lines) + "\n"


def workbook_name(brand: Brand) -> str:
    return f"Daily Ecom Mail — {brand.display_name}"


def spec_path(brand: Brand) -> Path:
    return SPEC_DIR / f"workbook_{brand.brand_id}.json"


def build_spec(brand: Brand) -> dict:
    elements, report = _elements(brand)
    retail = (
        ", retail + DTC and top 5 MTD retail styles by boutique"
        if brand.has_shopify_retail else ""
    )
    return {
        "name": workbook_name(brand),
        "description": (
            f"Daily ecom recap for {brand.display_name}, mirroring the recap "
            f"email: plan-tracked KPI cards, promo block, performance grid"
            f"{retail}, and top 10 sold/returned with product images."
        ),
        "document": {
            "schemaVersion": 1,
            "kind": "workbook",
            "elements": elements,
            "pages": [{"id": PAGE, "name": "Daily Ecom Mail", "pageWidth": "full"}],
            "layout": _layout(report),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brand", help="build one brand (Hudson / FD / Joe's)")
    parser.add_argument("--stdout", action="store_true",
                        help="print the spec instead of writing it")
    args = parser.parse_args()

    targets = [brand_config.get(args.brand)] if args.brand else list(brand_config.BRANDS)

    for brand in targets:
        spec = build_spec(brand)
        rendered = json.dumps(spec, indent=2, ensure_ascii=False) + "\n"
        if args.stdout:
            print(rendered, end="")
            continue
        path = spec_path(brand)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered)
        elements = spec["document"]["elements"]
        by_kind: dict[str, int] = {}
        for element in elements:
            by_kind[element["kind"]] = by_kind.get(element["kind"], 0) + 1
        summary = ", ".join(f"{n} {k}" for k, n in sorted(by_kind.items()))
        print(f"wrote {path.relative_to(REPO_ROOT)} ({len(elements)} elements: {summary})")


if __name__ == "__main__":
    main()
