#!/usr/bin/env python3
"""Generate docs/tools.md from the server's own tool registry.

Run after changing any tool signature or docstring:  python scripts/gen_tools_doc.py
The page is generated so it can never drift from the code.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("GSC_CONFIG_DIR", str(ROOT / ".tmp-config"))

from gsc_mcp_full import __version__  # noqa: E402
from gsc_mcp_full.server import mcp  # noqa: E402

GROUPS = {
    "Utilities": ["get_capabilities", "reauthenticate", "build_query_regex"],
    "Properties": ["list_properties", "get_property", "add_property", "remove_property"],
    "Search analytics": ["query_search_analytics", "performance_overview", "compare_periods", "queries_for_page", "pages_for_query", "hourly_performance", "data_freshness"],
    "Multilingual": ["query_variants", "language_breakdown", "keyboard_mistypes", "top_terms"],
    "Opportunities": ["find_cannibalization", "striking_distance", "low_ctr_opportunities", "content_movers", "brand_split"],
    "History": ["sync_history", "history_status", "history_query", "history_trend", "history_compare", "history_sql"],
    "URL inspection": ["inspect_url", "inspect_urls", "indexing_summary", "inspection_quota"],
    "Sitemaps": ["list_sitemaps", "get_sitemap", "submit_sitemap", "delete_sitemap"],
}
WRITE = {"add_property", "remove_property", "submit_sitemap", "delete_sitemap"}


def _type(p: dict) -> str:
    if "type" in p:
        return p["type"]
    return "/".join(x.get("type", "") for x in p.get("anyOf", []) if x.get("type") != "null") or "any"


def main() -> None:
    tools = {t.name: t for t in mcp._tool_manager.list_tools()}
    listed = {n for names in GROUPS.values() for n in names}
    missing = set(tools) - listed
    if missing:
        raise SystemExit(f"tools not in a group: {sorted(missing)}")
    out = [
        "---", "title: Tool reference", "nav_order: 7",
        "description: Every tool with its parameters, generated from the server itself.", "---", "",
        "# Tool reference", "{: .no_toc }", "",
        f"{len(tools)} tools in gsc-mcp-full {__version__}. This page is generated from the code by `scripts/gen_tools_doc.py`.",
        "", "Tools marked **write** need `GSC_ALLOW_WRITE=1`. Every analysis tool accepts `source=\"history\"` to run on the local store.", "",
        "## Table of contents", "{: .no_toc .text-delta }", "", "1. TOC", "{:toc}", "",
    ]
    for group, names in GROUPS.items():
        out += ["---", "", f"## {group}", ""]
        for name in names:
            t = tools[name]
            desc = (t.description or "").strip()
            out.append(f"### `{name}`" + (" — write" if name in WRITE else ""))
            out += ["", desc, ""]
            props = (t.parameters or {}).get("properties", {})
            req = set((t.parameters or {}).get("required", []))
            if props:
                out += ["| Parameter | Type | Default |", "|---|---|---|"]
                for pname, p in props.items():
                    default = "**required**" if pname in req else f"`{json.dumps(p.get('default'), ensure_ascii=False)}`"
                    out.append(f"| `{pname}` | {_type(p)} | {default} |")
                out.append("")
    (ROOT / "docs" / "tools.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote docs/tools.md with {len(tools)} tools")


if __name__ == "__main__":
    main()
