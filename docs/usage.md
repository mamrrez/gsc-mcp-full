---
title: 3 · First questions
nav_order: 4
description: Example prompts and the workflows the tools were designed for.
---

# Step 3 — First questions
{: .no_toc }

You talk to your AI client in plain language; it picks the tools. These prompts show what the server is good at. Replace `example.com` with your property (the server accepts `example.com`, `sc-domain:example.com` or `https://example.com/`).

## Table of contents
{: .no_toc .text-delta }

1. TOC
{:toc}

---

## Start here

> List my Search Console properties.

> Give me a performance overview of example.com for the last 28 days.

> Show the last 6 months month by month.

> What are my top queries for the last 7 days, with spelling variants grouped?

## Multilingual

> Which keywords on example.com are split across several spellings? Show the real totals.

> How much of my traffic is Persian vs Arabic vs English queries?

> Find queries that were typed with the keyboard on the wrong layout.

> Build me a Search Console regex for «خرید خودرو» that matches every spelling, so I can use it in the UI filter.

> What are the most demanded words across all my Japanese queries?

## Opportunities

> Where do two of my pages compete for the same keyword? Recommend which page should win.

> Show queries ranking between position 8 and 20 with the most impressions — my quick wins.

> Which page-one queries have a much lower CTR than their position should earn? Suggest better titles.

> Which pages lost more than 30% of their clicks compared to the previous month? Which gained?

> Split traffic into brand and non-brand. Brand terms: toyota, تویوتا.

## Local time

> Show the last 24 hours, hour by hour.  *(Search Console's 24-hour view, including preliminary data)*

> Show the last 7 days as Tehran days, not Pacific days.

> Which hours of the day do I get most impressions, in Asia/Tokyo time?

## History

> Sync the last 16 months of example.com into local history.

> Compare Q3 2026 with Q3 2024 from history.  *(only possible after syncing — the API stops at 16 months)*

> From history, show monthly clicks for queries containing «پژو» over the last two years.

See [History](history) for keeping the store growing automatically.

## Indexing

> Inspect https://example.com/some-page/ — is it indexed, and what canonical did Google pick?

> Check these 20 URLs for indexing problems and list only the ones with issues.

> List my sitemaps and their errors.

## Workflows

### Weekly SEO report

1. `performance_overview` (28 days) and `compare_periods` (vs previous 28 days).
2. `content_movers` for pages that decayed or rose.
3. `striking_distance` and `low_ctr_opportunities` for this week's to-do list.
4. `query_variants` — are the numbers you are reporting the *grouped* ones?

Ask: *"Run a weekly SEO report for example.com covering these four points."*

### Migration or redesign check

1. `sync_history` before the change so the "before" is kept forever.
2. After launch: `indexing_summary` on the key URLs, `content_movers` weekly.
3. `history_compare` months later, when the API's own window has moved on.

### Multilingual audit

1. `language_breakdown` — is the language split what you expect?
2. `query_variants` with `level=loose` — the same keyword hiding in more places.
3. `keyboard_mistypes` — demand you were not counting.
4. `find_cannibalization` — pages competing across spellings that the UI cannot see.

## Reading the output

- Tables are **capped** (default 25–50 rows) and say so. Ask a narrower question or raise `limit` rather than assuming the table is complete.
- *"Data from … onward is still being collected"* means the last 2–3 days will change; compare final periods when precision matters.
- Dates are **Pacific-Time days** unless a tool says otherwise. See [hourly_performance](tools#hourly_performance).
- Position is impression-weighted when rows are merged, exactly as Search Console does it.
