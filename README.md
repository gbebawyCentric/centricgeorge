# Daily Ecom Mail — Sigma workbook as code

A Sigma workbook that reproduces the daily ecom recap email for Hudson,
Favorite Daughter and Joe's, so the recap can be scheduled from Sigma instead
of the current external job.

The workbook is defined as code: `sql/` holds one runnable query per email
block, `scripts/build_spec.py` assembles them into a workbook spec, and
`scripts/deploy.py` pushes it through the Sigma API.

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

## Deploying

```bash
python3 scripts/build_spec.py     # regenerate sigma/workbook_spec.json
python3 scripts/deploy.py --dry-run
python3 scripts/deploy.py         # create, or update if it already exists
```

No dependencies beyond Python 3.10+. Deploy is idempotent — it looks the
workbook up by name and PATCHes when it already exists, so re-running will not
leave duplicates.

### Read this before the first deploy

Workbooks-as-code is in private beta and its spec schema is not publicly
documented. `sigma/workbook_spec.json` is written to the documented shape
(`name` / `dataSources` / `pages` / `elements` / `layout`) but has **not** been
validated against a live API, because Sigma's API is not reachable from the
environment this was authored in.

So pull a real spec first and diff the shape:

```bash
python3 scripts/get_spec.py 6vUEJAG6qufed10qtaM140 -o reference_spec.json
```

That is the existing **Centric West - Ecom KPI QA** workbook. Compare it against
`sigma/workbook_spec.json` and adjust the builder in `scripts/build_spec.py`
where key names differ. Everything is generated from one place, so corrections
are a single edit rather than a rewrite.

If a deploy is rejected, `deploy.py` prints the API's validation body verbatim —
that names the field it did not like.

## What the workbook contains

One page, `Daily Ecom Mail`, with two controls — **Brand** (Hudson / FD / Joe's)
and **Report date** — feeding every element. Top to bottom it mirrors the email:

| | Element |
|---|---|
| Brand banner + narrative paragraph | `txt_header` |
| Four plan-tracked KPI cards, red/green/grey | `kpi_yest_vs_plan`, `kpi_yest_vs_ly`, `kpi_mtd_vs_plan`, `kpi_mtd_vs_ly` |
| Promo & email block | `txt_promo` |
| Performance detail grid | `tbl_performance` |
| Retail + total DTC (FD only, hidden otherwise) | `tbl_channel_dtc` |
| Top 10 sold / Top 10 returned | `tbl_top_sold`, `tbl_top_returned` |

To send it, add a scheduled export in Sigma on the workbook, one schedule per
brand with the Brand control pinned, leaving Report date on its default of
yesterday.

## The SQL

Each file in `sql/` is a standalone query taking `:brand_label` and
`:report_date`, bound from the controls. Every one was run against Snowflake
and returns figures matching the attached emails — including the `Tuesday,
9/1/26` / `Tuesday, 9/2/25` date labels and the promo discount totals.

Run one by hand by substituting the two parameters.

`docs/data-mapping.md` traces every email block to its element and Snowflake
source, records the non-obvious decisions (how the Demand Plan row is
assembled, why promo discounts join through the in-scope order list), and lists
the known data gaps.

## Two things this does not reproduce

- **Product thumbnails** next to the top-10 rows. The image URLs live in
  `SHOPIFY_PRODUCT_ADF.featuredImageUrl` and `TB_SIGMA_DAILY_TOP_STYLES` has no
  product id to join on.
- **Per-brand theming.** One workbook renders one accent colour for all three
  brands; the emails are themed per brand.

Both are covered in `docs/data-mapping.md`.
