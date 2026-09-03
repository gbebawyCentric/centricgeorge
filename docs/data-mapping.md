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
| `SANDBOX.SBX_RRAJASEKAR.TB_SIGMA_RETAIL_DAILY_PULSE` | brand + day | "Retail boutiques added" (FD only) |
| `SANDBOX.SBX_RRAJASEKAR.VW_SIGMA_ORDERS_RETAIL` | one FD retail order | Top 5 MTD retail styles |
| `SHOPIFY_APP.DEV_BRONZE.SHOPIFY_ORDERS_ADF` | order id, one row per load | `TOTALDISCOUNT`; `RETAILLOCATIONNAME` for the boutique |
| `SHOPIFY_APP.DEV_BRONZE.SHOPIFY_ORDER_ITEMS_ADF` | one order line | Retail style / colour / units |
| `SHOPIFY_APP.DEV_BRONZE.SHOPIFY_PRODUCT_ADF` | product | `featuredImageUrl` for the thumbnails |

Connection: **Centric Brands POC** (`82dc9446-e21c-4484-987d-79b52a490e2a`).
This is the connection the existing Ecom KPI QA workbook uses to read these same
`SANDBOX.SBX_RRAJASEKAR` tables, so it is known to resolve them.
`CENTRIC_SNOWPATH_PRD` (`0a226657-a09f-4684-9465-820374fb6c30`) also exists and
is what earlier drafts named, but it is not demonstrated against these tables.

## Block by block

There is **one workbook per brand** (`scripts/brands.py` holds the theme and
copy). The SQL in `sql/` is the reference copy of the logic; most of it is
ported to Sigma column formulas in `scripts/build_spec.py`, and the rest to
inline SQL in `scripts/sources.py`.

| Email block | Element | Source | Ported from |
|---|---|---|---|
| Banner, brand name, scope line | `ctr_banner`, `txt_title`, `txt_kicker`, `txt_scope` | static | `sql/el_header.sql` (prose only — see below) |
| "Retail boutiques added" (FD) | `kpi_retail_amt`, `kpi_retail_orders` | inline SQL | — (new) |
| Four KPI cards | `kpi_yest_vs_plan`, `kpi_yest_vs_ly`, `kpi_mtd_vs_plan`, `kpi_mtd_vs_ly` | `TB_SIGMA_QA_GLANCE_BRAND` | `sql/el_kpi_tiles.sql` |
| "Promo & email" copy | `tbl_promo` | `ECOM_DAILY_PROMO` | `sql/el_promo.sql` (copy half) |
| Promo purchase figures | `kpi_promo_amt`, `kpi_promo_orders` | inline SQL | `sql/el_promo.sql` (totals half) |
| "Performance detail — ecom only" | `tbl_performance` | inline SQL | `sql/el_performance_grid.sql` |
| "Retail + total DTC" (FD) | `tbl_channel_dtc` | `TB_SIGMA_CHANNEL_FD` | `sql/el_channel_dtc.sql` |
| "Top 5 MTD retail styles" (FD) | `tbl_store_0..2` | inline SQL | — (new) |
| Separate-platform note (Joe's) | `txt_retail_note` | static | — |
| "Top 10 sold" | `tbl_top_sold` | inline SQL | `sql/el_top_sold.sql` |
| "Top 10 returned" | `tbl_top_returned` | inline SQL | `sql/el_top_returned.sql` |

The four KPI tiles were one row per tile, produced by a `UNION ALL` over a
single glance row. A column formula cannot generate rows — but it does not need
to here, because the four values are already four columns of that row. Each card
reads its own value/comparison pair and Sigma renders the change between them.

Each card reads its warehouse table directly rather than sourcing from another
element. A cross-element formula like `Sum([Yesterday demand])` does not resolve
through the API — it comes back as `Unknown column` — whereas the
`[TABLE/COLUMN]` form does.

**Top 5 MTD retail styles** has no pre-built table. It aggregates
`VW_SIGMA_ORDERS_RETAIL` joined to `SHOPIFY_ORDER_ITEMS_ADF`, with the boutique
from `SHOPIFY_ORDERS_ADF.RETAILLOCATIONNAME` (`Madison Avenue Boutique`,
`Beverly Hills Boutique`, `Nashville Boutique`) and the thumbnail from
`SHOPIFY_PRODUCT_ADF`. MTD is as-of the report date, not whole-month, so the
element answers the same question on any day the control is set to. Colour is
the variant title's first segment (`navy / one size` → `navy`), which is what
the email prints and also collapses sizes of one colourway into a row. Ranking
is units then dollars, which reproduces the email's tie order.

Brands are `Hudson`, `FD`, `Joe's` (brand ids `hudson-jeans`, `favorite-daughter`,
`joes-jeans`).

## Decisions worth knowing

**Demand Plan row.** The email's performance grid has a Demand Plan row, but
`TB_SIGMA_QA_KPI_LONG_BRAND` has no such metric — it carries Demand Sales,
Orders, Units, UPT, AOV, AUR and a set of not-yet-populated ones.
`sql/el_performance_grid.sql` assembles it from the glance table's plan columns
and unions it in. A column formula adds a column and never a row, so
`tbl_performance` uses an inline `sql` source that carries the same `UNION`,
placing the row at `METRIC_SORT` 1.5 — between Demand Sales (1) and Orders (2),
which is where the email reads it. Adding a `Demand Plan` row to
`TB_SIGMA_QA_KPI_LONG_BRAND` upstream would let the element go back to a plain
`warehouse-table` source.

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

That de-duplication is a `ROW_NUMBER()` window over raw Shopify, followed by a
cross-table join and an aggregation — none of which is a column formula, and
`TB_SIGMA_ORDERS_QA` has no `TOTALDISCOUNT` to aggregate element-side. So the
two figures come from an inline `sql` source instead, rendered as the
`kpi_promo_amt` and `kpi_promo_orders` cards beside the promo copy.
`tbl_promo` itself carries the scheduled promo/email copy only. A
`TB_SIGMA_PROMO_DAILY` view materialising `PROMO_DISCOUNT_AMT` and
`PROMO_ORDERS` per brand per day — exactly what `sql/el_promo.sql` computes —
would turn the cards back into plain `warehouse-table` sources.

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
1. ~~**Product thumbnails.**~~ **Now built.** `TB_SIGMA_DAILY_TOP_STYLES` carries
   no product id, but matching its `STYLE` against `SHOPIFY_PRODUCT_ADF."title"`
   resolves `featuredImageUrl` for all 870 rows, and a Sigma column takes an
   `image` key. The retail-styles grid joins on `PRODUCTID` instead, which is
   exact. Note the featured image is per product, not per variant, so a colourway
   shows its product's main image; variant-level images would need
   `SHOPIFY_PRODUCT_VARIANT_ADF.imageId` → `SHOPIFY_PRODUCT_IMAGE_ADF`.
2. ~~**Per-brand theming.**~~ **Now built.** There is one workbook per brand,
   each themed from `scripts/brands.py` (Hudson `#1B3A4B`, Favorite Daughter
   `#6B1D32`, Joe's `#111111` — taken from the rendered emails). Favorite
   Daughter gets the retail sections; Joe's gets its separate-platform note.

Plan data also exists for recent dates, so the tiles render real percentages
rather than the "—" placeholders visible in the attachments.
