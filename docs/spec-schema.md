# The workbook spec schema, as the API actually returns it

Workbooks-as-code is in private beta and Sigma does not publish the spec
schema. This file records the shape observed from a real workbook so nobody has
to re-derive it.

Source: `GET /v2/workbooks/6vUEJAG6qufed10qtaM140/spec` — the **Centric West -
Ecom KPI QA** workbook, `documentVersion` 14, pulled 3 Sep 2026.

Regenerate it any time with:

```bash
python3 scripts/get_spec.py 6vUEJAG6qufed10qtaM140 -o reference_spec.json
```

`reference_spec.json` is gitignored on purpose — it carries connection UUIDs and
internal table paths.

## Top level

The response wraps the writable document in read-only metadata:

```json
{
  "workbookId": "…", "name": "…", "url": "…",
  "documentVersion": 14, "latestDocumentVersion": 14,
  "ownerId": "…", "folderId": "…",
  "createdBy": "…", "updatedBy": "…",
  "createdAt": "…", "updatedAt": "…",
  "description": "…",
  "document": { "schemaVersion": 1, "kind": "workbook",
                "elements": [ … ], "pages": [ … ], "layout": "<?xml …" }
}
```

Everything that defines the workbook lives under `document`. `name` and
`description` sit *outside* it, alongside the other server-assigned metadata.

`documentVersion` is server-assigned and increments on each write. Do **not**
send it; the write calls below ignore it.

## Writing: verified against the live API

Confirmed on 3 Sep 2026 by creating a throwaway workbook (`ZZ Delete Me - spec
probe`, in My Documents) and updating it twice.

### Create

```
POST /v2/workbooks/spec
{ "name": "…", "folderId": "<uuid>", "document": { … } }
```

- **No `{"spec": …}` wrapper.** Sending one draws `Expecting string at 0.name`
  plus a full type dump — the wrapper hides every field from the validator.
- **`folderId` is required** and must be a UUID. There is no `workspaceId` on
  this endpoint. Get one from `GET /v2/files?typeFilters=folder` (paginate with
  the `nextPage` value from the response, not a `page` counter), or read
  `folderId` off an existing workbook's spec.
- The response is only `{"workbookId": "…"}`. `name`, `url`, `folderId` and
  `documentVersion` all come back `null` — re-fetch the workbook if you need
  them.

### Update

```
PUT /v2/workbooks/{workbookId}/spec
{ "document": { … } }
```

- **`PATCH` on this path answers 404.** The original client used PATCH, which
  is why the "update if it already exists" path could never have worked.
- The document is replaced wholesale, so read, modify, write back.
- Response: `{"success": true, "workbookId": "…"}`.

### The validator is the best documentation available

Rejections name the offending field precisely, and a deliberately empty body
(`{"spec": {}}`) returns ~61 KB describing every expected type — pages,
elements, visibility, background images, the lot. When in doubt about a field,
send something wrong on purpose and read the reply.

Two content rules found this way:

- A `text` element's `body` is markdown-flavoured. A bare `<p>` is rejected:
  `<p> carries no non-default block style or alignment; use a plain paragraph or
  # heading`. Pass plain text, `# heading`, or a `<p>` that actually carries a
  style — as the reference workbook does with `<p class="p-large">`.
- Column `formula` accepts Sigma functions, not just column references:
  `Upper([TB_SIGMA_KPI_DICTIONARY/METRIC])` round-tripped intact.

## `document.elements[]` — a flat list, not nested in pages

All 24 elements are siblings here. Nothing in an element says which page it
belongs to; the layout XML is the only thing that places it. Element type is
`kind`, not `type`.

Three kinds appear, with these key sets:

| `kind` | Keys |
|---|---|
| `text` (12) | `id`, `kind`, `body` |
| `table` (10) | `id`, `kind`, `name`, `source`, `columns`, `order`, `visibleAsSource` |
| `control` (2) | `id`, `kind`, `controlId`, `controlType`, `name`, `filters`, + per-type keys |

### `text`

One HTML string, no structured runs and no style object:

```json
{ "id": "txt_title", "kind": "text",
  "body": "<p class=\"p-large\"><span style=\"color: #1B4F72\">Centric West  Daily ecom KPI QA</span></p>" }
```

Styling is inline HTML plus Sigma's own classes (`p-large` here).

### `table`

```json
{
  "id": "tbl_calc", "kind": "table", "name": "KPI formulas",
  "source": {
    "kind": "warehouse-table",
    "connectionId": "82dc9446-…",
    "path": ["SANDBOX", "SBX_RRAJASEKAR", "TB_SIGMA_KPI_DICTIONARY"]
  },
  "columns": [
    { "id": "SECTION", "name": "Section", "formula": "[TB_SIGMA_KPI_DICTIONARY/SECTION]" }
  ],
  "order": ["SECTION", "METRIC", "FORMULA", "SOURCE_FIELD", "NOTES"],
  "visibleAsSource": false
}
```

`path` is `[database, schema, table]`. Column `formula` uses Sigma's
`[TABLE/COLUMN]` reference syntax. `order` lists column ids in display order.

