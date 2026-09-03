"""Assemble the workbook-as-code spec for the Daily Ecom Mail workbook.

The spec shape here is the one the Sigma API actually returns, read off live
workbooks rather than guessed:

    {"name", "description", "document": {
        "schemaVersion", "kind", "elements", "pages", "layout"}}

Things about it that are easy to get wrong:

* ``elements`` is a **flat** list on the document, not nested inside pages.
  The page an element belongs to is decided by ``layout``, not by nesting.
* ``layout`` is an **XML string** — one ``<Page>`` block per page, holding
  ``<Element>`` and ``<Container>`` nodes on a 24-column grid. There is no
  per-element x/y/width/height.
* Every element must appear in the layout. To keep an element off the report,
  put it on a page marked ``visibility: "hidden"`` — that is how the KPI cards
  get a data source without a raw table showing up under them.
* A table's data comes from a ``source``: ``warehouse-table`` (a
  ``[database, schema, table]`` path), ``sql`` (an inline statement), or
  ``table`` (another element). Each column carries a Sigma ``formula``.

Presentation lives on the elements themselves: ``kpi-chart`` for the cards,
``container`` for the banner, per-column ``format`` and ``hidden``,
``conditionalFormats`` for the red/green, ``display.emptyCellDisplay`` for the
email's em dash.

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

# Connection backing every element. This is "Centric Brands POC", the connection
# the existing Centric West - Ecom KPI QA workbook uses to read these same
# SANDBOX.SBX_RRAJASEKAR tables, so it is known to resolve them.
CONNECTION_ID = "82dc9446-e21c-4484-987d-79b52a490e2a"

DATABASE = "SANDBOX"
SCHEMA = "SBX_RRAJASEKAR"

# The emails are themed per brand (Hudson #1B3A4B, Favorite Daughter #6B1D32,
# Joe's #111111). One workbook renders one theme; this is the neutral default.
ACCENT = "#1B3A4B"
ON_ACCENT = "#FFFFFF"
ON_ACCENT_MUTED = "#C7D6DE"
MUTED = "#6A6A6A"
FAINT = "#8A8A8A"
GREEN = "#0B7A3B"
RED = "#C62828"

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

# --- formats ---------------------------------------------------------------

CURRENCY = {"kind": "number", "formatString": "$,.0f", "currencySymbol": "$"}
CURRENCY_CENTS = {"kind": "number", "formatString": "$,.2f", "currencySymbol": "$"}
PERCENT = {"kind": "number", "formatString": ",.1%"}
INTEGER = {"kind": "number", "formatString": ",d"}
DECIMAL = {"kind": "number", "formatString": ",.2f"}
DATE = {"kind": "datetime", "formatString": "%m/%d/%Y"}

EM_DASH = "—"


# --------------------------------------------------------------------------
# Sigma formula helpers
# --------------------------------------------------------------------------

def col(table: str, column: str) -> str:
    """A warehouse-source column reference, e.g. [TB_SIGMA_DAILY_PULSE/QTY]."""
    return f"[{table}/{column}]"


# An inline-SQL source is always addressed under the literal qualifier
# "Custom SQL", whatever the statement selects from. A bare [COLUMN] does not
# resolve — the columns come back typed `error`.
SQL_QUALIFIER = "Custom SQL"


def sql_col(column: str) -> str:
    """A column reference into an inline-sql source, e.g. [Custom SQL/METRIC]."""
    return f"[{SQL_QUALIFIER}/{column}]"


def quote(value: str) -> str:
    """A Sigma string literal. Sigma escapes a double quote by doubling it."""
    return '"' + value.replace('"', '""') + '"'


def switch(subject: str, mapping: dict[str, str], default: str) -> str:
    """Switch(subject, k1, v1, …, default) — the port target for a SQL
    ``CASE <expr> WHEN … THEN …`` with a constant subject."""
    arms = ", ".join(f"{quote(k)}, {v}" for k, v in mapping.items())
    return f"Switch({subject}, {arms}, {default})"


def trend(pct: str) -> str:
    """PORTED FROM sql/el_kpi_tiles.sql — the CASE that colours each card.

        CASE WHEN PCT_VALUE IS NULL THEN 'none'
             WHEN PCT_VALUE > 0 THEN 'up'
             WHEN PCT_VALUE < 0 THEN 'down' ELSE 'flat' END
    """
    return (
        f'If(IsNull({pct}), "none", '
        f'If({pct} > 0, "up", If({pct} < 0, "down", "flat")))'
    )


def style_color(table: str) -> str:
    """PORTED FROM sql/el_top_sold.sql and sql/el_top_returned.sql —
    ``STYLE || ' — ' || COLOR``."""
    return f'Concat({col(table, "STYLE")}, " — ", {col(table, "COLOR")})'


# --------------------------------------------------------------------------
# Element constructors
# --------------------------------------------------------------------------

def column(
    column_id: str,
    formula: str,
    name: str,
    fmt: dict | None = None,
    hidden: bool = False,
) -> dict:
    entry: dict = {"id": column_id, "formula": formula, "name": name}
    if fmt:
        entry["format"] = fmt
    if hidden:
        # Key columns the controls filter on still have to exist; hiding them
        # keeps the report reading like the email instead of like a data dump.
        entry["hidden"] = True
    return entry


def text_element(
    element_id: str,
    body: str,
    color: str = ACCENT,
    font_size: int | None = None,
) -> dict:
    """A text element. Only <p> blocks are accepted, with a small inline set
    (<u>, <sub>, <sup>, <span>, <a>) inside, and a <span> style may only carry
    color, background-color, font-size and font-family — so a heading is a
    <span> with a font-size, not an <h1>, and there is no letter-spacing."""
    style = f"color: {color}"
    if font_size:
        style += f"; font-size: {font_size}px"
    return {
        "id": element_id,
        "kind": "text",
        "body": f'<p class="p-large"><span style="{style}">{body}</span></p>',
    }


def warehouse_source(table: str) -> dict:
    return {
        "connectionId": CONNECTION_ID,
        "kind": "warehouse-table",
        "path": [DATABASE, SCHEMA, table],
    }


def sql_source(statement: str) -> dict:
    return {"connectionId": CONNECTION_ID, "kind": "sql", "statement": statement}


def table_element(
    element_id: str,
    name: str | None,
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
        "order": [c["id"] for c in columns],
        "visibleAsSource": True,
    }
    element["name"] = name if name else {"visibility": "hidden"}
    if sort:
        element["sort"] = sort
    if conditional_formats:
        element["conditionalFormats"] = conditional_formats
    # No empty-cell override: `display` is rejected on anything but a
    # pivot-table, so a blank plan cell renders blank rather than as the
    # email's em dash.
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
    """A kpi-chart card: the value large, and the change against a comparison
    column under it — which is what the email's four coloured cards show.

    Each card reads the warehouse table directly rather than sourcing from
    another element. A cross-element formula like ``Sum([Yesterday demand])``
    does not resolve through the API (it comes back as
    ``Unknown column "[Yesterday demand]"``), whereas the ``[TABLE/COLUMN]``
    form does. Self-contained cards also mean the controls filter each one
    directly, which is why every card carries the two key columns.
    """
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
# Sources
# --------------------------------------------------------------------------

GLANCE = "TB_SIGMA_QA_GLANCE_BRAND"
KPI_LONG = "TB_SIGMA_QA_KPI_LONG_BRAND"
CHANNEL_FD = "TB_SIGMA_CHANNEL_FD"
TOP_STYLES = "TB_SIGMA_DAILY_TOP_STYLES"
TOP_RETURNS = "TB_SIGMA_TOP_RETURNS"
PROMO = "ECOM_DAILY_PROMO"

# sql/el_promo.sql, with its :brand_label / :report_date filter dropped so the
# controls do the filtering instead. This one cannot be column formulas: it is a
# ROW_NUMBER() de-duplication of raw Shopify joined to the in-scope order list
# and then aggregated, and TB_SIGMA_ORDERS_QA carries no TOTALDISCOUNT of its
# own. An inline sql source is the honest way to keep it.
PROMO_TOTALS_SQL = """\
-- Promo purchase $ — see sql/el_promo.sql for the annotated original.
-- Shopify keeps one row per pipeline load, so de-duplicate to the latest row
-- per order id, then join the in-scope order list to it so the promo figure
-- inherits exactly the same scope filter as the demand numbers.
WITH shopify_latest AS (
    SELECT s.ID,
           s.TOTALDISCOUNT,
           ROW_NUMBER() OVER (PARTITION BY s.ID ORDER BY s.CREATEDAT DESC) AS rn
    FROM SHOPIFY_APP.DEV_BRONZE.SHOPIFY_ORDERS_ADF s
)
SELECT o.BRAND_LABEL,
       o.REPORT_DATE,
       SUM(COALESCE(sl.TOTALDISCOUNT, 0))          AS PROMO_DISCOUNT_AMT,
       COUNT_IF(COALESCE(sl.TOTALDISCOUNT, 0) > 0) AS PROMO_ORDERS
