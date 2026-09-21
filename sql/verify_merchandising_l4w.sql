-- Reproduces the L4W bug in the Merchandising workbook. See docs/merchandising-l4w.md.
--
-- The workbook computes L4W as
--     [Reporting Date] >= [4 WEEKS AGO] and [INSIDE DATE RANGE]
-- which intersects the four-week lookback with the user's own date selection.
-- Any selection shorter than four weeks makes L4W identical to the selected
-- range. This query shows the two windows side by side for the range Rod
-- reported, 9/13-9/20.
--
-- Substitute the two dates to check another selection.

WITH params AS (
  SELECT '2026-09-13'::DATE AS range_start,
         '2026-09-20'::DATE AS range_end
),
base AS (
  SELECT
    -- [Reporting Date] in the workbook: transaction date for DEMAND rows,
    -- fulfillment date (falling back to transaction date) otherwise.
    DATE_TRUNC('day',
      CASE WHEN t.DEMAND_VS_ACTUALIZED = 'DEMAND' THEN t.TRANSACTION_DTS
           ELSE COALESCE(t.FULFILLMENT_DATE, t.TRANSACTION_DTS) END)::DATE AS reporting_date,
    t.ITEM_QTY, t.COST, t.TOTAL_DISCOUNT_AMOUNT, t.TRANSACTION_TYPE,
    t.TRANSACTION_RETAIL_PRICE, t.UNIT_PRICE
  FROM CB_ANALYTICS_PRD.VIRTUAL.AGG_SALES_TRANSACTIONS t
  -- The element's row filters. There is no date filter on the element; the
  -- date scoping happens entirely in the formulas, which is why MTD and YTD
  -- can already reach outside the selected range.
  WHERE COALESCE(t.TRANSACTION_CLASSIFICATION, '') <> 'ORIGINAL_DUPLICATE'
    AND COALESCE(t.DEPARTMENT, '') <> 'Gift-Card'
    AND COALESCE(t.ORDER_LOCATION_CODE, '') <> '101'
    AND COALESCE(t.ORDER_LOCATION_NAME, '') <> '101 Corporate Office'
    AND t.BRAND_NAME IN ('Robert Graham', 'Joes Jeans', 'Herve Leger', 'Favorite Daughter')
    AND t.DEMAND_VS_ACTUALIZED IN ('DEMAND', 'ACTUALIZED')
),
windows AS (
  SELECT 1 AS ord, 'LW  selected range' AS window_name,
         p.range_start AS win_start, p.range_end AS win_end FROM params p
  UNION ALL
  -- What the workbook computes today: the lookback clamped to the selection.
  SELECT 2, 'L4W as-is (clamped)',
         GREATEST(DATEADD('week', -4, p.range_end), p.range_start), p.range_end FROM params p
  UNION ALL
  -- With [INSIDE DATE RANGE] removed. 29 days, because >= includes both ends.
  SELECT 3, 'L4W unclamped (29d)',
         DATEADD('week', -4, p.range_end), p.range_end FROM params p
  UNION ALL
  -- ... and with the off-by-one corrected to a true 28-day window.
  SELECT 4, 'L4W unclamped (28d)',
         DATEADD('day', 1, DATEADD('week', -4, p.range_end)), p.range_end FROM params p
)
SELECT
  w.window_name,
  w.win_start,
  w.win_end,
  SUM(b.ITEM_QTY) AS sales_qty,
  ROUND(SUM(CASE WHEN b.TRANSACTION_TYPE = 'SALE'   THEN b.ITEM_QTY * b.TRANSACTION_RETAIL_PRICE
                 WHEN b.TRANSACTION_TYPE = 'RETURN' THEN b.ITEM_QTY * b.UNIT_PRICE
                 ELSE 0 END), 0) AS sales_retail,
  -- How every L4W / MTD / YTD discount column computes it.
  ROUND(SUM(b.ITEM_QTY * b.TOTAL_DISCOUNT_AMOUNT), 0) AS discount_qty_weighted,
  -- How the two summary elements compute it for LW: no [Item Qty]. The gap
  -- between these two columns is the second finding in the doc.
  ROUND(SUM(b.TOTAL_DISCOUNT_AMOUNT), 0) AS discount_unweighted,
  ROUND(SUM(CASE WHEN b.TRANSACTION_TYPE = 'SALE'   THEN b.ITEM_QTY * b.TRANSACTION_RETAIL_PRICE
                 WHEN b.TRANSACTION_TYPE = 'RETURN' THEN b.ITEM_QTY * b.UNIT_PRICE
                 ELSE 0 END)
        - SUM(b.ITEM_QTY * b.TOTAL_DISCOUNT_AMOUNT), 0) AS net_sales,
  ROUND(SUM(b.ITEM_QTY * b.COST), 0) AS cogs
FROM windows w
JOIN base b ON b.reporting_date BETWEEN w.win_start AND w.win_end
GROUP BY w.ord, w.window_name, w.win_start, w.win_end
ORDER BY w.ord;
