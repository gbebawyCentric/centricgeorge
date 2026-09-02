-- Element: tbl_performance  ("Performance detail — ecom only")
-- Reproduces the main metric grid in the daily ecom recap email.
--
-- Rows, in email order: Demand Sales, Demand Plan, Orders, Units, UPT, AOV, AUR.
-- Columns:              Yesterday | Same Day LY | MTD | LY MTD | Month Plan | To-Go $ | % Achieved
--
-- :brand_label and :report_date are bound from the workbook controls
-- (ctl_brand / ctl_report_date). Blank plan cells render as the "—" seen in the email.

WITH params AS (
    SELECT :brand_label::TEXT AS brand_label,
           :report_date::DATE AS report_date
),

-- Plan figures live on the glance table, one row per brand + day.
glance AS (
    SELECT g.Y_DEMAND_PLAN,
           g.TOTAL_MONTH_PLAN,
           g.TO_GO_VS_PLAN,
           g.PCT_PLAN_ACHIEVED
    FROM SANDBOX.SBX_RRAJASEKAR.TB_SIGMA_QA_GLANCE_BRAND g
    JOIN params p
      ON g.BRAND_LABEL = p.brand_label
     AND g.REPORT_DATE = p.report_date
),

-- The plan-tracked KPIs already modelled long-form.
kpis AS (
    SELECT k.METRIC,
           CASE k.METRIC
                WHEN 'Demand Sales' THEN 1
                WHEN 'Orders'       THEN 3
                WHEN 'Units'        THEN 4
                WHEN 'UPT'          THEN 5
                WHEN 'AOV'          THEN 6
                WHEN 'AUR'          THEN 7
           END AS sort_order,
           k.YESTERDAY,
           k.SAME_DAY_LY,
           k.MTD,
           k.LY_MTD,
           k.TOTAL_MONTH_PLAN,
           k.TO_GO_VS_PLAN,
           k.PCT_PLAN_ACHIEVED
    FROM SANDBOX.SBX_RRAJASEKAR.TB_SIGMA_QA_KPI_LONG_BRAND k
    JOIN params p
      ON k.BRAND_LABEL = p.brand_label
     AND k.REPORT_DATE = p.report_date
    WHERE k.METRIC IN ('Demand Sales', 'Orders', 'Units', 'UPT', 'AOV', 'AUR')
),

-- The email carries a Demand Plan row that has no counterpart in the long KPI
-- table; it is assembled from the glance plan columns instead.
demand_plan AS (
    SELECT 'Demand Plan'      AS METRIC,
           2                  AS sort_order,
           g.Y_DEMAND_PLAN    AS YESTERDAY,
           NULL               AS SAME_DAY_LY,
           NULL               AS MTD,
           NULL               AS LY_MTD,
           g.TOTAL_MONTH_PLAN AS TOTAL_MONTH_PLAN,
           g.TO_GO_VS_PLAN    AS TO_GO_VS_PLAN,
           g.PCT_PLAN_ACHIEVED AS PCT_PLAN_ACHIEVED
    FROM glance g
)

SELECT METRIC,
       YESTERDAY,
       SAME_DAY_LY,
       MTD,
       LY_MTD,
       TOTAL_MONTH_PLAN,
       TO_GO_VS_PLAN,
       PCT_PLAN_ACHIEVED
FROM (
    SELECT * FROM kpis
    UNION ALL
    SELECT * FROM demand_plan
)
ORDER BY sort_order
