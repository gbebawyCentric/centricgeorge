# Daily Ecom Mail — Sigma workbooks as code

Sigma workbooks reproducing the daily ecom recap email for Hudson, Favorite
Daughter and Joe's, so the recap can be scheduled from Sigma instead of the
current external job.

The emails are three separately themed documents, so this builds **one workbook
per brand**. Everything is defined as code: `scripts/brands.py` holds the
per-brand theme and copy, `scripts/sources.py` the SQL that Sigma column
formulas cannot express, `scripts/build_spec.py` assembles a spec, and
`scripts/deploy.py` pushes it through the Sigma API. `sql/` stays the runnable
Snowflake reference for the logic.

## Where the credentials go

In a local `.env` file — **not** in chat, a commit, or a command line.

```bash
cp .env.example .env
$EDITOR .env                    # paste SIGMA_CLIENT_ID and SIGMA_CLIENT_SECRET
set -a && . ./.env && set +a    # load into the shell
```

`.env` is gitignored. Create the credential in Sigma under
**Administration → APIs & Embed Secrets → Create New**; the secret is shown once
at creation and cannot be retrieved afterwards. Check `SIGMA_API_BASE_URL`
matches your Sigma cloud.

To deploy from inside a Claude Code session instead of a laptop, the same
variables are set on the environment rather than in a file. See
`docs/remote-session-setup.md`.

## Deploying

```bash
python3 scripts/build_spec.py            # regenerate sigma/workbook_*.json
python3 scripts/deploy.py --dry-run
export SIGMA_FOLDER_ID=…                 # folder to create them in
python3 scripts/deploy.py                # all three brands
python3 scripts/deploy.py --brand FD     # just one
```

No dependencies beyond Python 3.10+. `SIGMA_FOLDER_ID` (or `--folder-id`)
applies on create only; an existing workbook is updated where it already lives.
Use it for a personal folder, which has no workspace id; it takes precedence
over `SIGMA_WORKSPACE_ID`.

Deploys are idempotent. `sigma/deployed.json` records the workbook id per brand
and is preferred over a name lookup — the workbook listing lags a few seconds
behind a create, so a name lookup straight after one comes back empty and makes
a second copy. Delete an entry to deliberately create a fresh workbook.

To send, add a scheduled export per workbook. The Brand control already defaults
to that workbook's brand.

## What each workbook contains

Top to bottom, mirroring the email:

