-- Email block: "Top 10 sold" (yesterday, ecom).
-- Units and dollars come straight from the validated pipeline table so the
-- workbook and the existing QA workbook always agree; only the product image
-- is joined on here.
--
-- Image resolution: order line -> Shopify product -> featuredImageUrl, keyed on
-- style + color. Colour sits in a different slot of VARIANTTITLE per brand
-- (FD/Hudson "colour / size", Joe's "size / COLOUR"), so the size-shaped part is
-- discarded rather than assuming a position. This reproduces the image URLs on
-- TB_SIGMA_TOP_STYLES_CURR exactly for all 30 current rows across the 3 brands.
WITH d AS (
  SELECT MAX(DT_PT) AS DT_PT
  FROM SANDBOX.SBX_RRAJASEKAR.TB_SIGMA_DAILY_TOP_STYLES
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
  t.RANK_IN_DAY,
  t.STYLE,
  t.COLOR,
  t.STYLE || ' — ' || t.COLOR AS STYLE_COLOR,
  t.QTY,
  t.DEMAND_AMT,
  img.IMAGE_URL,
  t.DT_PT
FROM SANDBOX.SBX_RRAJASEKAR.TB_SIGMA_DAILY_TOP_STYLES t
JOIN d ON t.DT_PT = d.DT_PT
LEFT JOIN img
       ON img.BRAND_ID = t.BRAND_ID
      AND img.STYLE_K  = UPPER(TRIM(t.STYLE))
      AND img.COLOR_K  = UPPER(TRIM(t.COLOR))
WHERE t.BRAND_ID = '{{BRAND_ID}}'
  AND t.RANK_IN_DAY <= 10
ORDER BY t.RANK_IN_DAY
