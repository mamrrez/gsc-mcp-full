---
title: Tool reference
nav_order: 7
description: Every tool with its parameters, generated from the server itself.
---

# Tool reference
{: .no_toc }

37 tools in gsc-mcp-full 0.2.2. This page is generated from the code by `scripts/gen_tools_doc.py`.

Tools marked **write** need `GSC_ALLOW_WRITE=1`. Every analysis tool accepts `source="history"` to run on the local store.

## Table of contents
{: .no_toc .text-delta }

1. TOC
{:toc}

---

## Utilities

### `get_capabilities`

Auth status, scope, write access, history coverage and the list of tools. Call this first when unsure.

### `reauthenticate`

Forget the cached client and sign in again (switch Google accounts or scopes).

### `build_query_regex`

Build a Search Console regex for a term that works in any script and matches its common spellings.

        Use the result as query_regex in other tools or paste it into the Search Console UI
        (regex filter). RE2's \b is ASCII-only, so this uses Unicode-safe boundaries; Arabic
        script gets ی/ي, ک/ك, ه/ة, ا/أ/إ/آ classes with optional vowel marks and half-spaces;
        digits match Persian, Arabic-Indic and full-width forms; Cyrillic е/ё; case-insensitive.
        loose=True also lets words run together. Accent and kana variants are not covered.

| Parameter | Type | Default |
|---|---|---|
| `term` | string | **required** |
| `whole_word` | boolean | `true` |
| `loose` | boolean | `false` |

---

## Properties

### `list_properties`

List every Search Console property this account can see, with the permission level.

### `get_property`

Details of one property (exact URL and permission level). Accepts loose input like example.com.

| Parameter | Type | Default |
|---|---|---|
| `site_url` | string | **required** |

### `add_property` — write

Add a property to this account (needs GSC_ALLOW_WRITE=1). Verification still happens in Search Console.

| Parameter | Type | Default |
|---|---|---|
| `site_url` | string | **required** |

### `remove_property` — write

Remove a property from this account (needs GSC_ALLOW_WRITE=1). Data is not deleted at Google.

| Parameter | Type | Default |
|---|---|---|
| `site_url` | string | **required** |

---

## Search analytics

### `query_search_analytics`

