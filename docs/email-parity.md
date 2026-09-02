# Email → workbook parity

Every block of the three mails in `reference/`, mapped to the element that
reproduces it and the query behind it. Read this alongside
`scripts/build_spec.py`, which lays the elements out in this order.

| # | Email block | Page element | SQL block |
|---|---|---|---|
| 1 | Brand header band: name, `DAILY ECOM RECAP`, site note, Today / Same Day LY | `<brand>_header_band` (container, brand accent) | `01_header` |
| 2 | Narrative box ("Yesterday's ecom demand was … MTD ecom demand is …") | `<brand>_narrative` | `01_header` |
| 3 | FD note: "Retail boutiques added $X / N orders yesterday…" | `favorite_daughter_retail_note` | `01_header` (`RETAIL_NOTE_LINE`) |
| 4 | Four KPI tiles: Yesterday vs plan / vs LY, MTD vs plan / vs LY | `<brand>_tile_*` | `01_header` |
| 5 | Promo & email callout, incl. promo purchase $ / orders | `<brand>_promo` | `01_header` |
| 6 | Performance detail table (7 rows × 8 columns) | `<brand>_perf` | `02_performance_grid` |
| 7 | "KPI additions in progress" footnote | `<brand>_kpi_footnote` | static text |
| 8 | Retail + Total DTC table (FD) | `favorite_daughter_channel` | `03_channel_dtc` |
| 9 | Top 5 MTD retail styles per boutique (FD) | `favorite_daughter_retail_top` | `06_retail_top_styles` |
| 10 | Joe's "Retail / DTC" placeholder paragraph | `joes_retail_placeholder` | static text |
| 11 | Refund / feed freshness footnotes | `<brand>_freshness` | `01_header` |
| 12 | Top 10 sold (image, style — color, units, $) | `<brand>_top_sold` | `04_top_sold` |
| 13 | Top 10 returned | `<brand>_top_returned` | `05_top_returned` |
| 14 | Footer (daily send, LY = −364, detail link, as-of) | `<brand>_footer` | `01_header` (`AS_OF_LINE`) |

## Where this differs from the mails in `reference/`

These are differences in the underlying data since those mails were sent, not
layout changes.

- **Plan is populated now.** The reference mails print `—` for every plan figure
  and `-74%`-style LY comparisons only. `ECOM_DAILY_SALES_PLAN` now has rows, so
  the same sentence renders with real numbers: *"Yesterday's ecom demand was
  $5.3k vs plan $14.3k (-63%) and -81% to same-day LY."* The em-dash path is
  still there and still triggers on a missing plan.
- **The reference mails are dated 9/1/26; the feed's latest complete day is
  8/27/26.** The report date is derived per brand rather than hardcoded, so the
  page follows whatever the pipeline has landed.
- **The performance grid shows 7 rows, not 13.** `TB_SIGMA_QA_KPI_LONG_BRAND`
  carries seven metrics that are not in Snowflake yet (Media Spend, CAC/CPO,
  Traffic, CVR, Net Sales, Margin $, Margin %) and they are all null. Rendering
  them would add seven blank rows the mails do not have; they are filtered out
  and stay covered by the "KPI additions in progress" footnote. Drop the
  `METRIC_SORT <= 6` filter in `02_performance_grid.sql` when those land.
- **"Demand Plan" is assembled, not read.** That KPI-long table has no
  `Demand Plan` row, so the grid's second row is built from the plan table with
  the LY columns intentionally blank, matching the mails.
- **Boutique styles are one grouped table, not three columns.** The mail hard-codes
  a column per boutique. Grouping by `LOCATION_LABEL` means a boutique that
  stops reporting drops out instead of leaving a dead column, and a fourth one
  appears without a spec change.

## Checks run against the warehouse

Every query was executed against `CENTRIC_SNOWPATH_PRD` / the `Centric Brands
POC` connection while writing it. What came back:

- **Product images resolve exactly.** `TB_SIGMA_DAILY_TOP_STYLES` has no image
  column, so `04_top_sold` joins order line → Shopify product →
  `featuredImageUrl` on style + colour. Colour sits in a different slot of
  `VARIANTTITLE` per brand (FD/Hudson `colour / size`, Joe's `size / COLOUR`),
  so the size-shaped part is discarded rather than assuming a position.
  Validated against `TB_SIGMA_TOP_STYLES_CURR`, which already carries
  pipeline-resolved URLs: **30 of 30 rows exact, 0 missed, 0 different** across
  all three brands. Keying on colour position alone matched 20 of 30 (Joe's
  missed all ten).
- **Header block returns one row per brand with every field populated** —
  including `Y_DEMAND_PLAN`, MTD plan summed from the daily plan rows, promo
  text from the Marketing Calendar, and promo purchase (`$1.6k across 22
  orders`) from `TOTALDISCOUNT` on the in-scope order set.
- **Performance grid returns the mails' 7 rows in order**, with `Demand Plan`
  in second position and blank LY columns.
- **Channel block returns 3 rows for FD** (Ecom $108.2k / 222 orders, Retail
  $13.6k / 34, Total DTC $121.8k / 256) and **0 rows for Hudson and Joe's**, so
  the FD-only elements simply have nothing to draw on the other pages.
- **Boutique block returns 5 styles for each of the three boutiques.** Gift
  cards had to be excluded: a $150 card was outranking every garment at Beverly
  Hills, so `ISGIFTCARD` lines are dropped.
- **Returns lag the order feed.** `TB_SIGMA_TOP_RETURNS` stops at 8/22 while
  orders run to 8/27. `05_top_returned` keys off the *report* date, not the
  latest date with refund rows — otherwise the page would quietly pair one day's
  KPIs with an older day's returns. On a day with no refunds it returns nothing
  and the table shows "No rows for this day.", which is what the reference mails
  print.

## Known gaps in the data, not the workbook

From `TB_SIGMA_SOURCE_MAP`:

| Metric | State |
|---|---|
| Loop return rate / status | Not in Snowflake — Loop platform / merch Excel |
| Media spend, CAC / CPO | Not in Snowflake — ad platforms, formula TBD |
| Traffic, CVR | Not in Snowflake ADF — GA4 preferred |
| Margin $ / %, Net $ | Columns exist on `TB_SIGMA_EXCEL_*` but are empty |
