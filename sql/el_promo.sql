-- Element: txt_promo  ("Promo & email" block)
--
-- Two independent facts sit in this block:
--   1. PROMO_TEXT / EMAIL_TEXT — what marketing had scheduled for the day,
--      read off the Marketing Calendar load. Absent on most days, which is the
--      "— (none on Marketing Calendar for this day)" line in the email.
--   2. PROMO_DISCOUNT_AMT / PROMO_ORDERS — what customers actually redeemed,
--      i.e. Shopify TOTALDISCOUNT on in-scope orders.
--
-- The discount figure is taken by joining the in-scope order list back to raw
-- Shopify rather than aggregating Shopify directly, so it inherits exactly the
-- same scope filter as the demand numbers above it and cannot drift from them.
-- SHOPIFY_ORDERS_ADF keeps a row per pipeline load, so it is de-duplicated to
-- the latest row per order id first.

WITH params AS (
    SELECT :brand_label::TEXT AS brand_label,
           :report_date::DATE AS report_date
),

brand AS (
    SELECT DISTINCT g.BRAND_LABEL, g.BRAND_ID
    FROM SANDBOX.SBX_RRAJASEKAR.TB_SIGMA_QA_GLANCE_BRAND g
    JOIN params p ON g.BRAND_LABEL = p.brand_label
),

-- Latest Shopify row per order id.
shopify_latest AS (
    SELECT s.ID,
           s.TOTALDISCOUNT,
           ROW_NUMBER() OVER (PARTITION BY s.ID ORDER BY s.CREATEDAT DESC) AS rn
    FROM SHOPIFY_APP.DEV_BRONZE.SHOPIFY_ORDERS_ADF s
),

redeemed AS (
    SELECT SUM(COALESCE(sl.TOTALDISCOUNT, 0))                        AS PROMO_DISCOUNT_AMT,
           COUNT_IF(COALESCE(sl.TOTALDISCOUNT, 0) > 0)               AS PROMO_ORDERS
    FROM SANDBOX.SBX_RRAJASEKAR.TB_SIGMA_ORDERS_QA o
    JOIN params p
      ON o.BRAND_LABEL = p.brand_label
     AND o.REPORT_DATE = p.report_date
    LEFT JOIN shopify_latest sl
      ON sl.ID = o.ORDER_ID
     AND sl.rn = 1
),

scheduled AS (
    SELECT pr.PROMO_TEXT, pr.EMAIL_TEXT
    FROM SANDBOX.SBX_RRAJASEKAR.ECOM_DAILY_PROMO pr
    JOIN brand b  ON pr.BRAND_ID  = b.BRAND_ID
    JOIN params p ON pr.PROMO_DATE = p.report_date
)

SELECT NULLIF(TRIM(COALESCE(s.PROMO_TEXT, '')), '') AS PROMO_TEXT,
       NULLIF(TRIM(COALESCE(s.EMAIL_TEXT, '')), '') AS EMAIL_TEXT,
       COALESCE(r.PROMO_DISCOUNT_AMT, 0)            AS PROMO_DISCOUNT_AMT,
       COALESCE(r.PROMO_ORDERS, 0)                  AS PROMO_ORDERS
FROM redeemed r
LEFT JOIN scheduled s ON TRUE
