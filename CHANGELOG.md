# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.2.1] — 2026-10-01

### Added
- `scripts/live_check.py` — a read-only, end-to-end check of every tool against one of your own properties.

### Changed
- Per-page analysis counts a page once. Google lists `#section` links and the sitelinks under a result as
  separate pages; `find_cannibalization`, `low_ctr_opportunities`, `striking_distance` and `pages_for_query`
  now fold them into their page, so only pages that appear as separate results are compared.
- `keyboard_mistypes` maps the punctuation keys that type letters on Persian, Arabic, Russian and Hebrew layouts.
- `query_variants` shows how each spelling differs from the most-seen one.
- `top_terms` leaves out bare numbers.
- An OAuth client of type "Web application" is recognised and explained before sign-in starts.

## [0.2.0] — 2026-10-01

### Added
- `hourly_performance(hours=24)` — Search Console's 24-hour view, including preliminary hours.
- `performance_overview(granularity=day|week|month)` — the report's time-granularity choice.
- `compare_periods` and `content_movers`: `compare_to=52_weeks`, alongside `previous`, `year_ago` and custom dates.
- `query_search_analytics`: `page_exact` and `page_filter_exclude` filters.
- Tool annotations (`readOnlyHint`, `destructiveHint`) on all 37 tools, so clients can tell a read from a write.
- `GSC_ALLOWED_HOSTS` for running HTTP mode behind a reverse proxy; `GSC_USE_ADC` for cloud identities.
- A second Persian keyboard layout (`fa2`) for `keyboard_mistypes`.
- Time budgets for URL-inspection batches and history syncs, with a report of what is left to do.
- Multilingual grouping inside mixed-script queries («خرید bmw x5»), and a case-insensitive `query_filter` for every script.

### Changed
- Tool failures are reported as tool errors (`isError`) with the reason in the message.
- Report headers show the totals for the period; history totals cover every stored row.
- Page URLs are always shown in full.
- `year_ago` compares the same calendar dates; use `52_weeks` to keep weekdays aligned.
- `inspect_urls` shows separate `index` and `rich results` verdicts; `indexing_summary` includes structured-data failures.
- Punctuation that carries meaning is kept when grouping (`c++`, `c#`, `.net`, `3.5`).
- Weekly trends use ISO weeks; hourly buckets show the exact local time in `:30` and `:45` timezones.
- Application Default Credentials are used only when configured.

## [0.1.0] — 2026-09-30

First release.

### Added
- 37 tools over the full Search Console API (properties, search analytics, sitemaps, URL inspection).
- Multilingual query grouping: per-script match keys for Arabic-script languages (Persian, Arabic, Urdu, Pashto), Chinese, Japanese, Korean, Thai, Indic scripts, Hebrew, Greek, Cyrillic and Latin-script languages incl. Turkish and Vietnamese; `standard` and `loose` levels.
- `query_variants`, `language_breakdown`, `keyboard_mistypes` (wrong keyboard layout detection for fa/ar/ru/he), `top_terms` (CJK/Thai segmentation with optional extras), `build_query_regex` (Unicode-safe RE2 patterns).
- Analysis tools: `find_cannibalization`, `striking_distance`, `low_ctr_opportunities`, `content_movers`, `brand_split`, `compare_periods`.
- Hourly data (`hourly_performance`) with local-day re-bucketing by IANA timezone; `data_freshness`.
- Local SQLite history (`sync_history`, `history_*` tools, read-only `history_sql`) for ranges beyond Google's 16 months.
- Concurrent, quota-tracked URL inspection (`inspect_urls`, `indexing_summary`).
- Read-only OAuth scope by default; write tools behind `GSC_ALLOW_WRITE`; service-account and ADC support; `0600` token file.
- CLI: `auth`, `doctor`, `sync`, `tools`, `serve --transport streamable-http`.
- Built on MCP Python SDK 2.x with a 1.x fallback.
