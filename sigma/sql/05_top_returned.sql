-- Email block: "Top 10 returned" (yesterday, ecom).
-- Shopify refunds only - Loop return rate / status is not in Snowflake yet
-- (see TB_SIGMA_SOURCE_MAP).
--
-- The report date is taken from the glance table, i.e. the same day the rest of
-- the email reports on - deliberately NOT the latest day that happens to have
-- refund rows. Refunds lag the order feed, so keying off the refund table would
-- silently pair one day's KPIs with an older day's returns. When there are no
-- refunds for the report date this returns no rows, which is the email's
-- "No rows for this day." state.
WITH d AS (
  SELECT MAX(REPORT_DATE) AS DT_PT
  FROM SANDBOX.SBX_RRAJASEKAR.TB_SIGMA_QA_GLANCE_BRAND
  WHERE BRAND_ID = '{{BRAND_ID}}'
),
items AS (
  SELECT i.BRANDID AS BRAND_ID, i.PRODUCTID, i.PRODUCTTITLE, i.VARIANTTITLE, i.LOADTIMESTAMP
  FROM SHOPIFY_APP.DEV_BRONZE.SHOPIFY_ORDER_ITEMS_ADF i
  WHERE i.BRANDID = '{{BRAND_ID}}'
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY i.BRANDID, i.LINEITEMID
    ORDER BY i.LOADTIMESTAMP DESC NULLS LAST
  ) = 1
),
prod AS (
  SELECT p."brandId" AS BRAND_ID, p."productId" AS PRODUCT_ID, p."featuredImageUrl" AS IMAGE_URL
  FROM SHOPIFY_APP.DEV_BRONZE.SHOPIFY_PRODUCT_ADF p
  WHERE p."brandId" = '{{BRAND_ID}}'
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY p."brandId", p."productId"
    ORDER BY p."loadTimestamp" DESC NULLS LAST
  ) = 1
),
keyed AS (
  SELECT
    i.BRAND_ID,
    i.PRODUCTID,
    i.LOADTIMESTAMP,
    UPPER(TRIM(i.PRODUCTTITLE)) AS STYLE_K,
    CASE
      WHEN UPPER(TRIM(SPLIT_PART(i.VARIANTTITLE, '/', 1))) = '' THEN ''
      WHEN REGEXP_LIKE(UPPER(TRIM(SPLIT_PART(i.VARIANTTITLE, '/', 1))), '^[0-9]{1,3}([./-][0-9]{1,3})?$')
        OR REGEXP_LIKE(UPPER(TRIM(SPLIT_PART(i.VARIANTTITLE, '/', 1))), '^(XXS|XS|S|M|L|XL|XXL|XXXL|1X|2X|3X|4X|OS|ONE SIZE|O/S)$')
      THEN UPPER(TRIM(SPLIT_PART(i.VARIANTTITLE, '/', 2)))
      ELSE UPPER(TRIM(SPLIT_PART(i.VARIANTTITLE, '/', 1)))
    END AS COLOR_K
  FROM items i
),
img AS (
  SELECT k.BRAND_ID, k.STYLE_K, k.COLOR_K,
         MAX_BY(pr.IMAGE_URL, k.LOADTIMESTAMP) AS IMAGE_URL
  FROM keyed k
  JOIN prod pr ON pr.PRODUCT_ID = k.PRODUCTID AND pr.BRAND_ID = k.BRAND_ID
  WHERE pr.IMAGE_URL IS NOT NULL
  GROUP BY 1, 2, 3
)
SELECT
  r.RANK_IN_DAY,
  r.STYLE,
  r.COLOR,
  r.STYLE || ' — ' || r.COLOR AS STYLE_COLOR,
  r.QTY,
  img.IMAGE_URL,
  r.DT_PT
FROM SANDBOX.SBX_RRAJASEKAR.TB_SIGMA_TOP_RETURNS r
JOIN d ON r.DT_PT = d.DT_PT
LEFT JOIN img
       ON img.BRAND_ID = r.BRAND_ID
      AND img.STYLE_K  = UPPER(TRIM(r.STYLE))
      AND img.COLOR_K  = UPPER(TRIM(r.COLOR))
WHERE r.BRAND_ID = '{{BRAND_ID}}'
  AND r.RANK_IN_DAY <= 10
ORDER BY r.RANK_IN_DAY
