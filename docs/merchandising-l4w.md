# Merchandising: L4W is not the last four weeks

Reported by Rod Corpuz, 21 Sep 2026 — "Sigma: L4W Metric not reflecting last 4
weeks". Pulling 9/13–9/20 in the [Merchandising workbook][wb] returned L4W
figures identical to LW.

[wb]: https://app.sigmacomputing.com/centric-brands/workbook/Merchandising-7gixjFsPWIiP0Be4S31grs

## The cause

The L4W measures live on the `SALES_TRANSACTIONS` element (`4NTRg6lY30`), which
reads `CB_ANALYTICS_PRD.VIRTUAL.AGG_SALES_TRANSACTIONS`. All five are built from
these two helper columns:

```
4 WEEKS AGO        DateAdd("week", -4, [DATE RANGE END])
INSIDE DATE RANGE  [Reporting Date] >= [DATE RANGE START] and [Reporting Date] <= [DATE RANGE END]
```

and each one ANDs them together:

```
L4W SALES QTY      If([Reporting Date] >= [4 WEEKS AGO] and [INSIDE DATE RANGE], [Item Qty], 0)
L4W SALES RETAIL   If([Reporting Date] >= [4 WEEKS AGO] and [INSIDE DATE RANGE], …, 0)
L4W SALES DISCOUNT If([Reporting Date] >= [4 WEEKS AGO] and [INSIDE DATE RANGE], [Item Qty] * [Total Discount Amount], 0)
L4W COGS           If([Reporting Date] >= [4 WEEKS AGO] and [INSIDE DATE RANGE], [Item Qty] * [Cost], 0)
L4W NET SALES      [L4W SALES RETAIL] - [L4W SALES DISCOUNT]
```

`[INSIDE DATE RANGE]` is the user's own selection. Intersecting it with the
four-week lookback gives

```
[ max(4 weeks before end, selected start) , selected end ]
```

so whenever the selected range is **shorter than four weeks**, `selected start`
wins and L4W collapses onto the selected range. With 9/13–9/20 selected the L4W
window is 9/13–9/20: the same eight days as LW. The metric only ever differs
from LW when someone selects a range longer than four weeks, which is not how
the report is used.

The MTD, YTD and LAST 12 MONTHS columns sitting beside it in the same element do
**not** have the clamp — they bound on `[DATE RANGE END]` alone and behave
correctly. L4W is the only one carrying `[INSIDE DATE RANGE]`.

Nothing outside these formulas restricts the rows: `SALES_TRANSACTIONS` has no
date filter (its filters are Demand-vs-Actualized, transaction classification,
department, location code, brand, UPC, material), and neither does
`MERCHANDISING BASE` downstream. That is why MTD and YTD can already see outside
the selected range, and why removing the clamp is enough — the history is
already in the element.

## The fix

Bound on the report date the way the other period columns do:

```
- If([Reporting Date] >= [4 WEEKS AGO] and [INSIDE DATE RANGE], …, 0)
+ If([Reporting Date] >= [4 WEEKS AGO] and [Reporting Date] <= [DATE RANGE END], …, 0)
```

on the four base columns. `L4W NET SALES` is derived from two of them and needs
no edit, and the ten or so downstream copies (`MERCHANDISING_BASE (Summary and
Detail)`, `(Size and Best Sellers)`, the hidden pivots) only `Sum()` these, so
they inherit the fix.

### Apply it in the Sigma UI

Four edits, on the `SALES_TRANSACTIONS` element: open each column's formula and
replace `and [INSIDE DATE RANGE]` with `and [Reporting Date] <= [DATE RANGE END]`.

| Column | Column id |
|---|---|
| L4W SALES QTY | `9peS6Tq_yI` |
| L4W SALES RETAIL | `3Y9lcWbZ3h` |
| L4W SALES DISCOUNT | `zGK2nUFdjf` |
| L4W COGS | `sFNu4tPbfQ` |

`L4W NET SALES` is derived from two of these and needs no edit. Neither do the
downstream copies — `MERCHANDISING_BASE (Summary and Detail)`, `(Size and Best
Sellers)` and the hidden pivots only `Sum()` these columns, so they inherit it.

### Why not through the API

`scripts/fix_merchandising_l4w.py` makes exactly these edits to the spec and can
PUT them back. **It does not currently work against this workbook, and it should
not be forced through.** It is kept because the diff it prints is the change to
make by hand, and because the endpoint notes below are worth having.

```bash
set -a && . ./.env && set +a
python3 scripts/fix_merchandising_l4w.py            # print the diff, send nothing
python3 scripts/fix_merchandising_l4w.py --apply    # currently rejected, see below
```

The write verb is `PUT /v2/workbooks/{id}/spec` with the body `{"document": …}`
— **not** the `PATCH` with `{"spec": …}` that the beta documentation describes,
which 404s. That much is now in `sigma_client.update_workbook_document`.

The blocker is that **the workbook's own spec does not survive a round-trip**: a
`GET` of it, PUT back unmodified, is rejected. Three defects found so far, each
surfacing only after the previous one was cleared:

