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

Connection: **Centric Brands POC** (`82dc9446-e21c-4484-987d-79b52a490e2a`).
This is the connection the existing Ecom KPI QA workbook uses to read these same
`SANDBOX.SBX_RRAJASEKAR` tables, so it is known to resolve them.
`CENTRIC_SNOWPATH_PRD` (`0a226657-a09f-4684-9465-820374fb6c30`) also exists and
is what earlier drafts named, but it is not demonstrated against these tables.

## Block by block

Each element reads its table directly; the SQL is the reference copy of the
logic, ported to column formulas in `scripts/build_spec.py`.

| Email block | Element | Ported from |
|---|---|---|
| Title + scope prose | `txt_title`, `txt_sub` | `sql/el_header.sql` (prose only — see below) |
| "Ecom KPIs (plan-tracked)" | `tbl_glance` | `sql/el_header.sql`, `sql/el_kpi_tiles.sql` |
| "Promo & email" | `tbl_promo` | `sql/el_promo.sql` (copy only) |
| "Performance detail — ecom only" | `tbl_performance` | `sql/el_performance_grid.sql` |
| "Retail + total DTC" | `tbl_channel_dtc` | `sql/el_channel_dtc.sql` |
| "Top 10 sold" | `tbl_top_sold` | `sql/el_top_sold.sql` |
| "Top 10 returned" | `tbl_top_returned` | `sql/el_top_returned.sql` |

The four KPI tiles were one row per tile, produced by a `UNION ALL` over a
single glance row. A column formula cannot generate rows — but it does not need
to here, because the four values are already four columns of that row. Each tile
reads its own column plus its own ported `TREND_*` formula.

Brands are `Hudson`, `FD`, `Joe's` (brand ids `hudson-jeans`, `favorite-daughter`,
`joes-jeans`).

## Decisions worth knowing

**Demand Plan row.** The email's performance grid has a Demand Plan row, but
`TB_SIGMA_QA_KPI_LONG_BRAND` has no such metric — it carries Demand Sales,
Orders, Units, UPT, AOV, AUR and a set of not-yet-populated ones.
`sql/el_performance_grid.sql` assembles it from the glance table's plan columns
and unions it in at sort position 2. **The workbook does not carry this row**: a
column formula adds a column, never a row. Its figures are on `tbl_glance`
instead (Yesterday plan $, Month plan $, To-go $, % plan achieved). Adding a
`Demand Plan` row to `TB_SIGMA_QA_KPI_LONG_BRAND` upstream would make it an
ordinary grid row.

**Metric ordering.** `TB_SIGMA_QA_KPI_LONG_BRAND` already carries `METRIC_SORT`
(Demand Sales 1, Orders 2, Units 3, UPT 4, AOV 5, AUR 6), so the hand-rolled
sort `CASE` in `sql/el_performance_grid.sql` is not ported — the native column
gives the same order. The SQL's numbering differs only because it leaves a slot
for the Demand Plan row above.

**Report date column.** `TB_SIGMA_DAILY_TOP_STYLES` and `TB_SIGMA_TOP_RETURNS`
carry both `DT_PT` and `REPORT_DATE`. The SQL joins on `DT_PT`; the two are
equal on every row (checked across all 870 and 145 rows), so the workbook uses
`REPORT_DATE` throughout and one date control binds to every element uniformly.

**Promo brand key.** `ECOM_DAILY_PROMO` is keyed by `BRAND_ID` while every other
table is keyed by `BRAND_LABEL`. `tbl_promo` derives a `BRAND_LABEL` column with
a `Switch` on brand id so the one Brand control filters it too.

**Promo discounts.** Taken by joining `TB_SIGMA_ORDERS_QA` (the in-scope order
list) back to raw Shopify on `ORDER_ID = SHOPIFY_ORDERS_ADF.ID`, rather than
aggregating Shopify directly. That way the promo figure inherits exactly the
same scope filter as the demand numbers above it and cannot drift from them.
The join key is the full GID (`gid://shopify/Order/…`), not `NUMERICORDERID`;
matching on the numeric column returns zero rows. Shopify keeps one row per
pipeline load, so it is de-duplicated to the latest row per order id first.
Verified at 100% match for all three brands on 2026-08-27.

**The workbook does not carry the promo purchase figures.** That de-duplication
is a `ROW_NUMBER()` window over raw Shopify, followed by a cross-table join and
an aggregation — none of which is a column formula, and `TB_SIGMA_ORDERS_QA`
has no `TOTALDISCOUNT` to aggregate element-side. `tbl_promo` carries the
scheduled promo/email copy only. A `TB_SIGMA_PROMO_DAILY` view materialising
`PROMO_DISCOUNT_AMT` and `PROMO_ORDERS` per brand per day — which is exactly
what `sql/el_promo.sql` computes — would make them ordinary columns.

**Date labels.** `TO_CHAR` has no format token for an unpadded month/day, and
`'DAY'` yields a blank-padded uppercase name, so "Tuesday, 9/1/26" is built
from `DAYNAME` + `MONTH`/`DAY`/`YEAR`. `DAYNAME` is mapped explicitly so the
output does not depend on the session's `WEEK_START`. These labels existed only
to be interpolated into the banner prose, which the schema does not support (see
below), so they are not ported; `tbl_glance` carries `SAME_DAY_LY_DATE` as a
real date via `DateAdd("day", -364, …)` and Sigma formats it.

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

Things the Sigma-native build does not reproduce, inherent to rendering from
workbook elements rather than hand-built HTML:

0. **The narrative banner paragraph.** A text element in this schema is static
   HTML with no data binding — every text element in the reference workbook is
   fixed prose. The email's opening sentence interpolates eight figures, which a
   static body cannot do. They are all columns on `tbl_glance`; the prose around
   them is static. (An earlier draft of `build_spec.py` assumed a `{{COLUMN}}`
   placeholder syntax in text bodies. No such thing exists in the real schema.)
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
