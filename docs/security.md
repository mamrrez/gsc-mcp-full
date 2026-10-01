---
title: Security
nav_order: 8
description: What the server stores, what it can do, and how to keep it contained.
---

# Security

## What is on your disk

| File | What it is | Who should read it |
|---|---|---|
| `client_secret.json` (wherever you saved it) | Identifies *your app* to Google | you |
| `~/.config/gsc-mcp-full/token.json` | Your sign-in: an access token and a **refresh token** | only you — created with mode `0600` |
| `~/.config/gsc-mcp-full/history.sqlite` | Your Search Analytics rows | you |

The refresh token lets the server get new access tokens without asking you again. Anyone who copies it can read (and, if you enabled writing, change) every Search Console property your Google account can see, until you revoke it at <https://myaccount.google.com/permissions>.

## What the server can do

- **Default:** read reports, inspect URLs, list sitemaps. Scope `webmasters.readonly`.
- **With `GSC_ALLOW_WRITE=1`:** also add/remove properties and submit/delete sitemaps. Scope `webmasters`. Nothing else — the API cannot delete data, change settings or affect rankings.

Write tools check the flag on every call, so a client cannot talk its way past it.

## Where the data goes

- The server runs on your machine and talks only to `googleapis.com`. There is no hosted component, no telemetry, no analytics, no update check.
- Tool output goes to your MCP client, which sends it to whatever AI model you use. That is the same data you see in Search Console; decide whether that is acceptable for your provider as you would for pasting a report.

## Untrusted input

Query strings are typed by the public. A query can contain text like *"ignore previous instructions and …"*, and it will appear in your AI's context. The server's instructions state that query text is data, no tool executes text taken from data, and destructive actions are off unless you enabled them — so the worst case is a confused answer, not a changed property.

## Hardening checklist

- Leave `GSC_ALLOW_WRITE` unset unless you need it that day.
- Do not commit `client_secret.json`, `token.json` or `history.sqlite`; the repository's `.gitignore` covers the common names.
- Prefer a **service account restricted to specific properties** for servers and shared machines.
- If you run `--transport streamable-http`, keep it on `127.0.0.1` or behind an authenticating proxy. The server has no user authentication of its own.
- Rotate: delete `token.json` and run `gsc-mcp-full auth` to get a fresh token; revoke the old one in your Google account.

## Reporting a problem

See [SECURITY.md](https://github.com/mamrrez/gsc-mcp-full/blob/main/SECURITY.md) for private reporting.
