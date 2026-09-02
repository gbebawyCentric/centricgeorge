#!/usr/bin/env python3
"""Build the Daily Ecom Recap workbook spec (Sigma Workbooks as Code).

    python3 scripts/build_spec.py                    # write sigma/workbook_spec.yaml
    python3 scripts/build_spec.py --format json      # same spec as JSON
    python3 scripts/build_spec.py --print-sql hudson-jeans 01_header
    python3 scripts/build_spec.py --stdout

One page per brand, in the send order of the mails being replaced: Hudson,
Favorite Daughter, Joe's. Each page reproduces one mail top to bottom, so a
scheduled export of a single page is the email.

Why pages and not one page plus a brand control: the brand accent colour is part
of the layout (header band, table headers, section rules), and a control cannot
repaint a container. Three pages also let each brand's send go to its own
recipients on its own schedule, and let the FD-only retail blocks exist without
being conditionally hidden on the other two.

The SQL lives in sigma/sql/*.sql, one file per email block, with two
placeholders expanded here:
  {{BRAND_ID}}        -> the brand's id literal
  {{MONEY(expr)}}     -> compact money string, em dash when null
  {{PCT(expr)}}       -> signed whole percent, em dash when null
  {{PCTPLAIN(expr)}}  -> unsigned whole percent, em dash when null
Keeping the display strings in SQL is what makes the rendered page read exactly
like the mail (see the header block's comment).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SQL_DIR = REPO / "sigma" / "sql"
OUT_YAML = REPO / "sigma" / "workbook_spec.yaml"
OUT_JSON = REPO / "sigma" / "workbook_spec.json"

WORKBOOK_NAME = "Daily Ecom Recap — Email"
WORKBOOK_DESCRIPTION = (
    "Per-brand daily ecom recap, laid out to be sent as the morning email. "
    "One page per brand; each page is one send. Brand-owned website demand only "
    "(FD retail boutiques are reported separately on the FD page). "
    "Generated from code — edit sigma/sql + scripts/build_spec.py, not the canvas."
)

# Warehouse connection that already backs "Centric West - Ecom KPI QA".
CONNECTION_ID = "82dc9446-e21c-4484-987d-79b52a490e2a"
CONNECTION_NAME = "Centric Brands POC"

# Detail workbook linked from the mail footer.
QA_WORKBOOK_URL = (
    "https://app.sigmacomputing.com/centric-brands/workbook/"
    "Centric-West-Ecom-KPI-QA-6vUEJAG6qufed10qtaM140"
)

# Palette lifted from the mails so the pages match what recipients see today.
INK = "#111111"
MUTED = "#6A6A6A"
FAINT = "#888888"
RULE = "#E8E8E8"
PANEL = "#FAFAFA"
TILE_NEUTRAL_BG = "#F4F4F4"
TILE_UP_BG = "#E7F6EC"
TILE_DOWN_BG = "#FDECEA"
UP = "#0B7A3B"
DOWN = "#C62828"
NEUTRAL = "#555555"

BRANDS = [
    {
        "key": "hudson",
        "brand_id": "hudson-jeans",
        "page_name": "Hudson Jeans",
        "display_name": "Hudson Jeans",
        "accent": "#1B3A4B",
        "has_retail": False,
        # Hudson's mail spells the Nordstrom carve-out out in full; the brand
        # config table's SITE_NOTE is the shorter form.
        "site_note": "Brand-owned website sales (Nordstrom marketplace excluded)",
    },
    {
        "key": "favorite_daughter",
        "brand_id": "favorite-daughter",
        "page_name": "Favorite Daughter",
        "display_name": "Favorite Daughter",
        "accent": "#6B1D32",
        "has_retail": True,
        "site_note": "Brand-owned website (ecom) — retail boutiques shown separately below.",
    },
    {
        "key": "joes",
        "brand_id": "joes-jeans",
        "page_name": "Joe's Jeans",
        "display_name": "Joe's Jeans",
        "accent": "#111111",
        "has_retail": False,
        "site_note": "Brand-owned website sales",
        # Joe's physical retail is not on Shopify, so the mail says so instead of
        # showing a channel table.
        "retail_placeholder": (
            "Joe's physical retail is on a separate platform (not Shopify). "
            "Retail + DTC total TBD once that feed is connected."
        ),
    },
]

BLOCKS = [
    "01_header",
    "02_performance_grid",
    "03_channel_dtc",
    "04_top_sold",
    "05_top_returned",
    "06_retail_top_styles",
]

KPI_FOOTNOTE = (
    "KPI additions in progress: Margin $/%, Media Spend, CAC/CPO, Traffic, CVR, Net $."
)
TOP10_FOOTNOTE = (
    "Email shows style / color / units (and $). More detail (season, material, "
    f"color code): {QA_WORKBOOK_URL}. If images are blank in Outlook: open the "
    "message → Download pictures."
)
FOOTER = (
    "Daily send (no weekend rollups). LY = same weekday (−364). Promo from "
    "Marketing Calendar; promo purchase $ = Shopify TOTALDISCOUNT. "
    f"Detail: {QA_WORKBOOK_URL}"
)


# --------------------------------------------------------------------------
# SQL macro expansion
# --------------------------------------------------------------------------

def _money(expr: str) -> str:
    """Compact money string: $1.2m / $12.8k / $207, em dash when null.

    Sign is applied outside the dollar mark so a negative to-go reads -$1.2k
    rather than $-1.2k.
    """
    return (
        "IFF({e} IS NULL, '—', IFF({e} < 0, '-', '') || '$' || "
        "CASE "
        "WHEN ABS({e}) >= 1000000 THEN TO_VARCHAR(ROUND(ABS({e}) / 1000000.0, 1)) || 'm' "
        "WHEN ABS({e}) >= 1000 THEN TO_VARCHAR(ROUND(ABS({e}) / 1000.0, 1)) || 'k' "
        "ELSE TO_VARCHAR(ROUND(ABS({e}), 0)) "
        "END)"
    ).format(e=expr)


def _pct(expr: str) -> str:
    """Signed whole percent: +186% / -31%, em dash when null."""
    return (
        "IFF({e} IS NULL, '—', IFF({e} >= 0, '+', '-') || "
        "TO_VARCHAR(ROUND(ABS({e}) * 100, 0)) || '%')"
    ).format(e=expr)


def _pct_plain(expr: str) -> str:
    """Unsigned whole percent, for "% achieved" where a + would read oddly."""
    return (
        "IFF({e} IS NULL, '—', TO_VARCHAR(ROUND({e} * 100, 0)) || '%')"
    ).format(e=expr)


MACROS = {"MONEY": _money, "PCT": _pct, "PCTPLAIN": _pct_plain}
_MACRO_RE = re.compile(r"\{\{(MONEY|PCT|PCTPLAIN)\(((?:[^{}]|\{[^{}]*\})*)\)\}\}")


def render_sql(block: str, brand_id: str) -> str:
    raw = (SQL_DIR / f"{block}.sql").read_text()
    sql = raw.replace("{{BRAND_ID}}", brand_id)
    sql = _MACRO_RE.sub(lambda m: MACROS[m.group(1)](m.group(2).strip()), sql)
    leftover = re.findall(r"\{\{[^}]*\}\}", sql)
    if leftover:
        raise SystemExit(f"{block}.sql: unexpanded placeholder(s): {sorted(set(leftover))}")
    return sql.rstrip() + "\n"


# --------------------------------------------------------------------------
# Spec element builders
#
# Key names follow Sigma's code representation for workbooks. They are the one
# part of this repo that could not be checked against a live org from the build
# environment (the Sigma API host is blocked by egress policy here), so they are
# kept in these five builders: if the beta spec names a field differently, fix it
# once here and rebuild. See README "Verifying the spec shape".
# --------------------------------------------------------------------------

def source(sid: str, name: str, sql: str) -> dict:
    return {
        "id": sid,
        "name": name,
        "type": "sql",
        "connectionId": CONNECTION_ID,
        "sql": sql,
    }


def text_el(eid: str, content: str, layout: dict, style: dict | None = None) -> dict:
    el = {"id": eid, "type": "text", "content": content, "layout": layout}
    if style:
        el["style"] = style
    return el


def section_label(eid: str, label: str, layout: dict) -> dict:
    """The small grey all-caps rules that separate the mail's sections."""
    return text_el(
        eid,
        label.upper(),
        layout,
        {"fontSize": 12, "color": MUTED, "letterSpacing": 0.6, "textTransform": "uppercase"},
    )