FROM SANDBOX.SBX_RRAJASEKAR.TB_SIGMA_ORDERS_QA o
LEFT JOIN shopify_latest sl
       ON sl.ID = o.ORDER_ID
      AND sl.rn = 1
GROUP BY o.BRAND_LABEL, o.REPORT_DATE
"""

# sql/el_performance_grid.sql's UNION, kept as SQL because a column formula adds
# a column and never a row. METRIC_SORT 1.5 slots the Demand Plan row between
# Demand Sales (1) and Orders (2), which is the order the email reads in.
PERFORMANCE_SQL = """\
-- Performance grid — see sql/el_performance_grid.sql for the annotated
-- original. The long KPI table carries no Demand Plan metric; the email has
-- one, assembled from the glance table's plan columns and unioned in.
SELECT BRAND_LABEL, REPORT_DATE, METRIC_SORT, METRIC,
       YESTERDAY, SAME_DAY_LY, MTD, LY_MTD,
       TOTAL_MONTH_PLAN, TO_GO_VS_PLAN, PCT_PLAN_ACHIEVED
FROM SANDBOX.SBX_RRAJASEKAR.TB_SIGMA_QA_KPI_LONG_BRAND
UNION ALL
SELECT BRAND_LABEL, REPORT_DATE, 1.5 AS METRIC_SORT, 'Demand Plan' AS METRIC,
       Y_DEMAND_PLAN AS YESTERDAY, NULL AS SAME_DAY_LY, NULL AS MTD,
       NULL AS LY_MTD, TOTAL_MONTH_PLAN, TO_GO_VS_PLAN, PCT_PLAN_ACHIEVED
