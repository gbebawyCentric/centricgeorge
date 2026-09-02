# Data mapping — email block → workbook element → Snowflake

Every figure in the daily recap email, traced to where it comes from. All the
SQL in `sql/` was run against Snowflake and returns the values shown here.

## Sources

| Snowflake object | Grain | Used for |
|---|---|---|
| `SANDBOX.SBX_RRAJASEKAR.TB_SIGMA_QA_GLANCE_BRAND` | brand + day | Header narrative, the four KPI tiles, plan columns |
| `SANDBOX.SBX_RRAJASEKAR.TB_SIGMA_QA_KPI_LONG_BRAND` | brand + day + metric | Performance grid rows |
| `SANDBOX.SBX_RRAJASEKAR.TB_SIGMA_DAILY_TOP_STYLES` | brand + day + rank | Top 10 sold |
| `SANDBOX.SBX_RRAJASEKAR.TB_SIGMA_TOP_RETURNS` | brand + day + rank | Top 10 returned |
| `SANDBOX.SBX_RRAJASEKAR.TB_SIGMA_CHANNEL_FD` | brand + day + channel | Retail + Total DTC (FD only) |
| `SANDBOX.SBX_RRAJASEKAR.TB_SIGMA_ORDERS_QA` | one in-scope ecom order | Promo discount scope |
| `SANDBOX.SBX_RRAJASEKAR.ECOM_DAILY_PROMO` | brand + day | Scheduled promo / email copy |
| `SHOPIFY_APP.DEV_BRONZE.SHOPIFY_ORDERS_ADF` | order id, one row per load | `TOTALDISCOUNT` for promo purchase |

Connection: `CENTRIC_SNOWPATH_PRD` (`0a226657-a09f-4684-9465-820374fb6c30`).

## Block by block

| Email block | Element | SQL |
|---|---|---|
| Brand banner + narrative paragraph | `txt_header` | `sql/el_header.sql` |
| Four cards under "Ecom KPIs (plan-tracked)" | `kpi_yest_vs_plan`, `kpi_yest_vs_ly`, `kpi_mtd_vs_plan`, `kpi_mtd_vs_ly` | `sql/el_kpi_tiles.sql` |
| "Promo & email" | `txt_promo` | `sql/el_promo.sql` |
| "Performance detail — ecom only" | `tbl_performance` | `sql/el_performance_grid.sql` |
| "Retail + total DTC" | `tbl_channel_dtc` | `sql/el_channel_dtc.sql` |
| "Top 10 sold" | `tbl_top_sold` | `sql/el_top_sold.sql` |
| "Top 10 returned" | `tbl_top_returned` | `sql/el_top_returned.sql` |

Brands are `Hudson`, `FD`, `Joe's` (brand ids `hudson-jeans`, `favorite-daughter`,
`joes-jeans`).

## Decisions worth knowing

**Demand Plan row.** The email's performance grid has a Demand Plan row, but
`TB_SIGMA_QA_KPI_LONG_BRAND` has no such metric — it carries Demand Sales,
Orders, Units, UPT, AOV, AUR and a set of not-yet-populated ones. The row is
assembled from the glance table's plan columns and unioned in at sort position
2, so the grid reads in the same order as the email.

**Promo discounts.** Taken by joining `TB_SIGMA_ORDERS_QA` (the in-scope order
list) back to raw Shopify on `ORDER_ID = SHOPIFY_ORDERS_ADF.ID`, rather than
aggregating Shopify directly. That way the promo figure inherits exactly the
same scope filter as the demand numbers above it and cannot drift from them.
The join key is the full GID (`gid://shopify/Order/…`), not `NUMERICORDERID`;
matching on the numeric column returns zero rows. Shopify keeps one row per
pipeline load, so it is de-duplicated to the latest row per order id first.
Verified at 100% match for all three brands on 2026-08-27.

**Date labels.** `TO_CHAR` has no format token for an unpadded month/day, and
`'DAY'` yields a blank-padded uppercase name, so "Tuesday, 9/1/26" is built
from `DAYNAME` + `MONTH`/`DAY`/`YEAR`. `DAYNAME` is mapped explicitly so the
output does not depend on the session's `WEEK_START`.

**LY** is the same weekday last year, i.e. −364 days, per the email footer.

**Favorite Daughter only.** `TB_SIGMA_CHANNEL_FD` holds FD rows alone — it is
the one brand whose boutiques run on Shopify. `tbl_channel_dtc` is set to hide
when empty, so Hudson and Joe's do not render a blank table. Joe's retail is on
a separate platform and is not in Snowflake yet.

**Top 10 returned** is Shopify refunds only. It is not the Loop return rate,
which is not in Snowflake (see `TB_SIGMA_DATA_GAPS`). Days with no refunds
return no rows and the element shows its empty state, matching the "No rows for
this day." seen in all three attachments.

## Known gaps

Carried from `TB_SIGMA_DATA_GAPS` and the source map; these appear in the email
as "KPI additions in progress":

- Margin $ / Margin % — not modelled
- Media Spend, CAC / CPO — ad platforms not piped to Snowflake
- Traffic, CVR — GA4 not in the ADF feed
- Net Sales — not modelled
- Loop return rate / status — Loop platform export or API needed

## Differences from the attached emails

Two things the Sigma-native build does not reproduce, both inherent to
rendering from workbook elements rather than hand-built HTML:

1. **Product thumbnails.** The attachments show a 56px Shopify image beside each
   top-10 row. `TB_SIGMA_DAILY_TOP_STYLES` carries no image URL; the URLs come
   from `SHOPIFY_PRODUCT_ADF.featuredImageUrl`. Adding them means extending that
   table with a product id and joining through.
2. **Per-brand theming.** The emails are themed per brand (Hudson `#1B3A4B`,
   Favorite Daughter `#6B1D32`, Joe's `#111111`). One workbook renders a single
   theme for all three; `ACCENT` in `scripts/build_spec.py` sets it. Per-brand
   colour needs either three workbooks or conditional formatting driven by a
   brand-colour column.

Plan data also exists for recent dates, so the tiles render real percentages
rather than the "—" placeholders visible in the attachments.
