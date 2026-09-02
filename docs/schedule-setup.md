# Sending the pages as the daily email

The workbook is the email. Each page is one brand's send, so three schedules are
needed, each exporting a single page.

Record the workbook id here once it has been created:

```
workbook id: __________________   (fill in from `sigma_api.py create` output)
```

## What Sigma can and cannot send

Worth being explicit, because it shapes how the pages are built: a Sigma
schedule does **not** send hand-authored HTML. It sends the workbook, or
selected pages/elements, as a PDF or PNG attachment, with the option to embed
the rendered image inline in the message body. That is why the layout work sits
in the workbook — the page has to *be* the email, since the message body around
it is Sigma's, not ours.

So the closest thing to the mails in `reference/` is: schedule the brand's page,
attach it as PDF, and tick the option to include it inline so it opens in the
message body rather than only as an attachment.

## Per-brand schedule

Same settings three times, once per page:

| Setting | Value |
|---|---|
| Recipients | current recap list (Ramajith + Amelie) |
| Subject | `<Brand> — Daily Ecom Recap` |
| Attach | PDF, single page: the brand's page only |
| Include inline | yes, so it renders in the message body |
| Frequency | daily, weekdays only (the mails are a daily send with no weekend rollups) |
| Time | after the ADF load lands — the current mails go out on the morning refresh |
| Timezone | America/Los_Angeles (the whole pipeline is PT: `DT_PT`, "as of … PT") |

Weekdays-only matters: the footer promises "Daily send (no weekend rollups)".

The pages carry no controls, so there is nothing to set per recipient and no
need for send-as-attachment row limits.

## Schedules in code

Schedules are a separate API from the code representation — creating the
workbook from `workbook_spec.yaml` does not create them. Add them in the UI
(**Send → Schedule exports**), or via `POST /v2/workbooks/{workbookId}/schedules`
if they should be version-controlled too.

## After the pipeline catches up

The pages derive their report date per brand from the latest day in the glance
table, so they need no edit when the feed advances. The two footnotes above the
top-10 block explain the lag on the recipient's behalf: whether refunds landed
for that date, and which day the order feed is complete through.
