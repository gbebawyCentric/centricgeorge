-- Element: tbl_channel_dtc  ("Retail + total DTC")
--
-- Favorite Daughter only — it is the one brand whose boutiques run on Shopify,
-- so TB_SIGMA_CHANNEL_FD holds rows for it alone. Hudson and Joe's return no
-- rows here and the element is hidden for them (Joe's shows the standing
-- "retail is on a separate platform" note instead).
--
-- Retail = Shopify orders tied to a physical location
-- (Madison Ave / Nashville / Beverly Hills).

WITH params AS (
    SELECT :brand_label::TEXT AS brand_label,
           :report_date::DATE AS report_date
)

SELECT c.CHANNEL,
       CASE c.CHANNEL
            WHEN 'Ecom (website)'            THEN 1
            WHEN 'Retail (POS / boutiques)'  THEN 2
            WHEN 'Total DTC'                 THEN 3
            ELSE 99
       END AS CHANNEL_ORDER,
       c.Y_DEMAND,
       c.Y_ORDERS,
       c.MTD_DEMAND
FROM SANDBOX.SBX_RRAJASEKAR.TB_SIGMA_CHANNEL_FD c
JOIN params p
  ON c.BRAND_LABEL = p.brand_label
 AND c.REPORT_DATE = p.report_date
ORDER BY CHANNEL_ORDER
