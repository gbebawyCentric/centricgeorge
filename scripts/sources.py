"""Inline-SQL sources for the parts of the recap that column formulas cannot do.

Most of the workbook reads a warehouse table and computes in Sigma column
formulas — see build_spec.py. Three things need real SQL, because each either
generates rows or spans tables:

* the performance grid's Demand Plan row, which is a UNION;
* the promo purchase totals, a ROW_NUMBER() de-duplication of raw Shopify
  joined to the in-scope order list and aggregated;
* the top-10 and retail-styles product images, joined through Shopify's product
  table — and the retail styles themselves, which are aggregated per store.

Each statement is the same logic as the matching file in sql/, minus its
:brand_label / :report_date parameters: every statement keeps BRAND_LABEL and
REPORT_DATE as output columns so the workbook controls do that filtering.

Note the quoted identifiers on SHOPIFY_PRODUCT_ADF ("productId",
"featuredImageUrl", …). That table is stored camel-case, so unquoted references
fail with `invalid identifier`.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# Shared fragments
# --------------------------------------------------------------------------

# Latest Shopify product row per product id, for the featured image. Products
# are re-loaded per pipeline run, so take the most recent row that has an image.
_PRODUCT_IMAGE_BY_ID = """\
    SELECT "productId" AS PRODUCT_ID,
           MAX_BY("featuredImageUrl", "loadTimestamp") AS IMAGE_URL
    FROM SHOPIFY_APP.DEV_BRONZE.SHOPIFY_PRODUCT_ADF
    WHERE "featuredImageUrl" IS NOT NULL
    GROUP BY 1"""

# TB_SIGMA_DAILY_TOP_STYLES carries no product id, so the image is matched on
# the product title instead. That resolves an image for all 870 rows today.
_PRODUCT_IMAGE_BY_TITLE = """\
    SELECT UPPER(TRIM("title")) AS PRODUCT_TITLE,
           MAX_BY("featuredImageUrl", "loadTimestamp") AS IMAGE_URL
    FROM SHOPIFY_APP.DEV_BRONZE.SHOPIFY_PRODUCT_ADF
    WHERE "featuredImageUrl" IS NOT NULL
    GROUP BY 1"""

# One row per retail order with the boutique it was rung up in.
_RETAIL_ORDERS = """\
    SELECT r.ORDER_ID, r.DT_PT, l.RETAILLOCATIONNAME AS STORE
    FROM SANDBOX.SBX_RRAJASEKAR.VW_SIGMA_ORDERS_RETAIL r
    JOIN (
        SELECT ID, RETAILLOCATIONNAME,
               ROW_NUMBER() OVER (PARTITION BY ID ORDER BY CREATEDAT DESC) AS rn
        FROM SHOPIFY_APP.DEV_BRONZE.SHOPIFY_ORDERS_ADF
        WHERE RETAILLOCATIONNAME IS NOT NULL
    ) l ON l.ID = r.ORDER_ID AND l.rn = 1"""

# Order line items, de-duplicated to the latest load per line.
_ORDER_ITEMS = """\
    SELECT ORDERID, PRODUCTID, PRODUCTTITLE, VARIANTTITLE, QUANTITY,
           COALESCE(DISCOUNTEDUNITPRICE, VARIANTPRICE, 0) * QUANTITY AS AMT,
           ROW_NUMBER() OVER (PARTITION BY LINEITEMID
                              ORDER BY LOADTIMESTAMP DESC) AS rn
    FROM SHOPIFY_APP.DEV_BRONZE.SHOPIFY_ORDER_ITEMS_ADF"""


# --------------------------------------------------------------------------
# Statements
# --------------------------------------------------------------------------

# PORTED FROM sql/el_performance_grid.sql.
# TB_SIGMA_QA_KPI_LONG_BRAND has no Demand Plan metric but the email's grid has
# that row, so it is unioned in from the glance table's plan columns at
# METRIC_SORT 1.5 — between Demand Sales (1) and Orders (2), where the email
# reads it. A column formula adds a column and never a row, which is why this
# one is SQL.
PERFORMANCE = """\
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

