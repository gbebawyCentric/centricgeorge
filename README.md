# Daily Ecom Mail — Sigma workbook as code

A Sigma workbook that reproduces the daily ecom recap email for Hudson,
Favorite Daughter and Joe's, so the recap can be scheduled from Sigma instead
of the current external job.

The workbook is defined as code: `scripts/build_spec.py` emits the workbook
spec and `scripts/deploy.py` pushes it through the Sigma API. `sql/` holds one
runnable Snowflake query per email block — the queries are no longer inlined
into the spec, they are the reference copy of logic that now lives in the
workbook as Sigma column formulas.

## Where the credentials go

In a local `.env` file — **not** in chat, a commit, or a command line.

```bash
cp .env.example .env
$EDITOR .env                    # paste SIGMA_CLIENT_ID and SIGMA_CLIENT_SECRET
set -a && . ./.env && set +a    # load into the shell
```

`.env` is gitignored. Create the credential in Sigma under
**Administration → APIs & Embed Secrets → Create New**; the secret is shown
once at creation and cannot be retrieved afterwards. Also check
`SIGMA_API_BASE_URL` matches your Sigma cloud — the default is AWS US.

To deploy from inside a Claude Code session instead of a laptop, the same
variables are set on the environment rather than in a file, and the Sigma API
host has to be allowlisted. See `docs/remote-session-setup.md` — the scripts
read only from the environment, so nothing in the code changes either way.

## Deploying

```bash
python3 scripts/build_spec.py     # regenerate sigma/workbook_spec.json
python3 scripts/deploy.py --dry-run
export SIGMA_FOLDER_ID=…          # folder to create it in; omit to use the default
python3 scripts/deploy.py         # create, or update if it already exists
```

No dependencies beyond Python 3.10+. Deploy is idempotent — it looks the
workbook up by name and PATCHes when it already exists, so re-running will not
leave duplicates. `SIGMA_FOLDER_ID` (or `--folder-id`) only applies on create;
an existing workbook is updated where it already lives. Use it for a personal
folder, which has no workspace id; it takes precedence over
`SIGMA_WORKSPACE_ID`.

### The spec schema

Workbooks-as-code is in private beta and its schema is not publicly documented,
so the shape used here was read off a live workbook rather than guessed:

```bash
python3 scripts/get_spec.py 6vUEJAG6qufed10qtaM140 -o reference_spec.json
```

That is the existing **Centric West - Ecom KPI QA** workbook. Three things about
the real schema are easy to get wrong:

- `elements` is a **flat** list on `document`, not nested inside pages. A page is
  only `{id, name, pageWidth}`.
- `layout` is an **XML string** describing a 24-column grid, one `<Element>` per
  element id. There is no per-element x/y/width/height.
- A table's data comes from `source.kind = "warehouse-table"` naming a
  `[database, schema, table]` path — **not** from inlined SQL. Each column
  carries a Sigma `formula`.

The POST body is the spec itself, not `{"spec": …}`. If a deploy is rejected,
`deploy.py` prints the API's validation body verbatim; it dumps the full
expected type, which is the fastest way to correct the builder.

### Why the SQL is not inlined

Sigma runs a workbook off warehouse tables plus column formulas, so the queries
in `sql/` are ported into `build_spec.py` as formulas rather than shipped as
SQL. Each ported formula carries a `PORTED FROM` comment naming its source file.

Four of the seven port cleanly — the `STYLE || ' — ' || COLOR` concatenations,
the channel and brand-name `CASE`s, the KPI trend `CASE`, and the promo
`NULLIF(TRIM(COALESCE(…)))` blank handling. Two things do not, because they are
row-generating or cross-table work that a column formula cannot express:

- **The Demand Plan grid row.** `sql/el_performance_grid.sql` `UNION`s it in from
  the glance table's plan columns; `TB_SIGMA_QA_KPI_LONG_BRAND` has no such
  metric. A formula adds a column, never a row. The figures are on the KPI
  element instead (Yesterday plan $, Month plan $, To-go $, % plan achieved).
- **Promo purchase totals.** `sql/el_promo.sql` de-duplicates
  `SHOPIFY_ORDERS_ADF` to the latest row per order id with `ROW_NUMBER()`, joins
  it to the in-scope order list and aggregates. `TB_SIGMA_ORDERS_QA` carries no
  `TOTALDISCOUNT`, so there is nothing to aggregate element-side. The scheduled
  promo/email copy does port; only the redeemed-discount figures do not.

