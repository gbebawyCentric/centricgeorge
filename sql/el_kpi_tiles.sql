-- Element: tbl_kpi_tiles  (the four coloured cards under "Ecom KPIs (plan-tracked)")
--
-- One row per tile so the four KPI elements can each bind to a single record:
--   Yesterday vs plan | Yesterday vs LY | MTD vs plan | MTD vs LY
--
-- PCT_VALUE is the big number on the card. It is NULL wherever plan data is
-- missing, which is what renders as "—" in the email.
-- TREND drives the card colour: positive -> green, negative -> red, flat -> grey.

WITH params AS (
    SELECT :brand_label::TEXT AS brand_label,
           :report_date::DATE AS report_date
),

glance AS (
    SELECT g.*
    FROM SANDBOX.SBX_RRAJASEKAR.TB_SIGMA_QA_GLANCE_BRAND g
    JOIN params p
      ON g.BRAND_LABEL = p.brand_label
     AND g.REPORT_DATE = p.report_date
),

tiles AS (
    SELECT 1 AS TILE_ORDER,
           'Yesterday vs plan'   AS TILE_LABEL,
           g.PCT_YEST_VS_PLAN    AS PCT_VALUE,
           g.YESTERDAY_DEMAND    AS PRIMARY_AMT,
           g.Y_DEMAND_PLAN       AS COMPARE_AMT
    FROM glance g
    UNION ALL
    SELECT 2,
           'Yesterday vs LY',
           g.PCT_YEST_VS_LY,
           g.YESTERDAY_DEMAND,
           g.SAME_DAY_LY_DEMAND
    FROM glance g
    UNION ALL
    SELECT 3,
           'MTD vs plan',
           g.PCT_MTD_VS_PLAN,
           g.MTD_DEMAND,
           g.TOTAL_MONTH_PLAN
    FROM glance g
    UNION ALL
    SELECT 4,
           'MTD vs LY',
           g.PCT_MTD_VS_LY,
           g.MTD_DEMAND,
           g.LY_MTD_DEMAND
    FROM glance g
)

SELECT TILE_ORDER,
       TILE_LABEL,
       PCT_VALUE,
       PRIMARY_AMT,
       COMPARE_AMT,
       CASE
           WHEN PCT_VALUE IS NULL THEN 'none'
           WHEN PCT_VALUE > 0     THEN 'up'
           WHEN PCT_VALUE < 0     THEN 'down'
           ELSE 'flat'
       END AS TREND
FROM tiles
ORDER BY TILE_ORDER