# PORTED FROM sql/el_promo.sql — the redeemed-discount half.
# Shopify keeps one row per pipeline load, so de-duplicate to the latest row per
# order id, then join the in-scope order list to it. Taking the figure this way
# rather than aggregating Shopify directly means it inherits exactly the same
# scope filter as the demand numbers and cannot drift from them.
PROMO_TOTALS = """\
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

# PORTED FROM sql/el_top_sold.sql, plus the product thumbnail the email shows
# beside each row. STYLE_COLOR is the same `STYLE || ' — ' || COLOR` label.
TOP_SOLD = f"""\
WITH img AS (
{_PRODUCT_IMAGE_BY_TITLE}
)
SELECT t.BRAND_LABEL,
       t.REPORT_DATE,
       t.RANK_IN_DAY,
       t.STYLE || ' — ' || t.COLOR AS STYLE_COLOR,
       t.QTY                       AS UNITS,
       t.DEMAND_AMT,
       img.IMAGE_URL
FROM SANDBOX.SBX_RRAJASEKAR.TB_SIGMA_DAILY_TOP_STYLES t
LEFT JOIN img ON img.PRODUCT_TITLE = UPPER(TRIM(t.STYLE))
WHERE t.RANK_IN_DAY <= 10
"""

# PORTED FROM sql/el_top_returned.sql. Shopify refunds only — not the Loop
# return rate, which is not in Snowflake.
TOP_RETURNED = f"""\
WITH img AS (
{_PRODUCT_IMAGE_BY_TITLE}
)
SELECT r.BRAND_LABEL,
       r.REPORT_DATE,
       r.RANK_IN_DAY,
       r.STYLE || ' — ' || r.COLOR AS STYLE_COLOR,
       r.QTY                       AS UNITS,
       img.IMAGE_URL
FROM SANDBOX.SBX_RRAJASEKAR.TB_SIGMA_TOP_RETURNS r
LEFT JOIN img ON img.PRODUCT_TITLE = UPPER(TRIM(r.STYLE))
WHERE r.RANK_IN_DAY <= 10
"""

# The "Retail boutiques added $X / N orders yesterday" line above the KPI cards.
RETAIL_ADDED = """\
SELECT c.BRAND_LABEL,
       p.DT_PT AS REPORT_DATE,
       p.DEMAND_AMT,
       p.ORDERS,
       p.UNITS
FROM SANDBOX.SBX_RRAJASEKAR.TB_SIGMA_RETAIL_DAILY_PULSE p
JOIN SANDBOX.SBX_RRAJASEKAR.ECOM_SIGMA_BRAND_CONFIG c
  ON c.BRAND_ID = p.BRAND_ID
"""


def retail_styles(store: str) -> str:
    """"Top 5 MTD retail styles" for one boutique.

    There is no pre-built table for this section — it is aggregated here from
    retail orders, their line items and the product image.

    MTD is as-of the report date, not whole-month, so the element answers the
    same question on any day the control is set to: every order in the same
    month up to and including that date. Ranking is units then dollars, which
    is what breaks the email's ties the way the email breaks them.

    Colour is the variant title's first segment: VARIANTTITLE reads
    "navy / one size", and the email prints just "navy", which also collapses
    sizes of the same colourway into one row.
    """
    escaped = store.replace("'", "''")
    return f"""\
WITH ord AS (
{_RETAIL_ORDERS}
    WHERE l.RETAILLOCATIONNAME = '{escaped}'
),
items AS (
{_ORDER_ITEMS}
),
img AS (
{_PRODUCT_IMAGE_BY_ID}
),
dates AS (
    SELECT DISTINCT DT_PT AS REPORT_DATE FROM ord
),
agg AS (
    SELECT d.REPORT_DATE,
           i.PRODUCTTITLE,
           SPLIT_PART(i.VARIANTTITLE, ' / ', 1) AS COLOR,
           MAX(g.IMAGE_URL)                     AS IMAGE_URL,
           SUM(i.QUANTITY)                      AS UNITS,
           SUM(i.AMT)                           AS AMT
    FROM dates d
    JOIN ord o
      ON DATE_TRUNC('month', o.DT_PT) = DATE_TRUNC('month', d.REPORT_DATE)
     AND o.DT_PT <= d.REPORT_DATE
    JOIN items i ON i.ORDERID = o.ORDER_ID AND i.rn = 1
    LEFT JOIN img g ON g.PRODUCT_ID = i.PRODUCTID
    GROUP BY 1, 2, 3
)
SELECT REPORT_DATE,
       PRODUCTTITLE || ' — ' || COLOR AS STYLE_COLOR,
       IMAGE_URL,
       UNITS,
       AMT,
       ROW_NUMBER() OVER (PARTITION BY REPORT_DATE
                          ORDER BY UNITS DESC, AMT DESC) AS RANK_IN_MONTH
FROM agg
QUALIFY RANK_IN_MONTH <= 5
"""
