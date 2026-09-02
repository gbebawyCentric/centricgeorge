-- Email block: "Retail + total DTC" (Favorite Daughter only).
-- Grain: one row per channel - Ecom (website), Retail (POS / boutiques), Total DTC.
-- Hudson and Joe's have no Shopify retail feed, so this returns no rows for them
-- and the element is hidden on those pages.
WITH d AS (
  SELECT MAX(REPORT_DATE) AS REPORT_DATE
  FROM SANDBOX.SBX_RRAJASEKAR.TB_SIGMA_CHANNEL_FD
)
SELECT
  c.BRAND_LABEL,
  c.CHANNEL,
  c.Y_DEMAND,
  c.Y_ORDERS,
  c.MTD_DEMAND,
  c.REPORT_DATE,
  CASE c.CHANNEL
    WHEN 'Ecom (website)'            THEN 1
    WHEN 'Retail (POS / boutiques)'  THEN 2
    WHEN 'Total DTC'                 THEN 3
    ELSE 4
  END AS CHANNEL_SORT
FROM SANDBOX.SBX_RRAJASEKAR.TB_SIGMA_CHANNEL_FD c
JOIN d ON c.REPORT_DATE = d.REPORT_DATE
WHERE '{{BRAND_ID}}' = 'favorite-daughter'
ORDER BY CHANNEL_SORT
