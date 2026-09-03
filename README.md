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

- `elements` is a **flat** list on `document`, not nested inside pages. The page
  an element belongs to is decided by `layout`.
- `layout` is an **XML string** — one `<Page>` block per page, holding
  `<Element>` and `<Container>` nodes on a 24-column grid. There is no
  per-element x/y/width/height.
- **Every element must appear in the layout.** To keep one off the report, put it
  on a page marked `visibility: "hidden"`.
- A table's `source` is one of `warehouse-table` (a `[database, schema, table]`
  path), `sql` (an inline `statement`), or `table` (another element). Each column
  carries a Sigma `formula`.

The POST body is the spec itself, not `{"spec": …}`, and an update is **PUT** —
`PATCH` on that path 404s. If a deploy is rejected, `deploy.py` prints the API's
validation body verbatim; it names the offending field and often dumps the full
expected type, which is the fastest way to correct the builder.

Constraints found by deploying, each of which rejected a build here:

| Rule | Detail |
|---|---|
| Text is `<p>` only | Inline set is `<u> <sub> <sup> <span> <a>`; no `<h1>`. A `<span style>` may carry only `color`, `background-color`, `font-size`, `font-family` — so a heading is a font-size, and letter-spacing is out. |
| `display` is pivot-only | So `emptyCellDisplay` is unavailable on a normal table; blank cells render blank, not as the email's em dash. |
| Conditional-format `value` is typed | It must match the column's type — a number against a numeric column. Against a column that fails to resolve, the validator asks for a string, which is a useful smell that the formula is broken. |
| Inline SQL is `[Custom SQL/COLUMN]` | Always that literal qualifier, whatever the statement selects from. A bare `[COLUMN]` silently resolves to type `error`. |
| Cross-element refs by name don't work | A `kpi-chart` sourced from another element with `Sum([Yesterday demand])` returns `Unknown column`. Every card here reads its warehouse table directly instead. |

### How the SQL was ported

The queries in `sql/` are ported into `build_spec.py` as Sigma column formulas.
Each ported formula carries a `PORTED FROM` comment naming its source file.

Five of the seven port cleanly to column formulas over `warehouse-table`
sources — the `STYLE || ' — ' || COLOR` concatenations, the channel and
brand-name `CASE`s, the KPI trend `CASE`, and the promo
`NULLIF(TRIM(COALESCE(…)))` blank handling. The KPI tiles' `UNION ALL` needed no
port at all: it existed to turn one glance row into four, and the four values are
already four columns of that row, so each card reads its own pair.

Two are **not** column formulas, because they generate rows or span tables, and
they use an inline `sql` source instead:

- **The performance grid.** `TB_SIGMA_QA_KPI_LONG_BRAND` has no Demand Plan
  metric; the email has that row. It is `UNION`ed in from the glance table's plan
  columns at sort position 1.5, between Demand Sales and Orders. A column formula
  adds a column, never a row.
- **Promo purchase totals.** A `ROW_NUMBER()` de-duplication of raw Shopify,
  joined to the in-scope order list and aggregated. `TB_SIGMA_ORDERS_QA` carries
  no `TOTALDISCOUNT` to aggregate element-side.

Both statements live in `build_spec.py` next to the element that uses them and
are the same logic as the matching `sql/` file, minus its `:brand_label` /
`:report_date` filter — the controls do that filtering now. Moving either into a
Snowflake view would turn it back into an ordinary `warehouse-table` source.

## What the workbook contains

Two pages. **Daily Ecom Mail** is the report; **Data** is hidden and holds the
two source tables that only exist to be queried. Two controls — **Brand**
(Hudson / FD / Joe's) and **Report date** — filter every element on both.

Top to bottom the report mirrors the email:

| Email block | Element(s) | Source |
|---|---|---|
| Dark banner + scope prose | `ctr_banner` → `txt_title`, `txt_scope` | static |
| Four plan-tracked KPI cards | `kpi_yest_vs_plan`, `kpi_yest_vs_ly`, `kpi_mtd_vs_plan`, `kpi_mtd_vs_ly` | `TB_SIGMA_QA_GLANCE_BRAND` |
| Promo & email copy, with the two purchase figures beside it | `tbl_promo` + `kpi_promo_amt`, `kpi_promo_orders` | `ECOM_DAILY_PROMO`, inline SQL |
| Performance detail grid, incl. the Demand Plan row | `tbl_performance` | inline SQL |
| Retail + total DTC (FD only; empty for the others) | `tbl_channel_dtc` | `TB_SIGMA_CHANNEL_FD` |
| Top 10 sold / Top 10 returned, side by side | `tbl_top_sold`, `tbl_top_returned` | `TB_SIGMA_DAILY_TOP_STYLES`, `TB_SIGMA_TOP_RETURNS` |

Presentation is carried on the elements: `kpi-chart` for the cards (value large,
change against a comparison column under it), a `container` with the accent
background behind the banner, per-column `format` (currency, percent, integer,
date) and `hidden` on the key columns the controls filter by, and
`conditionalFormats` turning `% Achieved` red under plan and green at or over it.

On the hidden **Data** page: `tbl_glance`, which carries the ported
`BRAND_DISPLAY_NAME`, `SAME_DAY_LY_DATE` and the four `TREND_*` columns and backs
the Brand control's value list, and `tbl_promo_totals` for inspecting the promo
figures directly.

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

- **The narrative banner paragraph.** A text element is static HTML with no data
  binding, so the email's opening sentence ("Yesterday's ecom demand was $X vs
  plan $Y…") cannot be assembled from columns — an earlier draft of
  `build_spec.py` assumed a `{{COLUMN}}` placeholder syntax that does not exist.
  The four KPI cards carry those same figures instead.
- **Product thumbnails** next to the top-10 rows. The image URLs live in
  `SHOPIFY_PRODUCT_ADF.featuredImageUrl` and `TB_SIGMA_DAILY_TOP_STYLES` has no
  product id to join on. (Columns do take an `image` key, so the blocker is the
  missing join, not the schema.)
- **Per-brand theming.** One workbook renders one accent colour for all three
  brands; the emails are themed per brand. `ACCENT` in `build_spec.py` sets it.
- **A top-10 cut-off.** `WHERE RANK_IN_DAY <= 10` is a row filter, which this
  builder does not set. Both tables are sorted by `RANK_IN_DAY`, so the top 10
  read off the top; add the filter in the UI to drop the tail.
- **The em-dash for blank cells**, because `display` is rejected on a normal
  table (see the constraints table above).

Product thumbnails and per-brand theming are covered in `docs/data-mapping.md`.

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
