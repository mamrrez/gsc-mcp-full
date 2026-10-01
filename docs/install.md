---
title: 2 · Install & connect
nav_order: 3
description: Install with uvx, sign in once, and add the server to Claude Desktop, Claude Code, Cursor, Windsurf, VS Code or Codex.
---

# Step 2 — Install & connect
{: .no_toc }

## Table of contents
{: .no_toc .text-delta }

1. TOC
{:toc}

---

## Install `uv`

The server is a Python package; `uv` runs it in its own isolated environment with one command and no Python setup.

```sh
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Open a new terminal and check `uvx --version`. Note the full path of `uvx` (`which uvx` / `where uvx`) — GUI apps like Claude Desktop often need the absolute path.

## Sign in once

```sh
export GSC_CREDENTIALS_PATH=~/.config/gsc-mcp-full/client_secret.json   # from Step 1
uvx gsc-mcp-full auth
```

A browser tab opens; choose the Google account that has your Search Console properties. If you see *"Google hasn't verified this app"*, click **Advanced → Go to … (unsafe)** — it is your own app from Step 1. The token is saved to `~/.config/gsc-mcp-full/token.json` with owner-only permissions.

Then confirm everything works:

```sh
uvx gsc-mcp-full doctor
```

You should see your properties listed. If not, see [Troubleshooting](troubleshooting).

{: .tip }
Prefer pip? `pip install gsc-mcp-full` installs the same `gsc-mcp-full` command; use it as the `command` in the configs below, with no `args`.

## Connect your MCP client

All clients need the same three things: the command (`uvx`), its arguments, and the environment variables. Replace the paths with yours. `GSC_TIMEZONE` and `GSC_LANG` are optional but make local-day and language features better.

### Claude Desktop

Edit the config file — **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json` · **Windows:** `%APPDATA%\Claude\claude_desktop_config.json` (Claude → Settings → Developer → Edit Config opens it).

```json
{
  "mcpServers": {
    "search-console": {
      "command": "/Users/you/.local/bin/uvx",
      "args": ["gsc-mcp-full"],
      "env": {
        "GSC_CREDENTIALS_PATH": "/Users/you/.config/gsc-mcp-full/client_secret.json",
        "GSC_TIMEZONE": "Asia/Tehran",
        "GSC_LANG": "fa"
      }
    }
  }
}
```

Restart Claude Desktop. The 🔌 tools icon should list `search-console`.

### Claude Code

```sh
claude mcp add search-console \
  -e GSC_CREDENTIALS_PATH=/Users/you/.config/gsc-mcp-full/client_secret.json \
  -e GSC_TIMEZONE=Asia/Tehran -e GSC_LANG=fa \
  -- uvx gsc-mcp-full
```

Add `--scope user` to make it available in every project. Check with `claude mcp list`.

### Cursor

Create `~/.cursor/mcp.json` (global) or `.cursor/mcp.json` (per project) with exactly the Claude Desktop JSON above.

### Windsurf

`~/.codeium/windsurf/mcp_config.json` — same JSON shape as Claude Desktop.

### VS Code (Copilot agent mode)

`.vscode/mcp.json` in your workspace (or *MCP: Add Server* from the command palette):

```json
{
  "servers": {
    "search-console": {
      "type": "stdio",
      "command": "uvx",
      "args": ["gsc-mcp-full"],
      "env": {
        "GSC_CREDENTIALS_PATH": "/Users/you/.config/gsc-mcp-full/client_secret.json",
        "GSC_TIMEZONE": "Asia/Tehran"
      }
    }
  }
}
```

### OpenAI Codex CLI

`~/.codex/config.toml`:

```toml
[mcp_servers.search-console]
command = "uvx"
args = ["gsc-mcp-full"]

[mcp_servers.search-console.env]
GSC_CREDENTIALS_PATH = "/Users/you/.config/gsc-mcp-full/client_secret.json"
```

### Any client, over HTTP

For a client on another machine, or one that only speaks HTTP:

```sh
gsc-mcp-full serve --transport streamable-http --host 127.0.0.1 --port 8000
```

The endpoint is `http://127.0.0.1:8000/mcp`. Put it behind an authenticated reverse proxy before exposing it beyond localhost — the server itself has no user authentication.

By default the server answers only requests addressed to `localhost` (protection against DNS-rebinding attacks), so a proxy forwarding `Host: mcp.example.com` gets `421 Misdirected Request`. Name the public host to let it through — the protection stays on for every other host:

```sh
GSC_ALLOWED_HOSTS=mcp.example.com gsc-mcp-full serve --transport streamable-http --host 0.0.0.0 --port 8000
```

## Enable write tools (optional)

Add `"GSC_ALLOW_WRITE": "1"` to the `env` block, then run `gsc-mcp-full auth --force` once so the token is re-issued with the full scope. `add_property`, `remove_property`, `submit_sitemap` and `delete_sitemap` then work.

## Language extras (optional)

Chinese, Japanese and Thai queries have no spaces. `top_terms` uses a real segmenter when it is installed:

```sh
uvx --from "gsc-mcp-full[zh]" gsc-mcp-full   # jieba + OpenCC
# or [ja] (fugashi + unidic-lite), [th] (pythainlp), [all]
```

Without them a script-aware fallback is used, so nothing breaks — results are just rougher.

## Next

[Step 3 — First questions](usage) shows what to ask.
