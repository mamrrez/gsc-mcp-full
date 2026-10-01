#!/usr/bin/env python3
"""Run the server against a real Search Console property and report what works.

The unit tests use a fake Search Console. This script is the other half: it
sends real requests, so it catches what a fake cannot — a filter Google
rejects, a field named differently, a regex RE2 will not compile.

    export GSC_CREDENTIALS_PATH=~/gsc/client_secret.json
    gsc-mcp-full auth                       # once
    python scripts/live_check.py            # picks your busiest property
    python scripts/live_check.py example.com --days 28

It only reads. The write tools are never called, one URL is inspected (one of
the 2,000 daily inspections), and the history sync goes to a temporary
database that is deleted when the script ends.

Nothing is written to disk unless you ask: ``--out FILE`` saves the full tool
output. That file is your Search Console data — keep it out of any repository.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

WRITE_TOOLS = {"add_property", "remove_property", "submit_sitemap", "delete_sitemap", "reauthenticate"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("site", nargs="?", help="property to test (default: the one with the most clicks)")
    ap.add_argument("--days", type=int, default=28)
    ap.add_argument("--out", help="save the full tool output to this file (it contains your data; default: not saved)")
    args = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="gsc-live-")
    os.environ["GSC_DB_PATH"] = str(Path(tmp) / "history.sqlite")  # never touch the real history
    os.environ.pop("GSC_ALLOW_WRITE", None)
    try:
        return run(args)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)  # the synced rows are real data; do not leave them behind


def run(args: argparse.Namespace) -> int:  # noqa: C901 - a linear checklist reads best in one place

    from gsc_mcp_full import __version__
    from gsc_mcp_full.auth import AuthError
    from gsc_mcp_full.client import GSCError
    from gsc_mcp_full.i18n import group_queries
    from gsc_mcp_full.runtime import ToolError
    from gsc_mcp_full.server import mcp, rt

    results: list[tuple[str, str, str, float]] = []  # (status, name, detail, seconds)
    log: list[str] = [f"# gsc-mcp-full {__version__} live check", ""]

    def check(name: str, fn) -> object:
        t = time.monotonic()
        try:
            out = fn()
            detail, status = (out if isinstance(out, str) else "ok"), "PASS"
            if isinstance(out, tuple):
                status, detail = ("PASS" if out[0] else "FAIL"), out[1]
        except (GSCError, AuthError, ToolError, ValueError) as e:
            status, detail, out = "FAIL", f"{type(e).__name__}: {e}", None
        except Exception as e:  # anything else is a bug worth seeing in full
            status, detail, out = "FAIL", f"UNEXPECTED {type(e).__name__}: {e}", None
        results.append((status, name, str(detail)[:150], time.monotonic() - t))
        return out

    # -- sign-in and property ----------------------------------------------------
    try:
        sites = rt.sites()
    except (AuthError, GSCError) as e:
        print(f"Cannot start: {e}")
        return 2
    usable = [s["siteUrl"] for s in sites if s.get("permissionLevel") != "siteUnverifiedUser"]
    if not usable:
        print("Signed in, but this account has no verified Search Console properties.")
        return 2
    rng = rt.range(args.days, None, None)

    def clicks_of(site: str) -> int:
        try:
            t = rt.period_totals(site, rng)
            return t["clicks"] if t else 0
        except Exception:
            return 0

    site = rt.site(args.site) if args.site else max(usable, key=clicks_of)
    print(f"gsc-mcp-full {__version__} · {len(usable)} properties · testing {site} · {rng}\n")

    # -- part A: does Google accept what the server sends? ------------------------
    state: dict = {}

    def totals_vs_dates():
        t = rt.period_totals(site, rng)
        days, _ = rt.fetch(site, rng, ["date"])
        s = sum(r["clicks"] for r in days)
        state["clicks"] = t["clicks"]
        return abs(t["clicks"] - s) <= max(2, 0.01 * s), f"no-dimension totals {t['clicks']:,} clicks vs sum of days {s:,}"

    def top_rows():
        q, meta = rt.fetch(site, rng, ["query"], max_rows=5000)
        p, _ = rt.fetch(site, rng, ["page"], max_rows=50)
        c, _ = rt.fetch(site, rng, ["country"], max_rows=5)
        state.update(queries=q, pages=p, countries=c, meta=meta)
        return bool(q and p), f"{len(q):,} queries, {len(p)} pages, top country {c[0]['country'] if c else '-'}"

    def device_filter():
        rows, _ = rt.fetch(site, rng, ["device"], device="mobile")
        return [r["device"] for r in rows] == ["MOBILE"], f"device=mobile returned {[r['device'] for r in rows]}"

    def country_filter():
        c = state["countries"][0]["country"]
        t = rt.period_totals(site, rng, country=c.upper())
        return t["impressions"] > 0, f"country={c.upper()} → {t['impressions']:,} impressions"

    def query_filter():
        top = state["queries"][0]["query"]
        word = max(top.split(), key=len)
        rows, _ = rt.fetch(site, rng, ["query"], query_filter=word.upper(), max_rows=500)
        return any(r["query"] == top for r in rows), f"filter on {len(word)}-letter word (upper-cased) → {len(rows)} rows, includes the top query"

    def page_filters():
        page = state["pages"][0]["page"]
        exact, _ = rt.fetch(site, rng, ["query"], page_exact=page, max_rows=50)
        excl = rt.period_totals(site, rng, page_filter_exclude=page)
        return bool(exact) and excl["clicks"] < state["clicks"], f"page_exact → {len(exact)} queries; excluding it leaves {excl['clicks']:,} of {state['clicks']:,} clicks"

    def hourly():
        rows, meta = rt.fetch(site, rt.range(3, None, None, lag=0), ["hour"])
        return bool(rows), f"{len(rows)} hourly rows, first incomplete hour: {meta.get('firstIncompleteHour', 'none')}"

    def other_types():
        notes = []
        for st in ("image", "video", "news", "discover", "googleNews"):
            rows, _ = rt.fetch(site, rng, ["date"], st)
            notes.append(f"{st}:{sum(r['clicks'] for r in rows)}")
        return True, "clicks by search type — " + ", ".join(notes)

    def appearance_and_final():
        a, _ = rt.fetch(site, rng, ["searchAppearance"])
        f, _ = rt.fetch(site, rng, ["date"], data_state="final")
        return True, f"{len(a)} search appearances; data_state=final returned {len(f)} days"

    def grouping_conserves():
        q = state["queries"]
        g = group_queries(q, "standard", rt.settings.lang)
        same = sum(x["clicks"] for x in g) == sum(r["clicks"] for r in q) and sum(x["impressions"] for x in g) == sum(r["impressions"] for r in q)
        merged = sum(1 for x in g if x["variant_count"] > 1)
        hidden = sum(v["impressions"] for x in g for v in x["variants"][1:])
        return same, f"{len(q):,} queries → {len(g):,} keywords; {merged} had spelling variants hiding {hidden:,} impressions; sums unchanged"

    for name, fn in [
        ("totals request matches the daily sum", totals_vs_dates),
        ("query / page / country dimensions", top_rows),
        ("device filter", device_filter),
        ("country filter", country_filter),
        ("multilingual query filter (real RE2)", query_filter),
        ("exact and exclude page filters", page_filters),
        ("hourly data", hourly),
        ("image, video, news, Discover, Google News", other_types),
        ("searchAppearance dimension and final data", appearance_and_final),
        ("grouping keeps clicks and impressions", grouping_conserves),
    ]:
        check("API · " + name, fn)

    # -- part B: every read-only tool, for real -----------------------------------
    pages = state.get("pages") or []
    queries = state.get("queries") or []
    page = pages[0]["page"] if pages else site
    query = queries[0]["query"] if queries else "test"
    r3 = rt.range(3, None, None)
    tool_args = {
        "get_capabilities": {}, "list_properties": {}, "get_property": {"site_url": site},
        "build_query_regex": {"term": query},
        "query_search_analytics": {"site_url": site, "days": args.days, "dimensions": "query,page", "group_variants": False},
        "performance_overview": {"site_url": site, "days": args.days},
        "compare_periods": {"site_url": site, "days": args.days},
        "queries_for_page": {"site_url": site, "page_url": page, "days": args.days},
        "pages_for_query": {"site_url": site, "query": query, "days": args.days},
        "hourly_performance": {"site_url": site, "hours": 24},
        "data_freshness": {"site_url": site},
        "query_variants": {"site_url": site, "days": args.days},
        "language_breakdown": {"site_url": site, "days": args.days},
        "keyboard_mistypes": {"site_url": site, "days": args.days},
        "top_terms": {"site_url": site, "days": args.days},
        "find_cannibalization": {"site_url": site, "days": args.days},
        "striking_distance": {"site_url": site, "days": args.days},
        "low_ctr_opportunities": {"site_url": site, "days": args.days},
        "content_movers": {"site_url": site, "days": args.days},
        "brand_split": {"site_url": site, "brand_terms": query.split()[0], "days": args.days},
        "list_sitemaps": {"site_url": site},
        "inspect_url": {"site_url": site, "page_url": page},
        "inspection_quota": {"site_url": site},
        "sync_history": {"site_url": site, "days": 3},
        "history_status": {"site_url": site},
        "history_query": {"site_url": site, "start_date": r3.start_iso, "end_date": r3.end_iso},
        "history_trend": {"site_url": site, "start_date": r3.start_iso, "end_date": r3.end_iso, "granularity": "day"},
        "history_sql": {"sql": "SELECT COUNT(*) AS rows, COUNT(DISTINCT qkey) AS keywords FROM rows"},
    }
    skipped = {"inspect_urls", "indexing_summary", "get_sitemap", "history_compare"}  # same code paths as the ones above

    def run_tool(name: str, kwargs: dict):
        def go():
            res = asyncio.run(mcp.call_tool(name, kwargs))
            text = "\n".join(getattr(c, "text", "") for c in res.content)
            log.extend([f"## {name}", "", text, ""])
            first = next((ln for ln in text.splitlines() if ln.strip()), "")
            return True, f"{len(text):,} chars · {first[:95]}"

        check("tool · " + name, go)

    registered = {t.name for t in mcp._tool_manager.list_tools()}
    for name, kwargs in tool_args.items():
        run_tool(name, kwargs)
    untested = registered - set(tool_args) - WRITE_TOOLS - skipped

    # -- report -------------------------------------------------------------------
    width = max(len(n) for _, n, _, _ in results)
    for status, name, detail, secs in results:
        print(f"{status}  {name:<{width}}  {secs:5.1f}s  {detail}")
    failed = [r for r in results if r[0] == "FAIL"]
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed" + (f" · not exercised: {', '.join(sorted(untested))}" if untested else ""))
    print(f"write tools not called: {', '.join(sorted(WRITE_TOOLS))}")
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(log), encoding="utf-8")
        print(f"full tool output saved (your data — keep it private): {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
