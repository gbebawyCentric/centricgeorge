-- Element: tbl_top_sold  ("Top 10 sold" — style / colour / units / demand $)
--
-- TB_SIGMA_DAILY_TOP_STYLES is already ranked per brand per day, so this only
-- trims to the top 10 and builds the "STYLE — COLOUR" label the email prints.

WITH params AS (
    SELECT :brand_label::TEXT AS brand_label,
           :report_date::DATE AS report_date
)

SELECT t.RANK_IN_DAY,
       t.STYLE,
       t.COLOR,
       t.STYLE || ' — ' || t.COLOR AS STYLE_COLOR,
       t.QTY                       AS UNITS,
       t.DEMAND_AMT
FROM SANDBOX.SBX_RRAJASEKAR.TB_SIGMA_DAILY_TOP_STYLES t
JOIN params p
  ON t.BRAND_LABEL = p.brand_label
 AND t.DT_PT       = p.report_date
WHERE t.RANK_IN_DAY <= 10
ORDER BY t.RANK_IN_DAY
