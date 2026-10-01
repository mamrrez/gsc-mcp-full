---
title: Home
nav_order: 1
description: Connect Google Search Console to Claude, Cursor, Windsurf or VS Code, with query grouping that is right for every language.
permalink: /
---

# gsc-mcp-full
{: .fs-9 }

A Google Search Console MCP server that understands every language.
{: .fs-6 .fw-300 }

[Set up in 10 minutes](setup){: .btn .btn-primary .fs-5 .mb-4 .mb-md-0 .mr-2 } [View on GitHub](https://github.com/mamrrez/gsc-mcp-full){: .btn .fs-5 .mb-4 .mb-md-0 }

---

## The problem it solves

Search Console counts every distinct *string* as its own query. If your visitors write Persian, Arabic, Japanese, Korean or Turkish — or just type fast — one keyword shows up as four or five rows, each looking small:

| Typed as | Rows in Search Console | Reality |
|---|---|---|
| خرید ماشین کارکرده · خريد ماشين كاركرده · خرید ماشین كاركرده | 3 | one keyword |
| エアコン · えあこん · ｴｱｺﾝ | 3 | one keyword |
| 에어컨 설치 · 에어컨설치 | 2 | one keyword |
| İstanbul klima · istanbul klima | 2 | one keyword |
| `ovdn lhadk` | a meaningless Latin query | «خرید ماشین» on the wrong keyboard layout |

**This server groups them first** — with rules that are right for each script — and every analysis (cannibalization, striking distance, brand vs non-brand, period comparisons) works on the grouped keyword.

## What else you get

- **Local days.** Search Console dates are Pacific-Time days. With hourly data (last 10 days) and your timezone, you get your *own* days.
- **History without limits.** Sync rows into a local SQLite file day by day; keep them past Google's 16 months and past the per-request cap.
- **Regex that works.** RE2's `\b` is ASCII-only, so `\bماشین\b` matches nothing. The server builds Unicode-safe patterns that match every spelling.
- **Answers, not dumps.** Compact Markdown with the analysis done, capped so a big property never floods the AI's context.
- **Read-only by default.** Nothing can be changed in Search Console until you opt in.

## Three steps

1. [Get Google credentials](setup) — an OAuth client in Google Cloud Console (free, ~5 minutes).
2. [Install and connect](install) — one command with `uvx`, then a few lines in your MCP client's config.
3. [Ask questions](usage) — example prompts and the workflows the tools were built for.

## Pages

- [1 · Google credentials](setup)
- [2 · Install & connect](install)
- [3 · First questions](usage)
- [Languages](multilingual) — every rule, and why
- [History](history) — keep your data forever
- [Tool reference](tools) — all 37 tools with parameters
- [Security](security)
- [Troubleshooting](troubleshooting)

gsc-mcp-full is a [Google Search Console MCP server](https://hasanpour.com/tools/gsc-mcp-full/) built by Mohammadreza Hasanpour.