Both need a Snowflake view — the natural fix is to add a `Demand Plan` row to
`TB_SIGMA_QA_KPI_LONG_BRAND` and a promo-totals column set to a new
`TB_SIGMA_PROMO_DAILY` — after which each becomes an ordinary column reference
here. The `sql/` queries stay the runnable definition of both in the meantime.

## What the workbook contains

One page, `Daily Ecom Mail`, with two controls — **Brand** (Hudson / FD / Joe's)
and **Report date** — feeding every element. Top to bottom it mirrors the email:

| Email block | Element | Source table |
|---|---|---|
| Title + scope prose | `txt_title`, `txt_sub` | — (static) |
| Plan-tracked KPIs, with a trend column per tile | `tbl_glance` | `TB_SIGMA_QA_GLANCE_BRAND` |
| Promo & email copy | `tbl_promo` | `ECOM_DAILY_PROMO` |
| Performance detail grid | `tbl_performance` | `TB_SIGMA_QA_KPI_LONG_BRAND` |
| Retail + total DTC (FD only; empty for the others) | `tbl_channel_dtc` | `TB_SIGMA_CHANNEL_FD` |
| Top 10 sold | `tbl_top_sold` | `TB_SIGMA_DAILY_TOP_STYLES` |
| Top 10 returned | `tbl_top_returned` | `TB_SIGMA_TOP_RETURNS` |

To send it, add a scheduled export in Sigma on the workbook, one schedule per
brand with the Brand control pinned.

The **Report date** control is a date range (`between`), which is the control
type the reference workbook uses. Set it to a single day for a daily send.

## The SQL

Each file in `sql/` is a standalone query taking `:brand_label` and
`:report_date`. Every one was run against Snowflake and returns figures matching
the attached emails. They are the reference definition of the logic; the
workbook itself now reads the same tables through column formulas, and the two
were checked against each other row for row (see below).

Run one by hand by substituting the two parameters.

`docs/data-mapping.md` traces every email block to its element and Snowflake
source, records the non-obvious decisions (how the Demand Plan row is
assembled, why promo discounts join through the in-scope order list), and lists
the known data gaps.

## What this does not reproduce

- **The narrative banner paragraph.** In the real schema a text element is
  static HTML with no data binding — the reference workbook's text elements are
  all fixed prose. So the email's opening sentence ("Yesterday's ecom demand was
  $X vs plan $Y…") cannot be assembled from columns the way an earlier draft of
  `build_spec.py` assumed with `{{COLUMN}}` placeholders. The figures are all on
  `tbl_glance`; the prose around them is static.
- **Product thumbnails** next to the top-10 rows. The image URLs live in
  `SHOPIFY_PRODUCT_ADF.featuredImageUrl` and `TB_SIGMA_DAILY_TOP_STYLES` has no
  product id to join on.
- **Per-brand theming.** One workbook renders one accent colour for all three
  brands; the emails are themed per brand.
- **A top-10 cut-off.** `WHERE RANK_IN_DAY <= 10` is a filter, not a column
  formula, and this schema has no demonstrated per-element filter key.
  `RANK_IN_DAY` is the leading column so the top 10 read off the top; add the
  filter in the UI to drop the tail.

The last two are covered in `docs/data-mapping.md`.

## Verified against the warehouse

The deployed workbook was queried back through the Sigma API and checked against
the same figures from Snowflake, for Hudson on 2026-08-27:

- All four KPI trend formulas match the `CASE` they were ported from, to eight
  decimal places (`-0.62919940` → `down`, and so on).
- `tbl_top_sold` returns the same five rows as `sql/el_top_sold.sql`, with
  identical `STYLE — COLOUR` labels and demand figures.
- `Switch` on brand id resolves correctly on both `tbl_glance`
  (→ `Hudson Jeans`) and `tbl_promo` (brand id → `Hudson`), and `DateAdd` gives
  2025-08-28 for a 2026-08-27 report date — the same weekday, as intended.

Note that `TB_SIGMA_CHANNEL_FD` currently holds a single day (2026-08-26) and
the glance/KPI tables stop at 2026-08-27, so a later report date renders empty.
That is the state of the tables, not of the workbook.
