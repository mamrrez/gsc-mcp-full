"""``gsc-mcp-full`` — serve (default), auth, doctor, sync, tools."""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from datetime import date, timedelta

from . import __version__


def _utf8_stdout() -> None:
    """Property names and tool docs contain non-ASCII text; a cp1252 console would crash on them."""
    with contextlib.suppress(Exception):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]


def _serve(args: argparse.Namespace) -> int:
    from .server import run

    run(transport=args.transport, host=args.host, port=args.port)
    return 0


def _auth(args: argparse.Namespace) -> int:
    from .auth import AuthError, credential_kind, load_credentials
    from .settings import Settings

    st = Settings.from_env()
    try:
        kind = credential_kind(st.credentials_path)
        load_credentials(st, interactive=True, force_login=args.force)
    except AuthError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if kind == "service_account":
        print(f"OK — service account, scope '{st.scope}'. No sign-in or token file is needed.")
    else:
        print(f"OK — signed in, scope '{st.scope}'. Token: {st.token_path}")
    return 0


def _doctor(args: argparse.Namespace) -> int:
    from .auth import AuthError, auth_status, load_credentials
    from .client import GSCClient, GSCError
    from .settings import Settings

    _utf8_stdout()
    st = Settings.from_env()
    print(f"gsc-mcp-full {__version__} · python {sys.version.split()[0]}")
    for k, v in auth_status(st).items():
        print(f"  {k}: {v}")
    print(f"  data_state: {st.data_state}\n  timezone: {st.timezone or '(unset)'}\n  db: {st.db_path}")
    try:
        creds = load_credentials(st, interactive=False)
        sites = GSCClient(creds).sites_list()
    except AuthError as e:
        print(f"\nNOT READY: {e}")
        return 2
    except GSCError as e:
        print(f"\nAPI call failed: {e}")
        return 3
    print(f"\nOK — {len(sites)} properties:")
    for s in sorted(sites, key=lambda s: s.get("siteUrl", "")):
        print(f"  {s.get('siteUrl')}  ({s.get('permissionLevel')})")
    return 0


def _sync(args: argparse.Namespace) -> int:
    from .auth import AuthError, load_credentials
    from .client import GSCClient, GSCError, resolve_site
    from .dates import today_pacific
    from .settings import Settings
    from .store import HistoryStore
    from .sync import sync_range

    _utf8_stdout()
    try:
        st = Settings.from_env()
        client = GSCClient(load_credentials(st, interactive=False))
        site = resolve_site(client.sites_list(), args.site) or args.site
        # Search Console days are Pacific days; "yesterday" must be Pacific yesterday.
        end = date.fromisoformat(args.end) if args.end else today_pacific() - timedelta(days=1)
        start = date.fromisoformat(args.start) if args.start else end - timedelta(days=args.days - 1)
        if start > end:
            raise ValueError(f"start {start} is after end {end}")
        dims = [d.strip() for d in args.dims.split(",") if d.strip()]
        res = sync_range(client, HistoryStore(st.db_path), site, start, end, args.type, dims, progress=lambda m: print("  " + m))
    except (AuthError, GSCError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(json.dumps({"site": site, **res}, ensure_ascii=False))
    return 0


def _tools(args: argparse.Namespace) -> int:
    """Print every tool as Markdown — the docs page is generated from this."""
    from .server import mcp

    _utf8_stdout()
    tools = mcp._tool_manager.list_tools()
    print("| Tool | What it does |\n|---|---|")
    for t in sorted(tools, key=lambda t: t.name):
        first = (t.description or "").strip().splitlines()[0]
        print(f"| `{t.name}` | {first} |")
    if not args.brief:
        for t in sorted(tools, key=lambda t: t.name):
            print(f"\n### `{t.name}`\n")
            print((t.description or "").strip())
            props = (t.parameters or {}).get("properties", {})
            req = set((t.parameters or {}).get("required", []))
            if props:
                print("\n| Parameter | Type | Default |\n|---|---|---|")
                for name, p in props.items():
                    typ = p.get("type") or "/".join(x.get("type", "") for x in p.get("anyOf", []) if x.get("type") != "null") or "any"
                    default = "required" if name in req else json.dumps(p.get("default"), ensure_ascii=False)
                    print(f"| `{name}` | {typ} | {default} |")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="gsc-mcp-full", description="Google Search Console MCP server that understands every language.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("serve", help="run the MCP server (default)")
    s.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(fn=_serve)

    a = sub.add_parser("auth", help="sign in with Google in the browser and store the token")
    a.add_argument("--force", action="store_true", help="ignore an existing token and sign in again")
    a.set_defaults(fn=_auth)

    d = sub.add_parser("doctor", help="check configuration, credentials and API access")
    d.set_defaults(fn=_doctor)

    y = sub.add_parser("sync", help="pull Search Analytics rows into the local history")
    y.add_argument("site")
    y.add_argument("--days", type=int, default=30)
    y.add_argument("--start")
    y.add_argument("--end")
    y.add_argument("--type", default="web")
    y.add_argument("--dims", default="query,page")
    y.set_defaults(fn=_sync)

    t = sub.add_parser("tools", help="print the tool reference as Markdown")
    t.add_argument("--brief", action="store_true")
    t.set_defaults(fn=_tools)

    argv = list(sys.argv[1:] if argv is None else argv)
    # `serve` is the default: `gsc-mcp-full` and `gsc-mcp-full --transport …` both run the server.
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help", "--version")):
        argv = ["serve", *argv]
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