def kpi_el(eid: str, sid: str, title: str, value_column: str, sub_column: str,
           layout: dict, direction_column: str | None = None) -> dict:
    """One of the four tiles. `direction_column` drives the red/green wash: the
    tile is green above plan / LY, red below, grey when the comparison is missing.
    """
    el = {
        "id": eid,
        "type": "kpi",
        "sourceId": sid,
        "title": title,
        "value": {"column": value_column},
        "subtitle": {"column": sub_column},
        "layout": layout,
        "style": {"backgroundColor": TILE_NEUTRAL_BG, "valueColor": NEUTRAL, "titleColor": MUTED},
    }
    if direction_column:
        el["conditionalFormatting"] = [
            {
                "condition": {"column": direction_column, "operator": "greaterThanOrEqual", "value": 0},
                "style": {"backgroundColor": TILE_UP_BG, "valueColor": UP},
            },
            {
                "condition": {"column": direction_column, "operator": "lessThan", "value": 0},
                "style": {"backgroundColor": TILE_DOWN_BG, "valueColor": DOWN},
            },
        ]
    return el


def table_el(eid: str, sid: str, columns: list[dict], layout: dict, accent: str,
             title: str | None = None, empty_text: str | None = None) -> dict:
    el = {
        "id": eid,
        "type": "table",
        "sourceId": sid,
        "columns": columns,
        "layout": layout,
        "style": {
            "headerBackgroundColor": accent,
            "headerTextColor": "#FFFFFF",
            "rowBorderColor": RULE,
            "firstColumnBackgroundColor": PANEL,
        },
    }
    if title:
        el["title"] = title
    if empty_text:
        # The mails print "No rows for this day." rather than an empty frame.
        el["emptyState"] = {"text": empty_text}
    return el