**There is no `dataSources` array, and no SQL anywhere in the spec.** Every one
of the ten data elements in this workbook reads a warehouse table directly and
does its work in column formulas. `"kind": "warehouse-table"` implies other
source kinds exist, but this workbook exercises only that one, so whether a
SQL-backed source can be expressed in a spec is **unknown** — see
[What this means for `sql/`](#what-this-means-for-sql).

### `control`

Controls are elements too, and each one lists its bindings explicitly:

```json
{
  "id": "ctrl_brand", "kind": "control", "controlId": "Brand", "name": "Brand",
  "controlType": "list", "mode": "include", "selectionMode": "single",
  "value": null,
  "source": { "kind": "source",
              "source": { "kind": "table", "elementId": "tbl_glance" },
              "columnId": "BRAND_LABEL" },
  "filters": [
    { "source": { "kind": "table", "elementId": "tbl_glance" }, "columnId": "BRAND_LABEL" },
    { "source": { "kind": "table", "elementId": "tbl_kpi" },    "columnId": "BRAND_LABEL" }
  ]
}
```

`controlId` is the stable name a scheduled export pins a value to; `id` is the
element id. Observed `controlType` values: `list` and `date-range`.

- `list` takes `mode` (`include`), `selectionMode` (`single`), `value`, and a
  `source` naming the column the choices come from.
- `date-range` takes `mode` (`between`) and `includeNulls` (`always`), and no
  source — the range is entered, not picked from data.

`filters[]` is one entry per element the control drives, each naming a target
element and column. Nothing is implicit: an element the control should filter
but that is missing from this list simply is not filtered.

## `document.pages[]`

Almost nothing:

```json
{ "id": "page_vani", "name": "KPI QA", "pageWidth": "full" }
```

No element list. Pages are containers named by the layout XML.

## `document.layout` — an XML string, not an object

```xml
<?xml version="1.0" encoding="utf-8"?>
<Page type="grid" gridTemplateColumns="repeat(24, 1fr)" gridTemplateRows="auto" id="page_vani">
  <Element elementId="txt_title"  gridColumn="1 / 25" gridRow="1 / 2"/>
  <Element elementId="ctrl_brand" gridColumn="1 / 7"  gridRow="3 / 4"/>
  <Element elementId="ctrl_dates" gridColumn="7 / 16" gridRow="3 / 4"/>
  <Element elementId="tbl_calc"   gridColumn="1 / 25" gridRow="5 / 30"/>
</Page>
```

A CSS-grid layout carried as a string inside the JSON. 24 columns; rows are
implicit and an element spans as many as it needs. Positions are CSS grid line
numbers, so a full-width element is `1 / 25`, not `0 / 24`.

## How far `sigma/workbook_spec.json` is from this

The builder was written to a guessed shape. Every difference below is
structural, not a key rename:

| | Generated now | Actual |
|---|---|---|
| Root | `name`, `description`, `controls`, `dataSources`, `pages` | metadata + `document{schemaVersion, kind, elements, pages, layout}` |
| Version markers | none | `schemaVersion: 1`, `kind: "workbook"` |
| Data | `dataSources[]` of `{type:"sql", sql}` referenced by element `dataSource` | no such array; each element carries `source{kind, connectionId, path}` |
| SQL | inline, with `:brand_label` / `:report_date` | none anywhere |
| Elements | nested in `pages[].elements[]` | flat `document.elements[]` |
| Type key | `type` | `kind` |
| Columns | not modeled | `columns[]` + `order[]` + `visibleAsSource` |
| Text | `content[]` of styled runs + `style{}` | one `body` HTML string |
| Controls | top-level `controls[]` | `kind:"control"` elements with explicit `filters[]` |
| Layout | per-element `{x, y, width, height}` | one XML grid string for the page |
| Pages | hold their elements | `{id, name, pageWidth}` only |

So `build_spec.py` needs rewriting rather than correcting. The earlier note in
the README that "corrections are a single edit rather than a rewrite" was
optimistic and is no longer accurate.

### Also: the connection id is wrong

`build_spec.py` emits `0a226657-a09f-4684-9465-820374fb6c30`, the
`CENTRIC_SNOWPATH_PRD` connection. The right one for
`SANDBOX.SBX_RRAJASEKAR.*` is `82dc9446-e21c-4484-987d-79b52a490e2a` — verified
by creating a table element against `TB_SIGMA_KPI_DICTIONARY` with that
connection id and having it accepted and stored.

## What this means for `sql/`

The reference workbook points Sigma at ten pre-built `TB_SIGMA_*` tables and
holds no SQL. Our seven queries in `sql/` are the same kind of work, expressed
as SQL instead. Two ways to reconcile that:

1. **Materialize each query as a view or table in Snowflake**, then give each
   element a `warehouse-table` source pointing at it. Keeps every validated
   query as the single source of truth, and matches how the existing workbook is
   built. Needs DDL rights in a schema Sigma's connection can read.
2. **Translate the SQL into Sigma column formulas.** No Snowflake changes, but
   it reimplements logic that is already correct and tested, in a language with
   no local test path.

**Decision: option 2, column formulas.** Column `formula` does accept Sigma
functions and not just plain column references, which is what makes it viable
at all.

The risk to walk into knowingly: a column formula is evaluated *within one table
element*, and our queries are not single-table. They use CTEs, joins across
several `TB_SIGMA_*` tables, and window functions. Sigma expresses that with
joined or child elements and `Lookup()` across elements, not with a formula per
column. Expect the simple queries to port cleanly and the assembled ones —
the Demand Plan row, the promo-discount join through the in-scope order list —
to need restructuring into several elements rather than translating
line-for-line. Some may not be expressible at all, in which case a view for
those specific queries is the fallback, keeping formulas everywhere else.