Search Analytics rows with any dimensions and filters. The general-purpose query tool.

        Args:
            site_url: property (sc-domain:example.com, https://example.com/ or just example.com).
            days / start_date / end_date: range; explicit dates (YYYY-MM-DD) win over days.
            dimensions: comma list of query, page, country, device, date, searchAppearance, hour.
            search_type: web, image, video, news, discover, googleNews.
            query_filter: a term in ANY language; case-insensitive, and matches its common spellings
                (ی/ي, ک/ك, half-space, vowel marks, Persian/Arabic digits, е/ё).
            query_regex / query_regex_exclude: raw RE2 regex (see build_query_regex for a safe one).
            page_filter: substring of the page URL; page_exact: the exact URL; page_filter_exclude: substring to
                leave out; page_regex: RE2 regex on the URL.
            country: ISO-3166-1 alpha-3 (IRN, USA…); device: DESKTOP, MOBILE, TABLET.
            data_state: all (matches the UI, default) or final.
            group_variants: merge spelling variants of the same query (only when dimensions=query).
            level: standard or loose grouping (loose also merges spacing and accent differences).
            sort_by: clicks, impressions, ctr, position — applied to the fetched rows; Google itself always
                returns the top rows by clicks. limit: rows shown. max_rows: rows fetched.

| Parameter | Type | Default |
|---|---|---|
| `site_url` | string | **required** |
| `days` | integer | `28` |
| `start_date` | string | `null` |
| `end_date` | string | `null` |
| `dimensions` | string | `"query"` |
| `search_type` | string | `"web"` |
| `query_filter` | string | `null` |
| `query_regex` | string | `null` |
| `query_regex_exclude` | string | `null` |
| `page_filter` | string | `null` |
| `page_exact` | string | `null` |
| `page_filter_exclude` | string | `null` |
| `page_regex` | string | `null` |
| `country` | string | `null` |
| `device` | string | `null` |
| `search_appearance` | string | `null` |
| `data_state` | string | `null` |
| `group_variants` | boolean | `false` |
| `level` | string | `"standard"` |
| `sort_by` | string | `"clicks"` |
| `limit` | integer | `50` |
| `max_rows` | integer | `5000` |

### `performance_overview`

One-screen summary: totals, trend, top queries and pages, devices, countries, and how fresh the data is.

        granularity: day, week, month or auto — the same choice as the Performance report's time-granularity
        menu (for hourly, use hourly_performance). auto picks day up to 31 days, week up to six months, then month.

| Parameter | Type | Default |
|---|---|---|
| `site_url` | string | **required** |
| `days` | integer | `28` |
| `start_date` | string | `null` |
| `end_date` | string | `null` |
| `search_type` | string | `"web"` |
| `granularity` | string | `"auto"` |
| `top` | integer | `10` |

### `compare_periods`

Compare a period with an earlier one; biggest movers first.

        compare_to: previous (the same number of days just before) | year_ago (the same calendar dates last
        year) | 52_weeks (364 days back, weekdays aligned) | custom (give previous_start and previous_end).
        dimension: query, page, country, device or searchAppearance. Queries are matched across spellings.

| Parameter | Type | Default |
|---|---|---|
| `site_url` | string | **required** |
| `days` | integer | `28` |
| `start_date` | string | `null` |
| `end_date` | string | `null` |
| `compare_to` | string | `"previous"` |
| `previous_start` | string | `null` |
| `previous_end` | string | `null` |
| `dimension` | string | `"query"` |
| `search_type` | string | `"web"` |
| `query_filter` | string | `null` |
| `page_filter` | string | `null` |
| `level` | string | `"standard"` |
| `limit` | integer | `25` |

### `queries_for_page`

Which queries send traffic to one page. Spelling variants are merged unless group_variants=False.

        Give the exact page URL. If nothing matches exactly, pages whose URL contains the text are used
        instead and listed, so a path such as /blog/ works too.

| Parameter | Type | Default |
|---|---|---|
| `site_url` | string | **required** |
| `page_url` | string | **required** |
| `days` | integer | `28` |
| `start_date` | string | `null` |
| `end_date` | string | `null` |
| `search_type` | string | `"web"` |
| `group_variants` | boolean | `true` |
| `level` | string | `"standard"` |
| `limit` | integer | `50` |

### `pages_for_query`

Which pages rank for one query — in each of its spellings — and how the impressions split between them.

| Parameter | Type | Default |
|---|---|---|
| `site_url` | string | **required** |
| `query` | string | **required** |
| `days` | integer | `28` |
| `start_date` | string | `null` |
| `end_date` | string | `null` |
| `search_type` | string | `"web"` |
| `level` | string | `"standard"` |
| `limit` | integer | `25` |

### `hourly_performance`

Hourly data for the last 10 days — Search Console's 24-hour view, and the only way to get true LOCAL days.

        hours=24 reproduces the Performance report's 24-hour view: the most recent 24 hourly points,
        including preliminary ones. Otherwise the last `days` (max 10) are returned. Search Console's daily
        numbers are Pacific-Time days; with timezone= (e.g. Asia/Tehran, Asia/Tokyo) the hours are re-cut
        into local days (by=day) or listed per local hour (by=hour).

| Parameter | Type | Default |
|---|---|---|
| `site_url` | string | **required** |
| `days` | integer | `7` |
| `hours` | integer | `null` |
| `timezone` | string | `null` |
| `by` | string | `"day"` |
| `search_type` | string | `"web"` |
| `query_filter` | string | `null` |
| `page_filter` | string | `null` |

### `data_freshness`

Which recent days are final and which are still changing, for daily and hourly data.

| Parameter | Type | Default |
|---|---|---|
| `site_url` | string | **required** |
| `search_type` | string | `"web"` |

---

## Multilingual

### `query_variants`

Keywords that Search Console splits across several spellings, with their real combined totals.

        Groups queries by a per-script match key: Persian/Arabic letter forms (ی/ي, ک/ك, ه/ة, ا/أ/إ/آ),
        half-space, vowel marks, digit scripts, kana width, case, separator punctuation — also inside mixed
        queries such as «خريد iphone 13». level=loose additionally merges spacing, accents (café/cafe),
        hiragana/katakana, Simplified/Traditional Chinese (with the zh extra). Only groups with at least
        min_variants spellings are shown. source=history uses the local store.

| Parameter | Type | Default |
|---|---|---|
| `site_url` | string | **required** |
| `days` | integer | `28` |
| `start_date` | string | `null` |
| `end_date` | string | `null` |
| `search_type` | string | `"web"` |
| `level` | string | `"standard"` |
| `min_variants` | integer | `2` |
| `query_filter` | string | `null` |
| `limit` | integer | `30` |
| `source` | string | `"api"` |
| `max_rows` | integer | `25000` |

### `language_breakdown`

Share of clicks and impressions by the script/language of the query (Persian vs Arabic vs Latin…).

| Parameter | Type | Default |
|---|---|---|
| `site_url` | string | **required** |
| `days` | integer | `28` |
| `start_date` | string | `null` |
| `end_date` | string | `null` |
| `search_type` | string | `"web"` |
| `source` | string | `"api"` |
| `max_rows` | integer | `25000` |

### `keyboard_mistypes`

Queries typed with the keyboard on the wrong layout (e.g. "ovdn lhadk" = «خرید ماشین» on a Persian keyboard).

        A hit is reported only when the remapped text is a query that really appears in the data, so the
        list is precise. include_unmatched=True also lists vowel-less Latin queries that map cleanly onto a
        layout (more findings, some false positives). layouts: any of fa, fa2 (the two Persian layouts in
        common use), ar, ru, he.

| Parameter | Type | Default |
|---|---|---|
| `site_url` | string | **required** |
| `days` | integer | `28` |
| `start_date` | string | `null` |
| `end_date` | string | `null` |
| `layouts` | string | `"fa,fa2,ar,ru,he"` |
| `include_unmatched` | boolean | `false` |
| `search_type` | string | `"web"` |
| `source` | string | `"api"` |
| `max_rows` | integer | `25000` |

### `top_terms`

Most demanded words across all queries — works for Chinese/Japanese/Thai (no spaces) too.

        Uses jieba / fugashi / pythainlp when installed (`pip install gsc-mcp-full[zh]` etc.), otherwise a
        script-aware fallback. Terms are merged across spellings.

| Parameter | Type | Default |
|---|---|---|
| `site_url` | string | **required** |
| `days` | integer | `28` |
| `start_date` | string | `null` |
| `end_date` | string | `null` |
| `top` | integer | `30` |
| `query_filter` | string | `null` |
| `search_type` | string | `"web"` |
| `source` | string | `"api"` |
| `max_rows` | integer | `25000` |

---

## Opportunities

### `find_cannibalization`

Queries where two or more of your pages compete as separate results, ranked by impressions going to the non-best page.

        Spelling variants of a query are merged first, so «خرید ماشین» on page A and «خريد ماشين» on page B
        is caught. min_share is the impression share a page needs to count as competing.

| Parameter | Type | Default |
|---|---|---|
| `site_url` | string | **required** |
| `days` | integer | `28` |
| `start_date` | string | `null` |
| `end_date` | string | `null` |
| `min_impressions` | integer | `20` |
| `min_share` | number | `0.1` |
| `level` | string | `"standard"` |
| `query_filter` | string | `null` |
| `search_type` | string | `"web"` |
| `limit` | integer | `20` |
| `source` | string | `"api"` |
| `max_rows` | integer | `25000` |

### `striking_distance`

Queries ranking just off page one (default positions 8–20) with real demand — the quickest wins.

        potential_clicks estimates extra clicks at position 5. Spelling variants are merged first.

| Parameter | Type | Default |
|---|---|---|
| `site_url` | string | **required** |
| `days` | integer | `28` |
| `start_date` | string | `null` |
| `end_date` | string | `null` |
| `min_position` | number | `8` |
| `max_position` | number | `20` |
| `min_impressions` | integer | `10` |
| `with_pages` | boolean | `true` |
| `query_filter` | string | `null` |
| `search_type` | string | `"web"` |
| `limit` | integer | `30` |
| `source` | string | `"api"` |
| `max_rows` | integer | `25000` |

### `low_ctr_opportunities`

Query/page pairs on page one whose CTR is far below what their position should earn — title/snippet work.

        Expected CTR is the site's own median per position when there is enough data, otherwise a benchmark
        curve; ratio=0.5 flags rows under half the expected CTR.

| Parameter | Type | Default |
|---|---|---|
| `site_url` | string | **required** |
| `days` | integer | `28` |
| `start_date` | string | `null` |
| `end_date` | string | `null` |
| `min_impressions` | integer | `100` |
| `ratio` | number | `0.5` |
| `max_position` | number | `10` |
| `query_filter` | string | `null` |
| `search_type` | string | `"web"` |
| `limit` | integer | `30` |
| `source` | string | `"api"` |
| `max_rows` | integer | `25000` |

### `content_movers`

Pages (or queries) that lost or gained ≥ threshold of their clicks vs an earlier period.

        compare_to: previous | year_ago (same calendar dates) | 52_weeks (weekdays aligned).
        Decayed = dropped, rising = grew, lost = had clicks before and none now, new = the opposite.

| Parameter | Type | Default |
|---|---|---|
| `site_url` | string | **required** |
| `days` | integer | `28` |
| `start_date` | string | `null` |
| `end_date` | string | `null` |
| `dimension` | string | `"page"` |
| `compare_to` | string | `"previous"` |
| `threshold` | number | `0.3` |
| `min_previous_clicks` | integer | `10` |
| `search_type` | string | `"web"` |
| `limit` | integer | `20` |
| `source` | string | `"api"` |
| `max_rows` | integer | `25000` |

### `brand_split`

Brand vs non-brand traffic. Give the brand in every script it is searched in, comma-separated
        (e.g. "toyota, تویوتا, トヨタ"). Each term matches its spelling variants, as whole words; with
        level=loose a term of 4+ characters also matches when glued to its neighbours (toyotacamry).

| Parameter | Type | Default |
|---|---|---|
| `site_url` | string | **required** |
| `brand_terms` | string | **required** |
| `days` | integer | `28` |
| `start_date` | string | `null` |
| `end_date` | string | `null` |
| `level` | string | `"loose"` |
| `search_type` | string | `"web"` |
| `source` | string | `"api"` |
| `max_rows` | integer | `25000` |

---

## History

### `sync_history`

Copy Search Analytics rows into the local SQLite history, one day at a time (keeps data past 16 months).

        Days already stored and final are skipped; recent or empty days are refreshed. dimensions defaults to
        query,page; add country,device for more detail (more rows). One call works for about 45 seconds and
        then reports how many days are left — call it again to continue, or run `gsc-mcp-full sync SITE
        --days N` in a terminal (no time limit; put it in cron to keep history growing).

| Parameter | Type | Default |
|---|---|---|
| `site_url` | string | **required** |
| `days` | integer | `90` |
| `start_date` | string | `null` |
| `end_date` | string | `null` |
| `search_type` | string | `"web"` |
| `dimensions` | string | `"query,page"` |
| `refresh_provisional` | boolean | `true` |

### `history_status`

What the local history contains: per property and search type, first/last day, rows, final days.

| Parameter | Type | Default |
|---|---|---|
| `site_url` | string | `null` |

### `history_query`

Query the local history for any date range, grouped by dimensions (queries merged across spellings).

        dimensions: query, page, country, device, date. query_contains matches the multilingual match key,
        so «ماشين» finds «ماشین» and 空调 works without spaces.

| Parameter | Type | Default |
|---|---|---|
| `site_url` | string | **required** |
| `start_date` | string | **required** |
| `end_date` | string | **required** |
| `dimensions` | string | `"query"` |
| `query_contains` | string | `null` |
| `page_contains` | string | `null` |
| `country` | string | `null` |
| `device` | string | `null` |
| `search_type` | string | `"web"` |
| `limit` | integer | `50` |

### `history_trend`

Clicks/impressions/CTR/position per day, ISO week or month from the local history — any length of time.

| Parameter | Type | Default |
|---|---|---|
| `site_url` | string | **required** |
| `start_date` | string | **required** |
| `end_date` | string | **required** |
| `granularity` | string | `"month"` |
| `query_contains` | string | `null` |
| `page_contains` | string | `null` |
| `search_type` | string | `"web"` |

### `history_compare`

Compare two stored periods (e.g. this quarter vs the same quarter two years ago) — beyond the API's 16 months.

        dimension: query, page, country or device.

| Parameter | Type | Default |
|---|---|---|
| `site_url` | string | **required** |
| `start_date` | string | **required** |
| `end_date` | string | **required** |
| `previous_start` | string | **required** |
| `previous_end` | string | **required** |
| `dimension` | string | `"query"` |
| `search_type` | string | `"web"` |
| `limit` | integer | `25` |

### `history_sql`

Run a read-only SELECT on the history database. Table `rows` (site, search_type, date, query, qkey, page,
        country, device, clicks, impressions, position); `sync_days`. qkey is the multilingual match key.

| Parameter | Type | Default |
|---|---|---|
| `sql` | string | **required** |
| `limit` | integer | `100` |

---

## URL inspection

### `inspect_url`

Full URL Inspection for one page: index verdict, crawl, canonical, robots, sitemaps, rich results, mobile.

| Parameter | Type | Default |
|---|---|---|
| `site_url` | string | **required** |
| `page_url` | string | **required** |
| `language` | string | `"en-US"` |

### `inspect_urls`

Inspect up to 50 URLs in parallel (comma- or newline-separated). Quota is checked first.

        Columns: `index` is the indexing verdict, `rich results` the structured-data verdict — a page can
        PASS one and FAIL the other. URLs not reached within the time budget are marked and can be re-sent.

| Parameter | Type | Default |
|---|---|---|
| `site_url` | string | **required** |
| `urls` | string | **required** |
| `concurrency` | integer | `8` |
| `language` | string | `"en-US"` |

### `indexing_summary`

Problems only: which of the given URLs are not indexed or have structured-data failures, and why. Up to 50 URLs.

| Parameter | Type | Default |
|---|---|---|
| `site_url` | string | **required** |
| `urls` | string | **required** |
| `concurrency` | integer | `8` |
| `language` | string | `"en-US"` |

### `inspection_quota`

How many URL inspections this server has used today for a property (Google allows ~2,000/day).

| Parameter | Type | Default |
|---|---|---|
| `site_url` | string | **required** |

---

## Sitemaps

### `list_sitemaps`

Sitemaps submitted for a property, with errors/warnings and URL counts. Pass sitemap_index to list its children.

| Parameter | Type | Default |
|---|---|---|
| `site_url` | string | **required** |
| `sitemap_index` | string | `null` |

### `get_sitemap`

Details of one sitemap: submission/download dates, errors, warnings, per-type URL counts.

| Parameter | Type | Default |
|---|---|---|
| `site_url` | string | **required** |
| `sitemap_url` | string | **required** |

### `submit_sitemap` — write

Submit (or resubmit) a sitemap URL (needs GSC_ALLOW_WRITE=1).

| Parameter | Type | Default |
|---|---|---|
| `site_url` | string | **required** |
| `sitemap_url` | string | **required** |

### `delete_sitemap` — write

Remove a sitemap from Search Console (needs GSC_ALLOW_WRITE=1). The file itself is untouched.

| Parameter | Type | Default |
|---|---|---|
| `site_url` | string | **required** |
| `sitemap_url` | string | **required** |

