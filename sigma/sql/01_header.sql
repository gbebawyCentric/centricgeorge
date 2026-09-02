-- Email block: brand header band + narrative paragraph + promo/email callout
--               + the four KPI tiles + the data-freshness footnotes.
-- Grain: exactly one row (brand x latest complete report date).
--
-- This block also owns the *copy*: the narrative sentences, the promo lines and
-- the compact money/percent strings ("$12.8k", "-31%") are built here rather
-- than assembled from formula chips in the workbook. Two reasons: the sentences
-- stay byte-identical to the mails they replace, and the em-dash placeholder for
-- a missing plan or promo is decided in one place instead of per element.
--
-- Report date is derived, not passed in: the send always shows the latest day
-- present in TB_SIGMA_QA_GLANCE_BRAND for the brand, which is what the email's
-- "ADF last complete day is <date> - showing that day until the pipeline
-- catches up" note describes.
WITH d AS (
  SELECT MAX(REPORT_DATE) AS REPORT_DATE
  FROM SANDBOX.SBX_RRAJASEKAR.TB_SIGMA_QA_GLANCE_BRAND
  WHERE BRAND_ID = '{{BRAND_ID}}'
),
g AS (
  SELECT g.*
  FROM SANDBOX.SBX_RRAJASEKAR.TB_SIGMA_QA_GLANCE_BRAND g
  JOIN d ON g.REPORT_DATE = d.REPORT_DATE
  WHERE g.BRAND_ID = '{{BRAND_ID}}'
),
cfg AS (
  SELECT SITE_NOTE, HAS_SHOPIFY_RETAIL
  FROM SANDBOX.SBX_RRAJASEKAR.ECOM_SIGMA_BRAND_CONFIG
  WHERE BRAND_ID = '{{BRAND_ID}}'
),
-- Month-to-date plan: summed from the daily plan rows up to the report date.
-- The month total on the glance table is the full-month plan.
mtd_plan AS (
  SELECT COALESCE(SUM(p.DEMAND_PLAN_AMT), 0) AS MTD_DEMAND_PLAN
  FROM SANDBOX.SBX_RRAJASEKAR.ECOM_DAILY_SALES_PLAN p
  CROSS JOIN d
  WHERE p.BRAND_ID = '{{BRAND_ID}}'
    AND p.PLAN_DATE BETWEEN DATE_TRUNC('month', d.REPORT_DATE) AND d.REPORT_DATE
),
promo AS (
  SELECT MAX(pr.PROMO_TEXT) AS PROMO_TEXT,
         MAX(pr.EMAIL_TEXT)  AS EMAIL_TEXT
  FROM SANDBOX.SBX_RRAJASEKAR.ECOM_DAILY_PROMO pr
  CROSS JOIN d
  WHERE pr.BRAND_ID = '{{BRAND_ID}}'
    AND pr.PROMO_DATE = d.REPORT_DATE
),
-- Latest record per Shopify order, so TOTALDISCOUNT is read off the same row
-- the demand figures come from (mirrors VW_SIGMA_LATEST_ORDERS).
orders_latest AS (
  SELECT o.ID AS ORDER_ID, o.BRANDID AS BRAND_ID, o.TOTALDISCOUNT
  FROM SHOPIFY_APP.DEV_BRONZE.SHOPIFY_ORDERS_ADF o
  WHERE o.BRANDID = '{{BRAND_ID}}'
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY o.BRANDID, o.ID
    ORDER BY o.UPDATEDAT DESC NULLS LAST, o.LOADTIMESTAMP DESC NULLS LAST
  ) = 1
),
-- "Promo purchase (discounts applied)" - discount dollars and the number of
-- discounted orders, restricted to the same in-scope ecom orders as demand.
promo_purchase AS (
  SELECT COALESCE(SUM(ol.TOTALDISCOUNT), 0)                          AS PROMO_PURCHASE_AMT,
         COUNT(DISTINCT IFF(ol.TOTALDISCOUNT > 0, f.ORDER_ID, NULL)) AS PROMO_PURCHASE_ORDERS
  FROM SANDBOX.SBX_RRAJASEKAR.VW_SIGMA_ORDERS_FILTERED f
  JOIN d ON f.DT_PT = d.REPORT_DATE
  LEFT JOIN orders_latest ol
         ON ol.ORDER_ID = f.ORDER_ID
        AND ol.BRAND_ID = f.BRAND_ID
  WHERE f.BRAND_ID = '{{BRAND_ID}}'
),
-- Drives the two data-freshness footnotes above the top-10 block: whether any
-- Shopify refunds landed for the report date, and which day the order feed is
-- actually complete through.
refunds AS (
  SELECT COUNT(*) AS REFUND_ROWS_TODAY
  FROM SANDBOX.SBX_RRAJASEKAR.TB_SIGMA_TOP_RETURNS r
  CROSS JOIN d
  WHERE r.BRAND_ID = '{{BRAND_ID}}'
    AND r.DT_PT = d.REPORT_DATE
),
feed AS (
  SELECT MAX(DT_PT) AS LAST_COMPLETE_DAY
  FROM SANDBOX.SBX_RRAJASEKAR.TB_SIGMA_DAILY_TOP_STYLES
  WHERE BRAND_ID = '{{BRAND_ID}}'
),
-- Yesterday's retail contribution, quoted in the FD note above the KPI tiles.
retail AS (
  SELECT MAX(IFF(c.CHANNEL = 'Retail (POS / boutiques)', c.Y_DEMAND, NULL)) AS RETAIL_Y_DEMAND,
         MAX(IFF(c.CHANNEL = 'Retail (POS / boutiques)', c.Y_ORDERS, NULL)) AS RETAIL_Y_ORDERS
  FROM SANDBOX.SBX_RRAJASEKAR.TB_SIGMA_CHANNEL_FD c
  CROSS JOIN d
  WHERE c.REPORT_DATE = d.REPORT_DATE
),
raw AS (
  SELECT
    g.BRAND_ID,
    g.BRAND_LABEL,
    cfg.SITE_NOTE,
    cfg.HAS_SHOPIFY_RETAIL,
    g.REPORT_DATE,
    DATEADD('day', -364, g.REPORT_DATE) AS SAME_DAY_LY_DATE,
    g.YESTERDAY_DEMAND,
    g.Y_DEMAND_PLAN,
    g.PCT_YEST_VS_PLAN,
    g.SAME_DAY_LY_DEMAND,
    g.PCT_YEST_VS_LY,
    g.MTD_DEMAND,
    mp.MTD_DEMAND_PLAN,
    g.TOTAL_MONTH_PLAN,
    g.PCT_MTD_VS_PLAN,
    g.LY_MTD_DEMAND,
    g.PCT_MTD_VS_LY,
    g.PCT_PLAN_ACHIEVED,
    g.TO_GO_VS_PLAN,
    promo.PROMO_TEXT,
    promo.EMAIL_TEXT,
    pp.PROMO_PURCHASE_AMT,
    pp.PROMO_PURCHASE_ORDERS,
    rf.REFUND_ROWS_TODAY,
    fd.LAST_COMPLETE_DAY,
    rt.RETAIL_Y_DEMAND,
    rt.RETAIL_Y_ORDERS,
    g.AS_OF_DATE
  FROM g
  CROSS JOIN cfg
  CROSS JOIN mtd_plan mp
  CROSS JOIN promo
  CROSS JOIN promo_purchase pp
  CROSS JOIN refunds rf
  CROSS JOIN feed fd
  CROSS JOIN retail rt
),
-- Display strings. Money is compact ($12.8k / $1.2m) the way the mail prints
-- it; percentages are whole numbers carrying an explicit sign; anything missing
-- becomes an em dash rather than "0" or "null".
fmt AS (
  SELECT
    r.*,
    DECODE(DAYOFWEEK(r.REPORT_DATE), 0,'Sunday',1,'Monday',2,'Tuesday',3,'Wednesday',
           4,'Thursday',5,'Friday',6,'Saturday')
      || ', ' || MONTH(r.REPORT_DATE) || '/' || DAY(r.REPORT_DATE)
      || '/' || RIGHT(YEAR(r.REPORT_DATE)::string, 2)                       AS REPORT_DATE_LABEL,
    DECODE(DAYOFWEEK(r.SAME_DAY_LY_DATE), 0,'Sunday',1,'Monday',2,'Tuesday',3,'Wednesday',
           4,'Thursday',5,'Friday',6,'Saturday')
      || ', ' || MONTH(r.SAME_DAY_LY_DATE) || '/' || DAY(r.SAME_DAY_LY_DATE)
      || '/' || RIGHT(YEAR(r.SAME_DAY_LY_DATE)::string, 2)                  AS SAME_DAY_LY_LABEL,

    {{MONEY(r.YESTERDAY_DEMAND)}}   AS YESTERDAY_DEMAND_FMT,
    {{MONEY(r.Y_DEMAND_PLAN)}}      AS Y_DEMAND_PLAN_FMT,
    {{MONEY(r.SAME_DAY_LY_DEMAND)}} AS SAME_DAY_LY_DEMAND_FMT,
    {{MONEY(r.MTD_DEMAND)}}         AS MTD_DEMAND_FMT,
    {{MONEY(r.MTD_DEMAND_PLAN)}}    AS MTD_DEMAND_PLAN_FMT,
    {{MONEY(r.TOTAL_MONTH_PLAN)}}   AS TOTAL_MONTH_PLAN_FMT,
    {{MONEY(r.LY_MTD_DEMAND)}}      AS LY_MTD_DEMAND_FMT,
    {{MONEY(r.TO_GO_VS_PLAN)}}      AS TO_GO_VS_PLAN_FMT,
    {{MONEY(r.PROMO_PURCHASE_AMT)}} AS PROMO_PURCHASE_AMT_FMT,
    {{MONEY(r.RETAIL_Y_DEMAND)}}    AS RETAIL_Y_DEMAND_FMT,

    {{PCT(r.PCT_YEST_VS_PLAN)}}     AS PCT_YEST_VS_PLAN_FMT,
    {{PCT(r.PCT_YEST_VS_LY)}}       AS PCT_YEST_VS_LY_FMT,
    {{PCT(r.PCT_MTD_VS_PLAN)}}      AS PCT_MTD_VS_PLAN_FMT,
    {{PCT(r.PCT_MTD_VS_LY)}}        AS PCT_MTD_VS_LY_FMT,
    -- Unsigned: "80%" of plan achieved, not "+80%".
    {{PCTPLAIN(r.PCT_PLAN_ACHIEVED)}} AS PCT_PLAN_ACHIEVED_FMT
  FROM raw r
)
SELECT
  f.*,

  -- Header band
  'Today = ' || f.REPORT_DATE_LABEL                                          AS HEADER_TODAY_LINE,
  'Same Day LY = ' || f.SAME_DAY_LY_LABEL || ' (same weekday)'               AS HEADER_LY_LINE,

  -- Narrative paragraph
  'Yesterday''s ecom demand was ' || f.YESTERDAY_DEMAND_FMT
    || ' vs plan ' || f.Y_DEMAND_PLAN_FMT
    || ' (' || f.PCT_YEST_VS_PLAN_FMT || ') and '
    || f.PCT_YEST_VS_LY_FMT || ' to same-day LY.'                            AS NARRATIVE_YESTERDAY,
  'MTD ecom demand is ' || f.MTD_DEMAND_FMT
    || ' vs MTD plan ' || f.MTD_DEMAND_PLAN_FMT
    || ' / month plan ' || f.TOTAL_MONTH_PLAN_FMT
    || ' (' || f.PCT_MTD_VS_PLAN_FMT || ' to MTD plan, '
    || f.PCT_MTD_VS_LY_FMT || ' to LY MTD).'                                 AS NARRATIVE_MTD,

  -- The small print under each of the four tiles, e.g.
  -- "$12.8k vs $14.3k plan" / "vs $18.5k" / "vs $49.4k LY MTD".
  f.YESTERDAY_DEMAND_FMT || ' vs ' || f.Y_DEMAND_PLAN_FMT || ' plan'          AS TILE_Y_PLAN_SUB,
  'vs ' || f.SAME_DAY_LY_DEMAND_FMT                                          AS TILE_Y_LY_SUB,
  f.MTD_DEMAND_FMT || ' vs ' || f.MTD_DEMAND_PLAN_FMT
    || ' MTD plan (month ' || f.TOTAL_MONTH_PLAN_FMT || ')'                   AS TILE_MTD_PLAN_SUB,
  'vs ' || f.LY_MTD_DEMAND_FMT || ' LY MTD'                                  AS TILE_MTD_LY_SUB,

  -- Promo & email callout
  IFF(COALESCE(TRIM(f.PROMO_TEXT), '') = '',
      '— (none on Marketing Calendar for this day)',
      f.PROMO_TEXT)                                                          AS PROMO_LINE,
  IFF(COALESCE(TRIM(f.EMAIL_TEXT), '') = '',
      '— (none on Marketing Calendar for this day)',
      f.EMAIL_TEXT)                                                          AS EMAIL_LINE,
  f.PROMO_PURCHASE_AMT_FMT || ' across ' || f.PROMO_PURCHASE_ORDERS
    || ' orders (Shopify TOTALDISCOUNT)'                                     AS PROMO_PURCHASE_LINE,

  -- FD-only note above the KPI tiles
  IFF(f.HAS_SHOPIFY_RETAIL AND f.RETAIL_Y_DEMAND IS NOT NULL,
      'Retail boutiques added ' || f.RETAIL_Y_DEMAND_FMT || ' / '
        || f.RETAIL_Y_ORDERS || ' orders yesterday — see Retail + Total DTC '
        || 'below. Not included in the ecom figures above.',
      NULL)                                                                  AS RETAIL_NOTE_LINE,

  -- Data-freshness footnotes above the top-10 block
  IFF(f.REFUND_ROWS_TODAY = 0,
      'No Shopify refunds in Snowflake for yesterday ('
        || f.REPORT_DATE::string || ' PT).',
      NULL)                                                                  AS REFUND_NOTE_LINE,
  'ADF last complete day is ' || f.LAST_COMPLETE_DAY::string
    || ' — showing that day until the pipeline catches up.'                  AS FEED_NOTE_LINE,
  'As of ' || f.AS_OF_DATE::string || ' PT.'                                 AS AS_OF_LINE
FROM fmt f