def col(column: str, label: str, fmt: str | None = None, align: str | None = None,
        width: int | None = None) -> dict:
    c: dict = {"column": column, "label": label}
    if fmt:
        c["format"] = fmt
    if align:
        c["align"] = align
    if width:
        c["width"] = width
    return c


# --------------------------------------------------------------------------
# Page assembly
# --------------------------------------------------------------------------

GRID = 12  # 12-column canvas, mirroring the mail's 980px table


def build_page(brand: dict) -> tuple[dict, list[dict]]:
    key = brand["key"]
    bid = brand["brand_id"]
    accent = brand["accent"]
    has_retail = brand["has_retail"]

    def sid(block: str) -> str:
        return f"src_{key}_{block}"

    sources = [
        source(sid("header"), f"{brand['page_name']} — header", render_sql("01_header", bid)),
        source(sid("perf"), f"{brand['page_name']} — performance grid",
               render_sql("02_performance_grid", bid)),
        source(sid("top_sold"), f"{brand['page_name']} — top 10 sold",
               render_sql("04_top_sold", bid)),
        source(sid("top_returned"), f"{brand['page_name']} — top 10 returned",
               render_sql("05_top_returned", bid)),
    ]
    if has_retail:
        sources += [
            source(sid("channel"), f"{brand['page_name']} — retail + total DTC",
                   render_sql("03_channel_dtc", bid)),
            source(sid("retail_top"), f"{brand['page_name']} — top 5 MTD retail styles",
                   render_sql("06_retail_top_styles", bid)),
        ]

    elements: list[dict] = []
    y = 0

    # ---- Header band -----------------------------------------------------
    header_children = [
        text_el(f"{key}_title", brand["display_name"], {"x": 0, "y": 0, "w": GRID, "h": 1},
                {"fontSize": 28, "fontWeight": 700, "color": "#FFFFFF"}),
        text_el(f"{key}_kicker", "DAILY ECOM RECAP", {"x": 0, "y": 1, "w": GRID, "h": 1},
                {"fontSize": 11, "letterSpacing": 1.4, "color": "#FFFFFF", "opacity": 0.9}),
        text_el(f"{key}_sitenote", brand["site_note"], {"x": 0, "y": 2, "w": GRID, "h": 1},
                {"fontSize": 13, "color": "#FFFFFF", "opacity": 0.95}),
        text_el(f"{key}_dates",
                f"=[{sid('header')}/HEADER_TODAY_LINE]\n=[{sid('header')}/HEADER_LY_LINE]",
                {"x": 0, "y": 3, "w": GRID, "h": 1},
                {"fontSize": 13, "color": "#FFFFFF", "opacity": 0.95}),
        text_el(f"{key}_narrative",
                f"=[{sid('header')}/NARRATIVE_YESTERDAY]\n=[{sid('header')}/NARRATIVE_MTD]",
                {"x": 0, "y": 4, "w": GRID, "h": 2},
                {"fontSize": 14, "color": "#FFFFFF", "backgroundColor": "rgba(255,255,255,0.12)",
                 "borderColor": "rgba(255,255,255,0.25)", "borderRadius": 6, "padding": 14}),
    ]
    elements.append({
        "id": f"{key}_header_band",
        "type": "container",
        "layout": {"x": 0, "y": y, "w": GRID, "h": 7},
        "style": {"backgroundColor": accent, "padding": 24},
        "elements": header_children,
    })
    y += 7

    # ---- FD-only note that retail is excluded from the ecom figures ------
    if has_retail:
        elements.append(text_el(
            f"{key}_retail_note", f"=[{sid('header')}/RETAIL_NOTE_LINE]",
            {"x": 0, "y": y, "w": GRID, "h": 1}, {"fontSize": 13, "color": NEUTRAL}))
        y += 1

    # ---- KPI tiles -------------------------------------------------------
    elements.append(section_label(f"{key}_lbl_kpis", "Ecom KPIs (plan-tracked)",
                                  {"x": 0, "y": y, "w": GRID, "h": 1}))
    y += 1
    tiles = [
        ("tile_y_plan", "Yesterday vs plan", "PCT_YEST_VS_PLAN_FMT",
         "TILE_Y_PLAN_SUB", "PCT_YEST_VS_PLAN"),
        ("tile_y_ly", "Yesterday vs LY", "PCT_YEST_VS_LY_FMT",
         "TILE_Y_LY_SUB", "PCT_YEST_VS_LY"),
        ("tile_mtd_plan", "MTD vs plan", "PCT_MTD_VS_PLAN_FMT",
         "TILE_MTD_PLAN_SUB", "PCT_MTD_VS_PLAN"),
        ("tile_mtd_ly", "MTD vs LY", "PCT_MTD_VS_LY_FMT",
         "TILE_MTD_LY_SUB", "PCT_MTD_VS_LY"),
    ]
    for i, (eid, title, value_col, sub_col, dir_col) in enumerate(tiles):
        elements.append(kpi_el(
            f"{key}_{eid}", sid("header"), title, value_col, sub_col,
            {"x": i * 3, "y": y, "w": 3, "h": 2}, direction_column=dir_col))
    y += 2

    # ---- Promo & email ---------------------------------------------------
    elements.append(section_label(f"{key}_lbl_promo", "Promo & email",
                                  {"x": 0, "y": y, "w": GRID, "h": 1}))
    y += 1
    elements.append(text_el(
        f"{key}_promo",
        f"**Promo:** =[{sid('header')}/PROMO_LINE]\n"
        f"**Email:** =[{sid('header')}/EMAIL_LINE]\n"
        f"**Promo purchase (discounts applied):** =[{sid('header')}/PROMO_PURCHASE_LINE]",
        {"x": 0, "y": y, "w": GRID, "h": 2},
        {"fontSize": 13, "color": "#333333", "backgroundColor": PANEL,
         "borderLeftColor": accent, "borderLeftWidth": 3, "padding": 10}))
    y += 2

    # ---- Performance detail ---------------------------------------------
    elements.append(section_label(f"{key}_lbl_perf", "Performance detail — ecom only",
                                  {"x": 0, "y": y, "w": GRID, "h": 1}))
    y += 1
    elements.append(table_el(
        f"{key}_perf", sid("perf"),
        [
            col("METRIC", "Metric", align="left", width=160),
            col("YESTERDAY", "Yesterday", "number:auto", "right"),
            col("SAME_DAY_LY", "Same Day LY", "number:auto", "right"),
            col("MTD", "MTD", "number:auto", "right"),
            col("LY_MTD", "LY MTD", "number:auto", "right"),
            col("TOTAL_MONTH_PLAN", "Month Plan", "currency:compact", "right"),
            col("TO_GO_VS_PLAN", "To-Go $", "currency:compact", "right"),
            col("PCT_PLAN_ACHIEVED", "% Achieved", "percent:0", "right"),
        ],
        {"x": 0, "y": y, "w": GRID, "h": 8}, accent))
    y += 8
    elements.append(text_el(f"{key}_kpi_footnote", KPI_FOOTNOTE,
                            {"x": 0, "y": y, "w": GRID, "h": 1},
                            {"fontSize": 12, "color": FAINT}))
    y += 1

    # ---- Retail + total DTC ---------------------------------------------
    if has_retail:
        elements.append(section_label(f"{key}_lbl_channel", "Retail + total DTC",
                                      {"x": 0, "y": y, "w": GRID, "h": 1}))
        y += 1
        elements.append(table_el(
            f"{key}_channel", sid("channel"),
            [
                col("CHANNEL", "Channel", align="left", width=220),
                col("Y_DEMAND", "Yesterday demand", "currency:compact", "right"),
                col("Y_ORDERS", "Yday orders", "number:0", "right"),
                col("MTD_DEMAND", "MTD demand", "currency:compact", "right"),
            ],
            {"x": 0, "y": y, "w": GRID, "h": 4}, accent))
        y += 4
        elements.append(text_el(
            f"{key}_channel_note",
            "Retail = Shopify orders tied to a physical location "
            "(Madison Ave / Nashville / Beverly Hills boutiques).",
            {"x": 0, "y": y, "w": GRID, "h": 1}, {"fontSize": 12, "color": FAINT}))
        y += 1

        elements.append(section_label(f"{key}_lbl_retail_top", "Top 5 MTD retail styles",
                                      {"x": 0, "y": y, "w": GRID, "h": 1}))
        y += 1
        # One table grouped by boutique rather than three side-by-side tables:
        # a boutique that stops reporting drops out of the grouping instead of
        # leaving a dead column, and a new one appears without a spec change.
        elements.append(table_el(
            f"{key}_retail_top", sid("retail_top"),
            [
                col("IMAGE_URL", "", "image", width=48),
                col("LOCATION_LABEL", "Boutique", align="left", width=140),
                col("STYLE_COLOR", "Style — color", align="left"),
                col("QTY", "Units", "number:0", "right"),
                col("DEMAND_AMT", "Demand $", "currency:0", "right"),
            ],
            {"x": 0, "y": y, "w": GRID, "h": 9}, accent))
        el = elements[-1]
        el["groupBy"] = [{"column": "LOCATION_LABEL"}]
        el["sort"] = [{"column": "LOCATION_LABEL", "direction": "asc"},
                      {"column": "RANK_IN_LOCATION", "direction": "asc"}]
        y += 9
    elif brand.get("retail_placeholder"):
        elements.append(section_label(f"{key}_lbl_retail", "Retail / DTC",
                                      {"x": 0, "y": y, "w": GRID, "h": 1}))
        y += 1
        elements.append(text_el(f"{key}_retail_placeholder", brand["retail_placeholder"],
                                {"x": 0, "y": y, "w": GRID, "h": 1},
                                {"fontSize": 13, "color": NEUTRAL}))
        y += 1

    # ---- Top 10 sold / returned -----------------------------------------
    elements.append(section_label(
        f"{key}_lbl_top10", "Top 10 — style / color / units (yesterday ecom)",
        {"x": 0, "y": y, "w": GRID, "h": 1}))
    y += 1
    elements.append(text_el(
        f"{key}_freshness",
        f"=[{sid('header')}/REFUND_NOTE_LINE] =[{sid('header')}/FEED_NOTE_LINE]",
        {"x": 0, "y": y, "w": GRID, "h": 1}, {"fontSize": 12, "color": FAINT}))
    y += 1
    elements.append(table_el(
        f"{key}_top_sold", sid("top_sold"),
        [
            col("RANK_IN_DAY", "#", "number:0", "right", width=32),
            col("IMAGE_URL", "", "image", width=56),
            col("STYLE_COLOR", "Style — color", align="left"),
            col("QTY", "Units", "number:0", "right"),
            col("DEMAND_AMT", "Demand $", "currency:0", "right"),
        ],
        {"x": 0, "y": y, "w": 6, "h": 12}, accent,
        title="Top 10 sold", empty_text="No rows for this day."))
    elements.append(table_el(
        f"{key}_top_returned", sid("top_returned"),
        [
            col("RANK_IN_DAY", "#", "number:0", "right", width=32),
            col("IMAGE_URL", "", "image", width=56),
            col("STYLE_COLOR", "Style — color", align="left"),
            col("QTY", "Units", "number:0", "right"),
        ],
        {"x": 6, "y": y, "w": 6, "h": 12}, accent,
        title="Top 10 returned", empty_text="No rows for this day."))
    y += 12

    elements.append(text_el(f"{key}_top10_footnote", TOP10_FOOTNOTE,
                            {"x": 0, "y": y, "w": GRID, "h": 1},
                            {"fontSize": 11, "color": FAINT}))
    y += 1

    # ---- Footer ----------------------------------------------------------
    elements.append(text_el(
        f"{key}_footer", f"{FOOTER} =[{sid('header')}/AS_OF_LINE]",
        {"x": 0, "y": y, "w": GRID, "h": 1},
        {"fontSize": 12, "color": "#8A8A8A", "borderTopColor": "#EEEEEE", "borderTopWidth": 1}))

    page = {
        "id": f"page_{key}",
        "name": brand["page_name"],
        "elements": elements,
    }
    return page, sources


