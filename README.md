# Daily Ecom Recap — Sigma workbook as code

A Sigma workbook whose pages are the daily ecom recap emails: one page per
brand (Hudson Jeans, Favorite Daughter, Joe's Jeans), each laid out to be sent
as that brand's morning mail. The three mails it reproduces are kept in
`reference/` for comparison.

```
sigma/sql/                  one query per email block, {{BRAND_ID}}-templated
sigma/workbook_spec.yaml    the generated spec (also .json — same content)
scripts/build_spec.py       renders the spec from the SQL + per-brand config
scripts/sigma_api.py        get / create / update a spec through the Sigma API
docs/email-parity.md        block-by-block map, differences, checks run
docs/schedule-setup.md      how the three sends are configured
reference/                  the three mails being replaced
```

## Build

```bash
python3 scripts/build_spec.py                 # -> sigma/workbook_spec.yaml
python3 scripts/build_spec.py --format json   # -> sigma/workbook_spec.json
```

No dependencies. To read one block's SQL exactly as the workbook will run it:

```bash
python3 scripts/build_spec.py --print-sql hudson-jeans 01_header
```

## Create it in Sigma

```bash
export SIGMA_CLIENT_ID=...        # Administration > APIs & Embed Secrets
export SIGMA_CLIENT_SECRET=...

python3 scripts/sigma_api.py whoami
python3 scripts/sigma_api.py create --spec sigma/workbook_spec.yaml --confirm
```

Then follow `docs/schedule-setup.md` to attach the three schedules, and record
the new workbook id there.

Subsequent changes go through the same path — edit the SQL or the layout,
rebuild, and `update <workbookId>`, so the canvas never becomes the source of
truth.

## Verifying the spec shape

**Do this before the first `create`.** Every query in `sigma/sql/` was run
against the warehouse and the results checked against the mails
(see `docs/email-parity.md`); the *spec field names* are the one part that was
not verified against a live Sigma org, because the environment this was written
in has no route to the Sigma API — the egress proxy answers `403` to
`aws-api.sigmacomputing.com`, so no call could be made from here:

```
$ python3 scripts/sigma_api.py create --confirm
error: POST /v2/auth/token -> could not reach https://aws-api.sigmacomputing.com: Tunnel connection failed: 403 Forbidden
```

Workbooks as Code is also in private beta, so its schema is not in the public
docs (`help.sigmacomputing.com` is blocked by the same policy). Pull the shape
from a workbook that already exists in this org and compare:

```bash
# "Centric West - Ecom KPI QA" — the workbook the mails already link to
python3 scripts/sigma_api.py get 6vUEJAG6qufed10qtaM140 -o sigma/reference_spec.yaml
```

If the beta names a field differently, the fix is local: the spec is assembled
by five builders at the top of `scripts/build_spec.py` (`source`, `text_el`,
`kpi_el`, `table_el`, `col`). Correct them there and rebuild — the SQL and the
layout do not change.

## Data

Warehouse connection **Centric Brands POC**
(`82dc9446-e21c-4484-987d-79b52a490e2a`), the same one behind *Centric West -
Ecom KPI QA*. The queries read the existing recap pipeline in
`SANDBOX.SBX_RRAJASEKAR` — `TB_SIGMA_QA_GLANCE_BRAND`,
`TB_SIGMA_QA_KPI_LONG_BRAND`, `TB_SIGMA_DAILY_TOP_STYLES`,
`TB_SIGMA_TOP_RETURNS`, `TB_SIGMA_CHANNEL_FD`, `ECOM_DAILY_SALES_PLAN`,
`ECOM_DAILY_PROMO`, `ECOM_SIGMA_BRAND_CONFIG` — and join
`SHOPIFY_APP.DEV_BRONZE` only for the two things that pipeline does not carry at
daily grain: product images and `TOTALDISCOUNT`.

Nothing here creates or alters a warehouse object, so the numbers stay
identical to the existing QA workbook. `TB_SIGMA_SOURCE_MAP` documents the
upstream sources and the metrics that are not in Snowflake yet.

Two design notes worth knowing before editing:

- **Report date is derived, never passed in.** Each page shows the latest
  complete day for its brand, so the send needs no parameter and no edit as the
  feed advances.
- **Display strings are built in SQL**, not from formula chips — the narrative
  sentences, `$12.8k`-style money, signed percentages, and the em dash for a
  missing plan or promo. That keeps the copy identical to the mails and puts the
  "what if it's null" decision in one place.
