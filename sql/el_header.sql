-- Element: txt_header  (the dark brand banner and its narrative paragraph)
--
-- Returns exactly one row. Every string the banner needs is assembled here so
-- the workbook text element only has to interpolate columns, never compute.
--
-- LY is the same weekday last year (-364 days), matching the email footer note.

WITH params AS (
    SELECT :brand_label::TEXT AS brand_label,
           :report_date::DATE AS report_date
),

glance AS (
    SELECT g.*
    FROM SANDBOX.SBX_RRAJASEKAR.TB_SIGMA_QA_GLANCE_BRAND g
    JOIN params p
      ON g.BRAND_LABEL = p.brand_label
     AND g.REPORT_DATE = p.report_date
)

SELECT g.BRAND_LABEL,
       g.BRAND_ID,
       g.REPORT_DATE,

       -- Display name as it appears in the banner headline.
       CASE g.BRAND_ID
            WHEN 'hudson-jeans'      THEN 'Hudson Jeans'
            WHEN 'favorite-daughter' THEN 'Favorite Daughter'
            WHEN 'joes-jeans'        THEN 'Joe''s Jeans'
            ELSE g.BRAND_LABEL
       END AS BRAND_DISPLAY_NAME,

       -- Scope line under "DAILY ECOM RECAP"; each brand words this differently.
       CASE g.BRAND_ID
            WHEN 'hudson-jeans'      THEN 'Brand-owned website sales (Nordstrom marketplace excluded)'
            WHEN 'favorite-daughter' THEN 'Brand-owned website (ecom) — retail boutiques shown separately below.'
            ELSE 'Brand-owned website sales'
       END AS SCOPE_LINE,

       -- "Today = Tuesday, 9/1/26" / "Same Day LY = Tuesday, 9/2/25".
       -- Built by hand rather than with TO_CHAR: Snowflake has no format token
       -- for an unpadded month/day, and 'DAY' yields a blank-padded uppercase
       -- name. DAYNAME is mapped explicitly so the result does not depend on
       -- the session WEEK_START setting.
       DECODE(DAYNAME(g.REPORT_DATE),
              'Mon', 'Monday',   'Tue', 'Tuesday', 'Wed', 'Wednesday',
              'Thu', 'Thursday', 'Fri', 'Friday',  'Sat', 'Saturday',
              'Sun', 'Sunday')
         || ', ' || MONTH(g.REPORT_DATE)
         || '/'  || DAY(g.REPORT_DATE)
         || '/'  || RIGHT(TO_VARCHAR(YEAR(g.REPORT_DATE)), 2) AS TODAY_LABEL,

       DECODE(DAYNAME(DATEADD(day, -364, g.REPORT_DATE)),
              'Mon', 'Monday',   'Tue', 'Tuesday', 'Wed', 'Wednesday',
              'Thu', 'Thursday', 'Fri', 'Friday',  'Sat', 'Saturday',
              'Sun', 'Sunday')
         || ', ' || MONTH(DATEADD(day, -364, g.REPORT_DATE))
         || '/'  || DAY(DATEADD(day, -364, g.REPORT_DATE))
         || '/'  || RIGHT(TO_VARCHAR(YEAR(DATEADD(day, -364, g.REPORT_DATE))), 2) AS SAME_DAY_LY_LABEL,

       DATEADD(day, -364, g.REPORT_DATE)                           AS SAME_DAY_LY_DATE,

       -- Raw values behind the narrative sentence.
       g.YESTERDAY_DEMAND,
       g.Y_DEMAND_PLAN,
       g.PCT_YEST_VS_PLAN,
       g.PCT_YEST_VS_LY,
       g.MTD_DEMAND,
       g.TOTAL_MONTH_PLAN,
       g.PCT_MTD_VS_PLAN,
       g.PCT_MTD_VS_LY
FROM glance g