1. Four hidden pivot-tables (`crRPeoTB5L`, `ulq_u8DDfZ`, `VfmuFDDmzt`,
   `U0svjkP5Iu`) carry an `axisTotals` entry for an axis that is not a dimension
   on them. `GET` emits it, `PUT` rejects it. Inert, and the script drops it.
   Note the same id *is* a live dimension on `emvJPA8iri` and `ThA5-G3idu`,
   where the subtotal renders — so this has to be decided per element, not by
   matching the id.
2. `elements[4]`, a text element, references `[SALES_TRANSACTIONS/Last Refresh
   Dts]` by name. The column exists
   (`inode-6NzVzQg0OzAWuKeo736zVd/LAST_REFRESH_DTS`) but `GET` emits it with no
   `name`, so the validator cannot resolve the reference — it is stricter than
   the runtime, which resolves it fine.
3. Unknown. The validator reports one error per request, so there is no way to
   see what is left without submitting again.

(2) is the reason to stop rather than keep patching. `GET` **drops** data the
workbook depends on. A `PUT` replaces the document wholesale, so anything else
`GET` dropped — in a category the validator happens not to check — would be
silently written away across all 112 elements. That is not a trade worth making
against four edits that take two minutes in the UI, on a workbook the
merchandising team reads weekly.

The pre-change spec is saved at
`sigma/merchandising_spec_v71_20260921T175506Z.json` either way. Nothing was
written: the workbook is still at document version 71, `updatedAt`
2026-09-15T19:41:56Z. Every attempt was rejected before it landed.

Worth raising with Sigma support — a spec that cannot be read and written back
unchanged makes the whole workbooks-as-code path unusable for this workbook.

## Verified against the warehouse

`sql/verify_merchandising_l4w.sql` replays both windows over
`AGG_SALES_TRANSACTIONS` for Rod's 9/13–9/20 selection, with the workbook's
row filters. Reporting date follows the workbook
(`Transaction Dts` for DEMAND rows, `Coalesce(Fulfillment Date, Transaction Dts)`
otherwise):

| Window | Sales qty | Net sales | COGS |
|---|---:|---:|---:|
| LW — selected range 9/13–9/20 | 16,577 | $2,789,451 | $631,843 |
| L4W **as it is today** (clamped) | 16,577 | $2,789,451 | $631,843 |
| L4W **unclamped** 8/23–9/20 | 63,601 | $9,275,310 | $2,264,157 |

The clamped row is identical to LW to the dollar, which is the reported symptom.
Unclamped, L4W is roughly 3.8× LW.

(Run 21 Sep 2026. `AGG_SALES_TRANSACTIONS` restates recent rows on refresh — an
earlier run the same morning gave 16,676 for the same window — so re-running
will move these totals a little. The equality will not move.)

These totals are larger than the ones in Rod's export (12,362 qty / $1,573,985)
because the query does not reproduce the left-outer join from
`DIM_LOCATION + DIM_PRODUCT` (which drops sales rows with no matching product or
location) or the `QTY > 0` filter on `MERCHANDISING BASE`, and the
Demand-vs-Actualized control state at export time is unknown. The **equality**
between LW and clamped L4W is what reproduces, and it does so exactly; the
absolute figures are not meant to tie out.

## Two related findings

**1. LW net sales does not multiply the discount by quantity.** This is the
reason Rod saw LW and L4W net sales differ by $2,894 while sales qty and COGS
matched to the unit.

```
MERCHANDISING BASE                       Zn(SumIf(([Item Qty] * [Total Discount Amount]), [INSIDE DATE RANGE]))
MERCHANDISING_BASE (Summary and Detail)  Zn(SumIf([Total Discount Amount], [INSIDE DATE RANGE]))       ← no [Item Qty]
MERCHANDISING_BASE (Size and Best Sellers)  same, no [Item Qty]
```

Every L4W / MTD / YTD / LAST 12 MONTHS discount column multiplies by
`[Item Qty]`; so does the parent `MERCHANDISING BASE`. Only the two summary
elements' `SALES DISCOUNT AMOUNT` — the column behind the **LW** figures — does
not, so it undercounts the discount on any line selling more than one unit and
overstates LW net sales and AUR. On the slice above the gap is $48,003 —
$498,408 of discount qty-weighted against $450,405 unweighted.

This is a second, independent defect. It is **not** part of the fix script,
because correcting it moves the headline LW net sales number that people read
every week, and that should be a deliberate, announced change.

**2. The window is 29 days, not 28.** `[4 WEEKS AGO]` is
`DateAdd("week", -4, [DATE RANGE END])` and the test is `>=`, so both endpoints
are included: for an end date of 9/20 the window runs 8/23–9/20. A four-week
window is 8/24–9/20. The fix script can correct this with
`--fix-window-length`, which is off by default — it changes a published
definition, not a broken one. On the slice above the extra day is 917 units and
$79,142 of net sales.