# --------------------------------------------------------------------------
# Self-check
#
# Every column an element names has to exist in the query feeding it. Nothing in
# the build would otherwise complain about a tile pointing at a column that was
# never selected - it would surface as an empty tile in a sent email.
#
# The available-column set is deliberately a superset: aliases (AS X) plus every
# qualified reference (t.COL) in the rendered SQL. That is enough to catch a
# name that does not exist anywhere, without needing to parse SQL properly.
# --------------------------------------------------------------------------

_ALIAS_RE = re.compile(r"\bAS\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)
_QUALIFIED_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\.([A-Z_][A-Z0-9_]*)\b")
_TEXT_REF_RE = re.compile(r"=\[([A-Za-z0-9_]+)/([A-Za-z0-9_]+)\]")


def available_columns(sql: str) -> set[str]:
    cols = {m.group(1).upper() for m in _ALIAS_RE.finditer(sql)}
    cols |= {m.group(1).upper() for m in _QUALIFIED_RE.finditer(sql)}
    return cols


def _element_refs(el: dict) -> list[tuple[str, str, str]]:
    """(sourceId, column, where) triples an element depends on."""
    refs: list[tuple[str, str, str]] = []
    eid = el.get("id", "?")
    sid = el.get("sourceId")

    if el.get("type") == "text":
        for m in _TEXT_REF_RE.finditer(el.get("content", "")):
            refs.append((m.group(1), m.group(2), f"{eid}.content"))
    elif el.get("type") == "kpi" and sid:
        refs.append((sid, el["value"]["column"], f"{eid}.value"))
        refs.append((sid, el["subtitle"]["column"], f"{eid}.subtitle"))
        for i, rule in enumerate(el.get("conditionalFormatting", [])):
            refs.append((sid, rule["condition"]["column"], f"{eid}.conditionalFormatting[{i}]"))
    elif el.get("type") == "table" and sid:
        for c in el.get("columns", []):
            refs.append((sid, c["column"], f"{eid}.columns"))
        for c in el.get("groupBy", []):
            refs.append((sid, c["column"], f"{eid}.groupBy"))
        for c in el.get("sort", []):
            refs.append((sid, c["column"], f"{eid}.sort"))

    for child in el.get("elements", []):
        refs.extend(_element_refs(child))
    return refs


def check_spec(spec: dict) -> list[str]:
    by_id = {s["id"]: available_columns(s["sql"]) for s in spec["sources"]}
    problems: list[str] = []
    seen_ids: set[str] = set()

    for page in spec["pages"]:
        def walk(elements):
            for el in elements:
                eid = el.get("id")
                if eid in seen_ids:
                    problems.append(f"duplicate element id {eid!r}")
                seen_ids.add(eid)
                walk(el.get("elements", []))
        walk(page["elements"])

        for el in page["elements"]:
            for sid, column, where in _element_refs(el):
                if sid not in by_id:
                    problems.append(f"{where}: unknown source {sid!r}")
                elif column.upper() not in by_id[sid]:
                    problems.append(f"{where}: {sid} has no column {column!r}")
    return problems


def build_spec() -> dict:
    pages, sources = [], []
    for brand in BRANDS:
        page, page_sources = build_page(brand)
        pages.append(page)
        sources.extend(page_sources)
    return {
        "name": WORKBOOK_NAME,
        "description": WORKBOOK_DESCRIPTION,
        "schemaVersion": "1",
        "sources": sources,
        "pages": pages,
    }


# --------------------------------------------------------------------------
# Minimal YAML writer
#
# Emitting this by hand keeps the repo dependency-free (PyYAML is not installed
# everywhere this runs) and keeps the long SQL readable as block scalars.
# --------------------------------------------------------------------------

def _needs_quotes(s: str) -> bool:
    if s == "":
        return True
    if s.strip() != s:
        return True
    if s[0] in "&*!|>%@`{}[]#,?-'\"":
        return True
    if ": " in s or s.endswith(":") or " #" in s:
        return True
    if s.lower() in {"true", "false", "null", "yes", "no", "on", "off", "~"}:
        return True
    # A string that would round-trip as a number has to stay quoted, or
    # schemaVersion "1" comes back as the integer 1.
    try:
        float(s)
    except ValueError:
        return False
    return True


def _scalar(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    s = str(v)
    if "\n" in s:
        return ""  # handled by caller as a block scalar
    if _needs_quotes(s):
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def _dump(value, indent: int, out: list[str]) -> None:
    pad = "  " * indent
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(v, (dict, list)) and v:
                out.append(f"{pad}{k}:")
                _dump(v, indent + 1, out)
            elif isinstance(v, (dict, list)):
                out.append(f"{pad}{k}: {{}}" if isinstance(v, dict) else f"{pad}{k}: []")
            elif isinstance(v, str) and "\n" in v:
                # "|" keeps the single trailing newline the SQL blocks end with,
                # "|-" strips it; picking the wrong one makes the YAML and JSON
                # forms of the same spec differ.
                out.append(f"{pad}{k}: {'|' if v.endswith(chr(10)) else '|-'}")
                for line in v.rstrip("\n").split("\n"):
                    out.append(f"{pad}  {line}" if line else "")
            else:
                out.append(f"{pad}{k}: {_scalar(v)}")
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                inner: list[str] = []
                _dump(item, indent + 1, inner)
                first = inner[0].lstrip()
                out.append(f"{pad}- {first}")
                out.extend(inner[1:])
            else:
                out.append(f"{pad}- {_scalar(item)}")


def to_yaml(spec: dict) -> str:
    out = [
        "# Generated by scripts/build_spec.py — do not edit by hand.",
        f"# Connection: {CONNECTION_NAME} ({CONNECTION_ID})",
        "",
    ]
    _dump(spec, 0, out)
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--format", choices=["yaml", "json"], default="yaml")
    ap.add_argument("--stdout", action="store_true", help="print instead of writing the file")
    ap.add_argument("--print-sql", nargs=2, metavar=("BRAND_ID", "BLOCK"),
                    help="render one SQL block and exit (e.g. hudson-jeans 01_header)")
    args = ap.parse_args()

    if args.print_sql:
        brand_id, block = args.print_sql
        known = {b["brand_id"] for b in BRANDS}
        if brand_id not in known:
            ap.error(f"unknown brand id {brand_id!r}; expected one of {sorted(known)}")
        if block not in BLOCKS:
            ap.error(f"unknown block {block!r}; expected one of {BLOCKS}")
        sys.stdout.write(render_sql(block, brand_id))
        return 0

    spec = build_spec()
    problems = check_spec(spec)
    if problems:
        print(f"{len(problems)} problem(s) in the generated spec:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    if args.format == "json":
        body, path = json.dumps(spec, indent=2, ensure_ascii=False) + "\n", OUT_JSON
    else:
        body, path = to_yaml(spec), OUT_YAML

    if args.stdout:
        sys.stdout.write(body)
        return 0

    path.write_text(body)
    n_el = sum(len(p["elements"]) for p in spec["pages"])
    print(f"wrote {path.relative_to(REPO)}  "
          f"({len(spec['pages'])} pages, {n_el} top-level elements, "
          f"{len(spec['sources'])} sql sources, {len(body):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
