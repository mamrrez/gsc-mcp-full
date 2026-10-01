---
title: Troubleshooting
nav_order: 9
description: The errors people actually hit, and the fix for each.
---

# Troubleshooting
{: .no_toc }

Run `gsc-mcp-full doctor` first — it prints the configuration it sees, tries to sign in without a browser, and lists your properties. Most problems are visible there.

## Table of contents
{: .no_toc .text-delta }

1. TOC
{:toc}

---

## `spawn uvx ENOENT` / `command not found: uvx`

The MCP client cannot find `uvx`, usually because GUI apps do not read your shell's `PATH`. Use the absolute path in `"command"`:

```sh
which uvx            # macOS/Linux — typically /Users/you/.local/bin/uvx
where uvx            # Windows     — typically C:\Users\you\.local\bin\uvx.exe
```

## `No credentials configured`

`GSC_CREDENTIALS_PATH` is not set **in the MCP client's config** (the `env` block). Setting it in your shell does not reach Claude Desktop or Cursor. Paths must be absolute; `~` is not expanded by every client.

## The browser never opens / the server hangs on first use

The OAuth flow needs a browser, and some clients start the server in a way that cannot open one. Sign in from a terminal once:

```sh
GSC_CREDENTIALS_PATH=/path/to/client_secret.json uvx gsc-mcp-full auth
```

The token is saved; the client then finds it.

## "Google hasn't verified this app"

Expected — it is *your* app from Step 1, and personal apps are not verified. Click **Advanced → Go to … (unsafe)**.

## I have to sign in again every week

Your OAuth consent screen is in **Testing** status; Google expires test-user tokens after 7 days. In Google Cloud Console → OAuth consent screen / Audience → **Publish app**. No verification is needed for your own use. Then `gsc-mcp-full auth --force`.

## `403` — "you do not have access to this property"

- Use the **exact** property URL from `list_properties`. `sc-domain:example.com` (domain property) and `https://example.com/` (URL-prefix property) are different properties with different data.
- Service account: its email must be added as a user in Search Console → Settings → Users and permissions.
- The signed-in Google account must be the one that has the property. `reauthenticate` (tool) or `gsc-mcp-full auth --force` switches accounts.

## `403` — "needs the full (write) scope"

You called a write tool with a read-only token. Set `GSC_ALLOW_WRITE=1` in the client's `env`, restart, and run `gsc-mcp-full auth --force`.

## `list_properties` is empty

- OAuth: you signed in with a different Google account than the one that owns the properties.
- Service account: it has not been added to any property (see above).

## `429` — quota exceeded

Search Analytics has generous quotas; URL Inspection does not (~2,000 per property per day, 600 per minute). `inspection_quota` shows what this server has used today. Inspect fewer URLs or wait.

## Python version errors

`uvx` picks a Python automatically. If it picks an old one: `uvx --python 3.12 gsc-mcp-full`. Python 3.10 or newer is required.

## Dates look one day off

Search Console dates are **Pacific-Time** days. For sites east of the Atlantic a "day" starts mid-morning local time. Use `hourly_performance` with `timezone=` for true local days (last 10 days only); for older data there is no way to re-cut days — every tool, in every product, has this limitation.

## Persian / Arabic text renders scrambled in tables

Mixed RTL/LTR cells confuse some clients. Set `GSC_BIDI_ISOLATE=1` and the server wraps RTL cells in Unicode isolation marks. Turn it off if your client shows them as boxes.

## The server says "N more rows not shown"

Deliberate: output is capped so a big property cannot flood the model's context. Ask a narrower question, add a filter, or raise `limit`.

## Still stuck

Open an issue with the output of `gsc-mcp-full doctor` (it never prints tokens) and the exact error: <https://github.com/mamrrez/gsc-mcp-full/issues>.
