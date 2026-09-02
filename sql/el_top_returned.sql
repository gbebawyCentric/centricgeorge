-- Element: tbl_top_returned  ("Top 10 returned")
--
-- Shopify refunds only — this is not the Loop return rate, which is not yet in
-- Snowflake (see TB_SIGMA_DATA_GAPS). On days with no refunds this returns no
-- rows and the workbook element shows its "No rows for this day." empty state.

WITH params AS (
    SELECT :brand_label::TEXT AS brand_label,
           :report_date::DATE AS report_date
)

SELECT r.RANK_IN_DAY,
       r.STYLE,
       r.COLOR,
       r.STYLE || ' — ' || r.COLOR AS STYLE_COLOR,
       r.QTY                       AS UNITS
FROM SANDBOX.SBX_RRAJASEKAR.TB_SIGMA_TOP_RETURNS r
JOIN params p
  ON r.BRAND_LABEL = p.brand_label
 AND r.DT_PT       = p.report_date
WHERE r.RANK_IN_DAY <= 10
ORDER BY r.RANK_IN_DAY