| Email block | Element(s) | Source |
|---|---|---|
| Themed banner, brand name, scope line | `ctr_banner` → `txt_title`, `txt_kicker`, `txt_scope` | static |
| Retail boutiques added (FD only) | `kpi_retail_amt`, `kpi_retail_orders` | `TB_SIGMA_RETAIL_DAILY_PULSE` |
| Four plan-tracked KPI cards | `kpi_yest_vs_plan`, `kpi_yest_vs_ly`, `kpi_mtd_vs_plan`, `kpi_mtd_vs_ly` | `TB_SIGMA_QA_GLANCE_BRAND` |
| Promo & email copy, with the purchase figures beside it | `tbl_promo`, `kpi_promo_amt`, `kpi_promo_orders` | `ECOM_DAILY_PROMO`, inline SQL |
| Performance detail grid, incl. the Demand Plan row | `tbl_performance` | inline SQL |
| Retail + total DTC (FD only) | `tbl_channel_dtc` | `TB_SIGMA_CHANNEL_FD` |
| Top 5 MTD retail styles, one column per boutique (FD only) | `tbl_store_0..2` | inline SQL |
| "Retail is on a separate platform" note (Joe's only) | `txt_retail_note` | static |
| Top 10 sold / returned, with product thumbnails | `tbl_top_sold`, `tbl_top_returned` | inline SQL |

Per-brand accents come from the rendered emails: Hudson `#1B3A4B`, Favorite
Daughter `#6B1D32`, Joe's `#111111`.

## The spec schema

Workbooks-as-code is in private beta and its schema is not publicly documented,
so the shape used here was read off live workbooks rather than guessed:

```bash
python3 scripts/get_spec.py 6vUEJAG6qufed10qtaM140 -o reference_spec.json
```

Things that are easy to get wrong:

- `elements` is a **flat** list on `document`. The page an element belongs to is
  decided by `layout`, and **every element must appear there** — to keep one off
  the report, put it on a page marked `visibility: "hidden"`.
- `layout` is an **XML string** — a `<Page>` per page holding `<Element>` and
  `<Container>` nodes on a 24-column grid. No per-element x/y/width/height.
- A table's `source` is `warehouse-table`, `sql` (an inline `statement`), or
  `table` (another element). `union`, `join` and `transpose` also exist.

The POST body is the spec itself, not `{"spec": …}`, and an update is **PUT** —
`PATCH` on that path 404s. When a deploy is rejected, `deploy.py` prints the
API's validation body verbatim; it names the offending field and often dumps the
full expected type.

Constraints found by deploying, each of which rejected a build here:

| Rule | Detail |
|---|---|
| Text is `<p>` only | Inline set is `<u> <sub> <sup> <span> <a>` — no `<h1>`, no `<b>`. A `<span style>` may carry only `color`, `background-color`, `font-size`, `font-family`, so a heading is a font-size and letter-spacing is out. |
| Text has no data binding | A text element is static HTML. There is no `{{COLUMN}}` interpolation. |
| `display` is pivot-only | So `emptyCellDisplay` is unavailable on a normal table. |
| Conditional-format `value` is typed | It must match the column's type. Against a column that fails to resolve the validator asks for a string, which is a useful smell that the formula is broken. |
| Inline SQL is `[Custom SQL/COLUMN]` | Always that literal qualifier, whatever the statement selects from. A bare `[COLUMN]` silently resolves to type `error`. |
| Cross-element refs by name don't work | A `kpi-chart` sourced from another element with `Sum([Yesterday demand])` returns `Unknown column`, so every card reads its own source directly. |
| Hidden columns leave query scope | They still drive control filters, but the query API cannot select them. |

## How the SQL was ported

Five of the seven queries in `sql/` are Sigma column formulas over
`warehouse-table` sources — the `STYLE || ' — ' || COLOR` concatenations, the
channel and brand-name `CASE`s, the KPI trend `CASE`, and the promo
`NULLIF(TRIM(COALESCE(…)))` blank handling. Each carries a `PORTED FROM` comment
naming its source file. The KPI tiles' `UNION ALL` needed no port: it existed to
turn one glance row into four, and the four values are already four columns of
that row, so each card reads its own value/comparison pair.

The rest are inline `sql` sources in `scripts/sources.py`, because each either
generates rows or spans tables:

- **The performance grid.** `TB_SIGMA_QA_KPI_LONG_BRAND` has no Demand Plan
  metric but the email's grid has that row, so it is `UNION`ed in from the
  glance plan columns at `METRIC_SORT` 1.5. A column formula adds a column,
  never a row.
- **Promo purchase totals.** A `ROW_NUMBER()` de-duplication of raw Shopify,
  joined to the in-scope order list and aggregated.
- **Product thumbnails.** Joined through `SHOPIFY_PRODUCT_ADF`.
- **Top 5 MTD retail styles.** Aggregated per boutique from retail orders and
  their line items; there is no pre-built table for it.

Each statement is the same logic as its `sql/` counterpart minus the
`:brand_label` / `:report_date` parameters — every statement keeps `BRAND_LABEL`
and `REPORT_DATE` as output columns so the controls do that filtering. Moving
one into a Snowflake view would turn it back into a `warehouse-table` source.

## What this does not reproduce

- **The narrative paragraph.** The email opens with "Yesterday's ecom demand was
  $98.7k, +7% to plan and +19% to same-day LY…", eight figures interpolated into
  a sentence. A Sigma text element is static HTML with no data binding, so this
  cannot be done. The four KPI cards carry the same figures. This is the largest
  remaining visual difference and it is a hard limit, not a shortcut.
- **The performance grid's date sub-header** ("Tuesday, 9/1/26" under
  "Yesterday"). Not a Sigma table feature.
- **The em dash for blank cells**, because `display` is pivot-table-only.
- **The email's exact card layout** — Sigma renders a value and its change; the
  email prints a percentage with two subtitle lines.

## The SQL

Each file in `sql/` is a standalone query taking `:brand_label` and
`:report_date`, runnable against Snowflake by substituting the two parameters.
They are the reference definition of the logic.

`docs/data-mapping.md` traces every email block to its element and Snowflake
source, records the non-obvious decisions, and lists the known data gaps.

## Verified against the warehouse

Checked by querying the deployed workbooks back through the Sigma API and
comparing with Snowflake and with the rendered email:

- **Top 5 MTD retail styles** reproduces the 8/31 email's Madison Avenue column
  exactly — same five styles, units and dollars, in the same order (ranking by
  units then dollars is what breaks the email's ties the way it breaks them).
- **Product thumbnails** resolve for all 870 rows of `TB_SIGMA_DAILY_TOP_STYLES`
  and return the same `cdn.shopify.com` URLs the email embeds.
- **KPI trend formulas** match the `CASE` they were ported from to eight decimal
  places, and `tbl_top_sold` returns the same rows as `sql/el_top_sold.sql`.
- **The Demand Plan row** returns with its plan figures, at the right position.

Note the source tables stop at 2026-08-27 (`TB_SIGMA_CHANNEL_FD` holds only
2026-08-26), so a later report date renders empty. That is the state of the
tables, not of the workbooks.
