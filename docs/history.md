---
title: History
nav_order: 6
description: Keep Search Analytics rows locally, past Google's 16-month window and per-request cap.
---

# History
{: .no_toc }

## Table of contents
{: .no_toc .text-delta }

1. TOC
{:toc}

---

## Why

The Search Console API keeps **16 months** and returns at most 25,000 rows per request (about 50,000 rows per day in practice). Anything older is gone; anything past the cap was never yours. `sync_history` copies rows into a local SQLite file, **one day at a time**, so each day gets its own pages and the data stays as long as you keep the file.

## How syncing works

- Each day is fetched with `dataState=all` (what the UI shows) for the dimensions you choose — `query,page` by default.
- A day is marked **final** — and never fetched again — once it is older than ~3 days, Google no longer flags it as incomplete, and it actually returned rows. Newer days are **provisional** and refreshed on the next sync. A day that came back empty stays provisional for ten days, because "no rows yet" is what a processing delay looks like.
- Asking for more dimensions later (say `query,page,country,device` after `query,page`) re-fetches the stored days with the fuller set.
- From an AI client, one `sync_history` call works for about 45 seconds and reports how many days are left; ask again to continue. The command line has no such limit.
- Rows carry `qkey`, the multilingual match key, so grouping across spellings is a `GROUP BY`.
- The file is `~/.config/gsc-mcp-full/history.sqlite` (change with `GSC_DB_PATH`), created with owner-only permissions.

Ask your client: *"Sync the last 16 months of example.com into history"* — or run it yourself:

```sh
gsc-mcp-full sync example.com --days 480
gsc-mcp-full sync example.com --days 480 --dims query,page,country,device   # more detail, many more rows
```

## What the totals mean

Rows that include the query dimension leave out *anonymised* queries — searches too rare for Google to disclose. Search Console's own totals include them; a sum of query-level rows cannot. So totals from history are lower than the totals in the Performance report for the same dates, by a few percent on a large site and by much more on a small one. Trends and comparisons between periods are still sound, since both sides are measured the same way. The history tools say this under every result.

## Keep it growing (cron)

Search Console adds days; your store should too. Because finished days are skipped, a daily run is cheap:

```sh
# crontab -e  — every day at 06:00, refresh the last 7 days (covers provisional days)
0 6 * * * GSC_CREDENTIALS_PATH=$HOME/.config/gsc-mcp-full/client_secret.json $HOME/.local/bin/uvx gsc-mcp-full sync example.com --days 7 >> $HOME/.config/gsc-mcp-full/sync.log 2>&1
```

For a server without a browser use a [service account](setup#option-b--service-account-for-servers-cron-jobs-teams).

## Using it

Every analysis tool takes `source="history"` and then works for any date range:

> From history, find cannibalization on example.com between 2025-01-01 and 2025-12-31.

Dedicated tools:

| Tool | For |
|---|---|
| `history_status` | what is stored, per property and search type |
| `history_query` | rows for any range, grouped by dimensions; `query_contains` matches the multilingual key |
| `history_trend` | clicks / impressions / CTR / position per day, week or month |
| `history_compare` | two arbitrary periods — this quarter vs the same quarter two years ago |
| `history_sql` | any read-only `SELECT` |

## Schema

```sql
rows (site, search_type, date, query, qkey, page, country, device, clicks, impressions, position)
sync_days (site, search_type, date, dims, row_count, final, synced_at)
inspections (site, day, count)          -- URL Inspection quota tracking
```

Example: monthly clicks for one keyword across every spelling.

```sql
SELECT substr(date,1,7) AS month, SUM(clicks) AS clicks
FROM rows
WHERE site = 'sc-domain:example.com' AND qkey LIKE '%خرید ماشین%'
GROUP BY month ORDER BY month;
```

`qkey` holds the *standard* key (see [Languages](multilingual)); write your `LIKE` with Persian ی/ک forms and ASCII digits.

## Size

A typical mid-size site produces 5,000–30,000 `query,page` rows per day; a year is 2–10 million rows and a few hundred MB. SQLite handles that comfortably. Adding `country,device` multiplies rows by roughly 3–6×.

## BigQuery bulk export

Search Console can also export daily to BigQuery (set up in the Search Console UI, not the API). It has no row cap at all. This server does not read from BigQuery today; if you already have the export, `history_sql` on a local copy is the closest equivalent.
