-- Email block: "Performance detail - ecom only".
-- Grain: one row per KPI, in the email's row order:
--   Demand Sales, Demand Plan, Orders, Units, UPT, AOV, AUR.
--
-- Two shape corrections against TB_SIGMA_QA_KPI_LONG_BRAND:
--   * It has no "Demand Plan" row, so that row is assembled from the daily plan
--     table (yesterday plan, MTD plan, full-month plan) the way the email prints
--     it - LY columns intentionally blank.
--   * It carries seven metrics that are not in Snowflake yet (Media Spend,
--     CAC/CPO, Traffic, CVR, Net Sales, Margin $, Margin %) and would render as
--     seven empty rows. They are excluded here; the email covers them in the
--     "KPI additions in progress" footnote instead.
WITH d AS (
  SELECT MAX(REPORT_DATE) AS REPORT_DATE
  FROM SANDBOX.SBX_RRAJASEKAR.TB_SIGMA_QA_KPI_LONG_BRAND
  WHERE BRAND_ID = '{{BRAND_ID}}'
),
g AS (
  SELECT g.*
  FROM SANDBOX.SBX_RRAJASEKAR.TB_SIGMA_QA_GLANCE_BRAND g
  JOIN d ON g.REPORT_DATE = d.REPORT_DATE
  WHERE g.BRAND_ID = '{{BRAND_ID}}'
),
mtd_plan AS (
  SELECT COALESCE(SUM(p.DEMAND_PLAN_AMT), 0) AS MTD_DEMAND_PLAN
  FROM SANDBOX.SBX_RRAJASEKAR.ECOM_DAILY_SALES_PLAN p
  CROSS JOIN d
  WHERE p.BRAND_ID = '{{BRAND_ID}}'
    AND p.PLAN_DATE BETWEEN DATE_TRUNC('month', d.REPORT_DATE) AND d.REPORT_DATE
),
base AS (
  SELECT
    k.METRIC_SORT::number(9, 1)      AS METRIC_SORT,
    k.METRIC                         AS METRIC,
    k.YESTERDAY::number(38, 8)       AS YESTERDAY,
    k.SAME_DAY_LY::number(38, 8)     AS SAME_DAY_LY,
    k.MTD::number(38, 8)             AS MTD,
    k.LY_MTD::number(38, 8)          AS LY_MTD,
    k.TOTAL_MONTH_PLAN::number(38, 2) AS TOTAL_MONTH_PLAN,
    k.TO_GO_VS_PLAN::number(38, 2)   AS TO_GO_VS_PLAN,
    k.PCT_PLAN_ACHIEVED::number(38, 8) AS PCT_PLAN_ACHIEVED,
    k.REPORT_DATE
  FROM SANDBOX.SBX_RRAJASEKAR.TB_SIGMA_QA_KPI_LONG_BRAND k
  JOIN d ON k.REPORT_DATE = d.REPORT_DATE
  WHERE k.BRAND_ID = '{{BRAND_ID}}'
    AND k.METRIC_SORT <= 6
),
plan_row AS (
  SELECT
    1.5::number(9, 1)                       AS METRIC_SORT,
    'Demand Plan'                           AS METRIC,
    g.Y_DEMAND_PLAN::number(38, 8)          AS YESTERDAY,
    NULL::number(38, 8)                     AS SAME_DAY_LY,
    mp.MTD_DEMAND_PLAN::number(38, 8)       AS MTD,
    NULL::number(38, 8)                     AS LY_MTD,
    g.TOTAL_MONTH_PLAN::number(38, 2)       AS TOTAL_MONTH_PLAN,
    NULL::number(38, 2)                     AS TO_GO_VS_PLAN,
    NULL::number(38, 8)                     AS PCT_PLAN_ACHIEVED,
    g.REPORT_DATE
  FROM g
  CROSS JOIN mtd_plan mp
)
SELECT * FROM base
UNION ALL
SELECT * FROM plan_row
ORDER BY METRIC_SORT