FROM SANDBOX.SBX_RRAJASEKAR.TB_SIGMA_QA_GLANCE_BRAND
"""


# --------------------------------------------------------------------------
# Data elements (hidden page)
# --------------------------------------------------------------------------

def _glance_element() -> dict:
    """PORTED FROM sql/el_header.sql and sql/el_kpi_tiles.sql.

    Backs the four KPI cards, so it lives on the hidden Data page. Column names
    are kept plain because the cards reference them by name.

    The KPI tiles were a UNION ALL turning one glance row into four rows, one
    per tile. A column formula cannot generate rows — and does not need to here:
    the four values are already four columns of that row, so each card reads its
    own pair of columns.
    """
    return table_element(
        "tbl_glance",
        "Glance",
        warehouse_source(GLANCE),
        [
            column("BRAND_LABEL", col(GLANCE, "BRAND_LABEL"), "Brand"),
            column("REPORT_DATE", col(GLANCE, "REPORT_DATE"), "Report date", DATE),
            # CASE g.BRAND_ID WHEN 'hudson-jeans' THEN 'Hudson Jeans' … END
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
                DATE,
            ),
            column("Yesterday demand", col(GLANCE, "YESTERDAY_DEMAND"), "Yesterday demand", CURRENCY),
            column("Yesterday plan", col(GLANCE, "Y_DEMAND_PLAN"), "Yesterday plan", CURRENCY),
            column("Same day LY demand", col(GLANCE, "SAME_DAY_LY_DEMAND"), "Same day LY demand", CURRENCY),
            column("MTD demand", col(GLANCE, "MTD_DEMAND"), "MTD demand", CURRENCY),
            column("LY MTD demand", col(GLANCE, "LY_MTD_DEMAND"), "LY MTD demand", CURRENCY),
            column("Month plan", col(GLANCE, "TOTAL_MONTH_PLAN"), "Month plan", CURRENCY),
            column("PCT_YEST_VS_PLAN", col(GLANCE, "PCT_YEST_VS_PLAN"), "Yest vs plan", PERCENT),
            column("TREND_YEST_VS_PLAN", trend(col(GLANCE, "PCT_YEST_VS_PLAN")), "Trend — yest vs plan"),
            column("PCT_YEST_VS_LY", col(GLANCE, "PCT_YEST_VS_LY"), "Yest vs LY", PERCENT),
            column("TREND_YEST_VS_LY", trend(col(GLANCE, "PCT_YEST_VS_LY")), "Trend — yest vs LY"),
            column("PCT_MTD_VS_PLAN", col(GLANCE, "PCT_MTD_VS_PLAN"), "MTD vs plan", PERCENT),
            column("TREND_MTD_VS_PLAN", trend(col(GLANCE, "PCT_MTD_VS_PLAN")), "Trend — MTD vs plan"),
            column("PCT_MTD_VS_LY", col(GLANCE, "PCT_MTD_VS_LY"), "MTD vs LY", PERCENT),
            column("TREND_MTD_VS_LY", trend(col(GLANCE, "PCT_MTD_VS_LY")), "Trend — MTD vs LY"),
            column("To-go", col(GLANCE, "TO_GO_VS_PLAN"), "To-go", CURRENCY),
            column("Pct plan achieved", col(GLANCE, "PCT_PLAN_ACHIEVED"), "% plan achieved", PERCENT),
        ],
    )


def _promo_totals_element() -> dict:
    """Promo purchase $ and order count. Backs two cards, so it is on the
    hidden Data page. See PROMO_TOTALS_SQL for why this is not column formulas."""
    return table_element(
        "tbl_promo_totals",
        "Promo totals",
        sql_source(PROMO_TOTALS_SQL),
        [
            column("BRAND_LABEL", sql_col("BRAND_LABEL"), "Brand"),
            column("REPORT_DATE", sql_col("REPORT_DATE"), "Report date", DATE),
            column("Promo discount", sql_col("PROMO_DISCOUNT_AMT"), "Promo discount", CURRENCY),
            column("Promo orders", sql_col("PROMO_ORDERS"), "Promo orders", INTEGER),
        ],
    )


# --------------------------------------------------------------------------
# Report elements (visible page)
# --------------------------------------------------------------------------

def _performance_element() -> dict:
    """PORTED FROM sql/el_performance_grid.sql.

    Uses METRIC_SORT for ordering — the table already carries it — and keeps the
    Demand Plan row, which needs the UNION in PERFORMANCE_SQL.
    """
    return table_element(
        "tbl_performance",
        "Performance detail — ecom only",
        sql_source(PERFORMANCE_SQL),
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
            {
                "type": "single",
                "columnIds": ["PCT_PLAN_ACHIEVED"],
                "condition": "<",
                # Typed to match the column: a number here, because
                # PCT_PLAN_ACHIEVED resolves as one.
                "value": 1,
                "style": {"color": RED},
                "includeValues": True,
            },
            {
                "type": "single",
                "columnIds": ["PCT_PLAN_ACHIEVED"],
                "condition": ">=",
                "value": 1,
                "style": {"color": GREEN},
                "includeValues": True,
            },
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
        warehouse_source(CHANNEL_FD),
        [
            column("BRAND_LABEL", col(CHANNEL_FD, "BRAND_LABEL"), "Brand", hidden=True),
            column("REPORT_DATE", col(CHANNEL_FD, "REPORT_DATE"), "Report date", DATE, hidden=True),
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
                hidden=True,
            ),
            column("CHANNEL", col(CHANNEL_FD, "CHANNEL"), "Channel"),
            column("Y_DEMAND", col(CHANNEL_FD, "Y_DEMAND"), "Yesterday demand", CURRENCY),
            column("Y_ORDERS", col(CHANNEL_FD, "Y_ORDERS"), "Yday orders", INTEGER),
            column("MTD_DEMAND", col(CHANNEL_FD, "MTD_DEMAND"), "MTD demand", CURRENCY),
        ],
        sort=[{"columnId": "CHANNEL_ORDER", "direction": "ascending", "nulls": "last"}],
    )


def _top_sold_element() -> dict:
    """PORTED FROM sql/el_top_sold.sql — the STYLE_COLOR concatenation."""
    return table_element(
        "tbl_top_sold",
        "Top 10 sold",
        warehouse_source(TOP_STYLES),
        [
            column("BRAND_LABEL", col(TOP_STYLES, "BRAND_LABEL"), "Brand", hidden=True),
            column("REPORT_DATE", col(TOP_STYLES, "REPORT_DATE"), "Report date", DATE, hidden=True),
            column("RANK_IN_DAY", col(TOP_STYLES, "RANK_IN_DAY"), "#", INTEGER),
            column("STYLE_COLOR", style_color(TOP_STYLES), "Style / colour"),
            column("UNITS", col(TOP_STYLES, "QTY"), "Units", INTEGER),
            column("DEMAND_AMT", col(TOP_STYLES, "DEMAND_AMT"), "Demand $", CURRENCY),
        ],
        sort=[{"columnId": "RANK_IN_DAY", "direction": "ascending", "nulls": "last"}],
    )


def _top_returned_element() -> dict:
    """PORTED FROM sql/el_top_returned.sql. Shopify refunds only — not the Loop
    return rate, which is not in Snowflake."""
    return table_element(
        "tbl_top_returned",
        "Top 10 returned",
        warehouse_source(TOP_RETURNS),
        [
            column("BRAND_LABEL", col(TOP_RETURNS, "BRAND_LABEL"), "Brand", hidden=True),
            column("REPORT_DATE", col(TOP_RETURNS, "REPORT_DATE"), "Report date", DATE, hidden=True),
            column("RANK_IN_DAY", col(TOP_RETURNS, "RANK_IN_DAY"), "#", INTEGER),
            column("STYLE_COLOR", style_color(TOP_RETURNS), "Style / colour"),
            column("UNITS", col(TOP_RETURNS, "QTY"), "Units", INTEGER),
        ],
        sort=[{"columnId": "RANK_IN_DAY", "direction": "ascending", "nulls": "last"}],
    )


def _promo_element() -> dict:
    """PORTED FROM sql/el_promo.sql — the scheduled-copy half.

    ECOM_DAILY_PROMO is keyed by BRAND_ID while every other table is keyed by
    BRAND_LABEL, so BRAND_LABEL is derived here to bind to the same control.
    NULLIF(TRIM(COALESCE(…))) is ported to the If/Trim below.
    """
    promo_text = col(PROMO, "PROMO_TEXT")
    email_text = col(PROMO, "EMAIL_TEXT")
    return table_element(
        "tbl_promo",
        # A name of {"visibility": "hidden"} makes the element fall back to
        # showing the raw table name ("ECOM_DAILY_PROMO"), so give it a real one.
        "Scheduled promo copy",
        warehouse_source(PROMO),
        [
            column(
                "BRAND_LABEL",
                switch(
                    col(PROMO, "BRAND_ID"),
                    {k: quote(v) for k, v in BRAND_ID_TO_LABEL.items()},
                    col(PROMO, "BRAND_ID"),
                ),
                "Brand",
                hidden=True,
            ),
            column("PROMO_DATE", col(PROMO, "PROMO_DATE"), "Date", DATE, hidden=True),
            column(
                "PROMO_TEXT",
                f'If(Trim(Coalesce({promo_text}, "")) = "", '
                f'"{EM_DASH} (none on Marketing Calendar for this day)", {promo_text})',
                "Promo",
            ),
            column(
                "EMAIL_TEXT",
                f'If(Trim(Coalesce({email_text}, "")) = "", "{EM_DASH}", {email_text})',
                "Email",
            ),
        ],
        banding=False,
    )


# --------------------------------------------------------------------------
# KPI cards
# --------------------------------------------------------------------------

# The four plan-tracked cards. Each is (element id, label, value column,
# comparison column) against the glance table — the same four pairings the
# email's coloured cards show.
KPI_CARDS = [
    ("kpi_yest_vs_plan", "Yesterday vs plan", "YESTERDAY_DEMAND", "Y_DEMAND_PLAN"),
    ("kpi_yest_vs_ly", "Yesterday vs LY", "YESTERDAY_DEMAND", "SAME_DAY_LY_DEMAND"),
    ("kpi_mtd_vs_plan", "MTD vs plan", "MTD_DEMAND", "TOTAL_MONTH_PLAN"),
    ("kpi_mtd_vs_ly", "MTD vs LY", "MTD_DEMAND", "LY_MTD_DEMAND"),
]

PROMO_CARDS = [
    ("kpi_promo_amt", "Promo purchase (discounts applied)", "PROMO_DISCOUNT_AMT", CURRENCY),
    ("kpi_promo_orders", "Orders with a discount", "PROMO_ORDERS", INTEGER),
]


def _kpi_cards() -> list[dict]:
    return [
        kpi_card(
            element_id,
            label,
            warehouse_source(GLANCE),
            col(GLANCE, "BRAND_LABEL"),
            col(GLANCE, "REPORT_DATE"),
            f'Sum({col(GLANCE, value_column)})',
            f'Sum({col(GLANCE, compare_column)})',
        )
        for element_id, label, value_column, compare_column in KPI_CARDS
    ]


def _promo_cards() -> list[dict]:
    return [
        kpi_card(
            element_id,
            label,
            sql_source(PROMO_TOTALS_SQL),
            sql_col("BRAND_LABEL"),
            sql_col("REPORT_DATE"),
            f"Sum({sql_col(value_column)})",
            fmt=fmt,
        )
        for element_id, label, value_column, fmt in PROMO_CARDS
    ]


# --------------------------------------------------------------------------
# Controls
# --------------------------------------------------------------------------

BRAND_FILTER_TARGETS = [
    ("tbl_glance", "BRAND_LABEL"),
    ("tbl_promo_totals", "BRAND_LABEL"),
    ("tbl_performance", "BRAND_LABEL"),
    ("tbl_channel_dtc", "BRAND_LABEL"),
    ("tbl_top_sold", "BRAND_LABEL"),
    ("tbl_top_returned", "BRAND_LABEL"),
    ("tbl_promo", "BRAND_LABEL"),
    # Each card reads its table directly, so the controls filter it directly.
    *((element_id, "BRAND_LABEL") for element_id, *_ in KPI_CARDS),
    *((element_id, "BRAND_LABEL") for element_id, *_ in PROMO_CARDS),
]

# TB_SIGMA_DAILY_TOP_STYLES and TB_SIGMA_TOP_RETURNS carry both DT_PT and
# REPORT_DATE and the two are equal on every row, so REPORT_DATE is used
# throughout and one date control binds to every element uniformly.
DATE_FILTER_TARGETS = [
    ("tbl_glance", "REPORT_DATE"),
    ("tbl_promo_totals", "REPORT_DATE"),
    ("tbl_performance", "REPORT_DATE"),
    ("tbl_channel_dtc", "REPORT_DATE"),
    ("tbl_top_sold", "REPORT_DATE"),
    ("tbl_top_returned", "REPORT_DATE"),
    ("tbl_promo", "PROMO_DATE"),
    *((element_id, "REPORT_DATE") for element_id, *_ in KPI_CARDS),
    *((element_id, "REPORT_DATE") for element_id, *_ in PROMO_CARDS),
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


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------

PAGE_MAIL = "page_mail"
PAGE_DATA = "page_data"


def _elements() -> list[dict]:
    return [
        # --- banner, inside the accent container -------------------------
        {"id": "ctr_banner", "kind": "container", "style": {"backgroundColor": ACCENT}},
        text_element("txt_title", "DAILY ECOM RECAP", ON_ACCENT, font_size=30),
        text_element(
            "txt_scope",
            "Hudson · Favorite Daughter · Joe&#39;s — brand-owned website sales. "
            "Hudson excludes the Nordstrom marketplace; Favorite Daughter shows its "
            "retail boutiques separately below. LY = same weekday last year (&#8722;364).",
            ON_ACCENT_MUTED,
        ),
        *_controls(),
        # --- KPI cards ---------------------------------------------------
        text_element("txt_kpi_heading", "ECOM KPIs (PLAN-TRACKED)", MUTED),
        *_kpi_cards(),
        # --- promo -------------------------------------------------------
        text_element("txt_promo_heading", "PROMO &amp; EMAIL", MUTED),
        _promo_element(),
        *_promo_cards(),
        # --- performance grid --------------------------------------------
        text_element("txt_perf_heading", "PERFORMANCE DETAIL — ECOM ONLY", MUTED),
        _performance_element(),
        text_element(
            "txt_kpi_note",
            "KPI additions in progress: Margin $/%, Media Spend, CAC/CPO, Traffic, "
            "CVR, Net $ — those rows are present but blank on purpose.",
            FAINT,
        ),
        # --- FD retail / DTC ---------------------------------------------
        text_element("txt_channel_heading",
                     "RETAIL + TOTAL DTC — FAVORITE DAUGHTER ONLY", MUTED),
        _channel_element(),
        # --- top 10s -----------------------------------------------------
        text_element("txt_top_heading", "TOP 10 SOLD &amp; RETURNED", MUTED),
        _top_sold_element(),
        _top_returned_element(),
        # --- footer ------------------------------------------------------
        text_element(
            "txt_footer",
            "Daily send (no weekend rollups). Promo copy from the Marketing Calendar; "
            "promo purchase $ = Shopify TOTALDISCOUNT on in-scope orders. Top 10 "
            "returned is Shopify refunds only — not the Loop return rate, which is "
            "not yet in Snowflake.",
            FAINT,
        ),
        # --- hidden data page --------------------------------------------
        _glance_element(),
        _promo_totals_element(),
    ]


# Rows each report element occupies on the 24-column grid.
MAIN_LAYOUT: list[tuple[str, int, int, int]] = [
    # (element id, grid column start, grid column end, row span)
    ("txt_kpi_heading", 1, 25, 1),
    ("kpi_yest_vs_plan", 1, 7, 3),
    ("kpi_yest_vs_ly", 7, 13, 3),
    ("kpi_mtd_vs_plan", 13, 19, 3),
    ("kpi_mtd_vs_ly", 19, 25, 3),
    ("txt_promo_heading", 1, 25, 1),
    ("tbl_promo", 1, 13, 4),
    ("kpi_promo_amt", 13, 19, 4),
    ("kpi_promo_orders", 19, 25, 4),
    ("txt_perf_heading", 1, 25, 1),
    ("tbl_performance", 1, 25, 12),
    ("txt_kpi_note", 1, 25, 1),
    ("txt_channel_heading", 1, 25, 1),
    ("tbl_channel_dtc", 1, 25, 5),
    ("txt_top_heading", 1, 25, 1),
    ("tbl_top_sold", 1, 13, 12),
    ("tbl_top_returned", 13, 25, 12),
    ("txt_footer", 1, 25, 2),
]

DATA_LAYOUT = [("tbl_glance", 14), ("tbl_promo_totals", 8)]


def _layout() -> str:
    lines = ['<?xml version="1.0" encoding="utf-8"?>']

    # --- report page ------------------------------------------------------
    lines.append(
        f'<Page type="grid" gridTemplateColumns="repeat(24, 1fr)" '
        f'gridTemplateRows="auto" id="{PAGE_MAIL}">'
    )
    # Banner container: title and scope prose sit inside it, so they render on
    # the accent background rather than on the page.
    lines += [
        '  <Container elementId="ctr_banner" type="grid" gridColumn="1 / 25" '
        'gridRow="1 / 4" gridTemplateColumns="repeat(24, 1fr)" gridTemplateRows="auto">',
        '    <Element elementId="txt_title" gridColumn="1 / 25" gridRow="1 / 2"/>',
        '    <Element elementId="txt_scope" gridColumn="1 / 25" gridRow="2 / 4"/>',
        "  </Container>",
        '  <Element elementId="ctrl_brand" gridColumn="1 / 7" gridRow="4 / 5"/>',
        '  <Element elementId="ctrl_dates" gridColumn="7 / 16" gridRow="4 / 5"/>',
    ]

    row = 5
    # Elements sharing a row (the KPI cards, the two top-10 tables) are grouped
    # by their column start: a new row begins whenever a run returns to column 1.
    index = 0
    while index < len(MAIN_LAYOUT):
        run = [MAIN_LAYOUT[index]]
        index += 1
        while index < len(MAIN_LAYOUT) and MAIN_LAYOUT[index][1] != 1:
            run.append(MAIN_LAYOUT[index])
            index += 1
        span = max(entry[3] for entry in run)
        for element_id, start, end, _ in run:
            lines.append(
                f'  <Element elementId="{element_id}" gridColumn="{start} / {end}" '
                f'gridRow="{row} / {row + span}"/>'
            )
        row += span
    lines.append("</Page>")

    # --- hidden data page -------------------------------------------------
    lines.append(
        f'<Page type="grid" gridTemplateColumns="repeat(24, 1fr)" '
        f'gridTemplateRows="auto" id="{PAGE_DATA}">'
    )
    row = 1
    for element_id, span in DATA_LAYOUT:
        lines.append(
            f'  <Element elementId="{element_id}" gridColumn="1 / 25" '
            f'gridRow="{row} / {row + span}"/>'
        )
        row += span
    lines.append("</Page>")

    return "\n".join(lines) + "\n"


def build_spec() -> dict:
    return {
        "name": WORKBOOK_NAME,
        "description": (
            "Daily ecom recap for Hudson, Favorite Daughter and Joe's. Mirrors the "
            "daily recap email: KPI cards, promo block, performance grid, FD "
            "retail/DTC split, and top 10 sold/returned. Pick a brand and report "
            "date, then schedule one send per brand."
        ),
        "document": {
            "schemaVersion": 1,
            "kind": "workbook",
            "elements": _elements(),
            "pages": [
                {"id": PAGE_MAIL, "name": "Daily Ecom Mail", "pageWidth": "full"},
                # Source tables for the cards. Hidden so the report reads like
                # the email; every element must appear in the layout somewhere.
                {"id": PAGE_DATA, "name": "Data", "visibility": "hidden"},
            ],
            "layout": _layout(),
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
    by_kind: dict[str, int] = {}
    for element in elements:
        by_kind[element["kind"]] = by_kind.get(element["kind"], 0) + 1
    summary = ", ".join(f"{count} {kind}" for kind, count in sorted(by_kind.items()))
    print(f"wrote {SPEC_PATH.relative_to(REPO_ROOT)} ({len(elements)} elements: {summary})")


if __name__ == "__main__":
    main()
