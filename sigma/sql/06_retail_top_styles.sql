-- Email block: "Top 5 MTD retail styles", one column per boutique
-- (Favorite Daughter only).
--
-- Retail = Shopify orders tied to a physical location. Only the three
-- boutiques are counted (Madison Avenue / Beverly Hills / Nashville); the
-- "Shopify NY" and "Studio Services" locations are not storefronts and are
-- excluded by the Boutique name filter. Returns no rows for the other brands,
-- whose physical retail is on a separate platform.
WITH d AS (
  SELECT MAX(REPORT_DATE) AS REPORT_DATE
  FROM SANDBOX.SBX_RRAJASEKAR.TB_SIGMA_CHANNEL_FD
),
retail_orders AS (
  SELECT
    r.ORDER_ID,
    r.BRAND_ID,
    o.RETAILLOCATIONNAME AS LOCATION_NAME
  FROM SANDBOX.SBX_RRAJASEKAR.VW_SIGMA_ORDERS_RETAIL r
  CROSS JOIN d
  JOIN (
    SELECT x.ID AS ORDER_ID, x.BRANDID AS BRAND_ID, x.RETAILLOCATIONNAME
    FROM SHOPIFY_APP.DEV_BRONZE.SHOPIFY_ORDERS_ADF x
    WHERE x.BRANDID = '{{BRAND_ID}}'
    QUALIFY ROW_NUMBER() OVER (
      PARTITION BY x.BRANDID, x.ID
      ORDER BY x.UPDATEDAT DESC NULLS LAST, x.LOADTIMESTAMP DESC NULLS LAST
    ) = 1
  ) o ON o.ORDER_ID = r.ORDER_ID AND o.BRAND_ID = r.BRAND_ID
  WHERE r.BRAND_ID = '{{BRAND_ID}}'
    AND o.RETAILLOCATIONNAME ILIKE '%Boutique%'
    AND r.DT_PT BETWEEN DATE_TRUNC('month', d.REPORT_DATE) AND d.REPORT_DATE
),
items AS (
  SELECT
    i.ORDERID,
    i.BRANDID AS BRAND_ID,
    i.PRODUCTID,
    i.PRODUCTTITLE,
    i.VARIANTTITLE,
    i.QUANTITY,
    i.DISCOUNTEDUNITPRICE,
    i.LOADTIMESTAMP
  FROM SHOPIFY_APP.DEV_BRONZE.SHOPIFY_ORDER_ITEMS_ADF i
  WHERE i.BRANDID = '{{BRAND_ID}}'
    -- Gift cards are not a style. Left in, a $150 card outsells every garment
    -- in the boutique ranking.
    AND COALESCE(i.ISGIFTCARD, FALSE) = FALSE
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
lines AS (
  SELECT
    ro.LOCATION_NAME,
    UPPER(TRIM(i.PRODUCTTITLE)) AS STYLE_K,
    i.PRODUCTTITLE AS STYLE,
    CASE
      WHEN UPPER(TRIM(SPLIT_PART(i.VARIANTTITLE, '/', 1))) = '' THEN ''
      WHEN REGEXP_LIKE(UPPER(TRIM(SPLIT_PART(i.VARIANTTITLE, '/', 1))), '^[0-9]{1,3}([./-][0-9]{1,3})?$')
        OR REGEXP_LIKE(UPPER(TRIM(SPLIT_PART(i.VARIANTTITLE, '/', 1))), '^(XXS|XS|S|M|L|XL|XXL|XXXL|1X|2X|3X|4X|OS|ONE SIZE|O/S)$')
      THEN TRIM(SPLIT_PART(i.VARIANTTITLE, '/', 2))
      ELSE TRIM(SPLIT_PART(i.VARIANTTITLE, '/', 1))
    END AS COLOR,
    i.PRODUCTID,
    i.QUANTITY,
    COALESCE(i.DISCOUNTEDUNITPRICE, 0) * COALESCE(i.QUANTITY, 0) AS LINE_DEMAND,
    i.LOADTIMESTAMP
  FROM retail_orders ro
  JOIN items i ON i.ORDERID = ro.ORDER_ID AND i.BRAND_ID = ro.BRAND_ID
),
agg AS (
  SELECT
    l.LOCATION_NAME,
    l.STYLE,
    l.COLOR,
    SUM(l.QUANTITY)    AS QTY,
    SUM(l.LINE_DEMAND) AS DEMAND_AMT,
    MAX_BY(pr.IMAGE_URL, l.LOADTIMESTAMP) AS IMAGE_URL
  FROM lines l
  LEFT JOIN prod pr ON pr.PRODUCT_ID = l.PRODUCTID
  GROUP BY 1, 2, 3
)
SELECT
  UPPER(REPLACE(a.LOCATION_NAME, ' Boutique', '')) AS LOCATION_LABEL,
  a.LOCATION_NAME,
  a.STYLE,
  a.COLOR,
  a.STYLE || ' — ' || a.COLOR AS STYLE_COLOR,
  a.QTY,
  a.DEMAND_AMT,
  a.IMAGE_URL,
  ROW_NUMBER() OVER (
    PARTITION BY a.LOCATION_NAME
    ORDER BY a.QTY DESC NULLS LAST, a.DEMAND_AMT DESC NULLS LAST
  ) AS RANK_IN_LOCATION
FROM agg a
QUALIFY RANK_IN_LOCATION <= 5
ORDER BY a.LOCATION_NAME, RANK_IN_LOCATION
