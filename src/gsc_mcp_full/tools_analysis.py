"""Analysis tools: multilingual query intelligence, opportunities, movers, and the local history."""

from __future__ import annotations

from . import analysis as an
from .client import search_type_name
from .format import fmt_delta, fmt_int, fmt_pct, fmt_pos, fmt_pos_delta, md_table, metrics_line
from .i18n import find_layout_mistypes, group_queries, term_frequency
from .runtime import Runtime, guarded, hints, parse_dims
from .store import check_dims
from .sync import DEFAULT_DIMS, sync_range

READ = hints()
LOCAL_READ = hints(open_world=False)  # reads only the history file on this machine
SYNC = hints(read_only=False)  # reads from Google, writes the local history file

SYNC_BUDGET = 45.0  # seconds one sync_history call may run before handing back
HISTORY_NOTE = (
    "\n\n_History totals are sums of stored query-level rows. Google leaves anonymised (rare) queries out of "
    "those rows, so they are lower than the totals Search Console shows for the same period._"
)


def _previous(cur, compare_to: str):
    mode = (compare_to or "previous").lower()
    if mode == "year_ago":
        return cur.year_ago()
    if mode in ("52_weeks", "52weeks", "weeks_52"):
        return cur.weeks_52_ago()
    if mode == "previous":
        return cur.previous()
    raise ValueError("compare_to must be previous, year_ago or 52_weeks")


def register(mcp, rt: Runtime) -> None:  # noqa: C901
    def _rows(site: str, rng, dims: list[str], search_type: str, source: str, merge_spellings: bool = True, **filters) -> list[dict]:
        """Rows from the API, or from the local history when source='history'."""
        if source == "history":
            return rt.store().rows(
                site, rng.start_iso, rng.end_iso, search_type_name(search_type), by=check_dims(dims),
                query_contains=filters.get("query_filter"), page_contains=filters.get("page_filter"),
                country=filters.get("country"), device=filters.get("device"), limit=filters.get("max_rows", 25_000),
                merge_spellings=merge_spellings,
            )
        if source != "api":
            raise ValueError("source must be api or history")
        rows, _ = rt.fetch(site, rng, dims, search_type, **filters)
        return rows

    def _searches(site: str, rng, search_type: str, source: str, **filters) -> dict[str, int] | None:
        """Impressions per keyword counted per search (not per page), keyed by match key.

        Needed to tell sitelinks from competing pages. Only the API has it; the
        history stores per-page rows, so there the stricter fallback rule applies.
        """
        if source != "api":
            return None
        rows, _ = rt.fetch(site, rng, ["query"], search_type, **filters)
        return {g["key"]: g["impressions"] for g in group_queries(rows, "standard", rt.settings.lang)}

    def _source_note(source: str, n: int, max_rows: int) -> str:
        note = HISTORY_NOTE if source == "history" else ""
        if n >= max_rows:
            note += f"\n\n_Based on the top {max_rows:,} rows by clicks; raise max_rows to look deeper._"
        return note

    # -- multilingual --------------------------------------------------------

    @mcp.tool(annotations=READ)
    @guarded
    def query_variants(
        site_url: str,
        days: int = 28,
        start_date: str | None = None,
        end_date: str | None = None,
        search_type: str = "web",
        level: str = "standard",
        min_variants: int = 2,
        query_filter: str | None = None,
        limit: int = 30,
        source: str = "api",
        max_rows: int = 25000,
    ) -> str:
        """Keywords that Search Console splits across several spellings, with their real combined totals.

        Groups queries by a per-script match key: Persian/Arabic letter forms (ی/ي, ک/ك, ه/ة, ا/أ/إ/آ),
        half-space, vowel marks, digit scripts, kana width, case, separator punctuation — also inside mixed
        queries such as «خريد iphone 13». level=loose additionally merges spacing, accents (café/cafe),
        hiragana/katakana, Simplified/Traditional Chinese (with the zh extra). Only groups with at least
        min_variants spellings are shown. source=history uses the local store.
        """
        site = rt.site(site_url)
        rng = rt.range(days, start_date, end_date)
        rows = _rows(site, rng, ["query"], search_type, source, merge_spellings=False, query_filter=query_filter, max_rows=max_rows)
        groups = [g for g in group_queries(rows, level, rt.settings.lang) if g["variant_count"] >= min_variants]
        if not groups:
            return f"No query in {rng} has {min_variants}+ spellings at level={level} ({len(rows):,} rows checked). Try level=loose."
        hidden_imps = sum(v["impressions"] for g in groups for v in g["variants"][1:])
        out = [
            f"**{site}** · {rng} · {len(rows):,} rows → {len(groups)} keywords with {min_variants}+ spellings · level={level}",
            f"Impressions hidden in non-canonical spellings: **{fmt_int(hidden_imps)}**",
            "",
        ]
        for g in groups[:limit]:
            out.append(f"### {g['canonical']}  —  {metrics_line(g)}  ({g['variant_count']} spellings, {g['lang'] or g['script']})")
            body = [[v["query"], fmt_int(v["clicks"]), fmt_int(v["impressions"]), fmt_pos(v["position"]), ", ".join(v["differs"]) or "most seen"] for v in g["variants"][:8]]
            out.append(md_table(["spelling", "clicks", "impr", "pos", "differs from the most seen by"], body))
            out.append("")
        if len(groups) > limit:
            out.append(f"_{len(groups) - limit} more groups not shown._")
        return "\n".join(out) + _source_note(source, len(rows), max_rows)

    @mcp.tool(annotations=READ)
    @guarded
    def language_breakdown(
        site_url: str,
        days: int = 28,
        start_date: str | None = None,
        end_date: str | None = None,
        search_type: str = "web",
        source: str = "api",
        max_rows: int = 25000,
    ) -> str:
        """Share of clicks and impressions by the script/language of the query (Persian vs Arabic vs Latin…)."""
        site = rt.site(site_url)
        rng = rt.range(days, start_date, end_date)
        rows = _rows(site, rng, ["query"], search_type, source, max_rows=max_rows)
        if not rows:
            return f"No data for {site} in {rng}."
        br = an.language_breakdown(rows, rt.settings.lang)
        body = [[b["lang"], b["script"], fmt_int(b["queries"]), fmt_int(b["clicks"]), fmt_pct(b["click_share"]), fmt_int(b["impressions"]), fmt_pct(b["ctr"]), fmt_pos(b["position"]), b["example"]] for b in br]
        note = (
            "\n\n_Language is guessed from the letters used. Persian and Arabic share a script: Persian-only letters "
            "(پ چ ژ گ) mean 'fa', Arabic-only marks (ة أ إ, the article ال) mean 'ar', and a query that only shows which "
            "keyboard was used is assigned by GSC_LANG if set. '?' means nothing distinguishes it. A mixed query is "
            "counted under the script most of its letters belong to._"
        )
        return f"**{site}** · {rng} · {len(rows):,} queries\n\n" + md_table(["lang", "script", "queries", "clicks", "share", "impr", "CTR", "pos", "example"], body) + note + _source_note(source, len(rows), max_rows)

    @mcp.tool(annotations=READ)
    @guarded
    def keyboard_mistypes(
        site_url: str,
        days: int = 28,
        start_date: str | None = None,
        end_date: str | None = None,
        layouts: str = "fa,fa2,ar,ru,he",
        include_unmatched: bool = False,
        search_type: str = "web",
        source: str = "api",
        max_rows: int = 25000,
    ) -> str:
        """Queries typed with the keyboard on the wrong layout (e.g. "ovdn lhadk" = «خرید ماشین» on a Persian keyboard).

        A hit is reported only when the remapped text is a query that really appears in the data, so the
        list is precise. include_unmatched=True also lists vowel-less Latin queries that map cleanly onto a
        layout (more findings, some false positives). layouts: any of fa, fa2 (the two Persian layouts in
        common use), ar, ru, he.
        """
        site = rt.site(site_url)
        rng = rt.range(days, start_date, end_date)
        rows = _rows(site, rng, ["query"], search_type, source, merge_spellings=False, max_rows=max_rows)
        lays = [x.strip() for x in layouts.split(",") if x.strip()]
        hits = find_layout_mistypes(rows, lays, include_unmatched=include_unmatched)
        if not hits:
            return f"No wrong-layout queries found in {len(rows):,} queries ({rng}, layouts {', '.join(lays)})."
        body = [[h.query, h.intended, h.layout, h.matched_query or "(no matching query)", fmt_int(h.clicks), fmt_int(h.impressions)] for h in hits]
        total_imps = sum(h.impressions for h in hits)
        return (
            f"**{site}** · {rng} · {len(hits)} wrong-layout queries, {fmt_int(total_imps)} impressions\n\n"
            + md_table(["as typed", "meant", "layout", "matches real query", "clicks", "impr"], body, max_rows=50)
            + "\n\n_These are searches for your content that Google still matched. Nothing needs fixing on the site — but add these impressions back to the intended keyword when judging demand._"
        )

    @mcp.tool(annotations=READ)
    @guarded
    def top_terms(
        site_url: str,
        days: int = 28,
        start_date: str | None = None,
        end_date: str | None = None,
        top: int = 30,
        query_filter: str | None = None,
        search_type: str = "web",
        source: str = "api",
        max_rows: int = 25000,
    ) -> str:
        """Most demanded words across all queries — works for Chinese/Japanese/Thai (no spaces) too.

        Uses jieba / fugashi / pythainlp when installed (`pip install gsc-mcp-full[zh]` etc.), otherwise a
        script-aware fallback. Terms are merged across spellings.
        """
        site = rt.site(site_url)
        rng = rt.range(days, start_date, end_date)
        rows = _rows(site, rng, ["query"], search_type, source, query_filter=query_filter, max_rows=max_rows)
        terms, methods = term_frequency(rows, top=top, lang_hint=rt.settings.lang)
        if not terms:
            return f"No queries in {rng}."
        body = [[t["term"], fmt_int(t["queries"]), fmt_int(t["impressions"]), fmt_int(t["clicks"])] for t in terms]
        return f"**{site}** · {rng} · {len(rows):,} queries · segmentation: {', '.join(sorted(methods))}\n\n" + md_table(["term", "in queries", "impr", "clicks"], body) + _source_note(source, len(rows), max_rows)

    # -- opportunities -------------------------------------------------------

    @mcp.tool(annotations=READ)
    @guarded
    def find_cannibalization(
        site_url: str,
        days: int = 28,
        start_date: str | None = None,
        end_date: str | None = None,
        min_impressions: int = 20,
        min_share: float = 0.1,
        level: str = "standard",
        query_filter: str | None = None,
        search_type: str = "web",
        limit: int = 20,
        source: str = "api",
        max_rows: int = 25000,
    ) -> str:
        """Queries where two or more of your pages compete as separate results, ranked by impressions going to the non-best page.

        Spelling variants of a query are merged first, so «خرید ماشین» on page A and «خريد ماشين» on page B
        is caught. min_share is the impression share a page needs to count as competing.
        """
        site = rt.site(site_url)
        rng = rt.range(days, start_date, end_date)
        rows = _rows(site, rng, ["query", "page"], search_type, source, query_filter=query_filter, max_rows=max_rows)
        searches = _searches(site, rng, search_type, source, query_filter=query_filter, max_rows=max_rows) if level == "standard" else None
        groups = an.cannibalization(rows, level, rt.settings.lang, min_impressions, min_share, searches)
        if not groups:
            return f"No cannibalization found in {len(rows):,} query/page rows ({rng})."
        out = [f"**{site}** · {rng} · {len(groups)} cannibalized keywords (from {len(rows):,} rows)", ""]
        for g in groups[:limit]:
            out.append(f"### {g['query']} — {fmt_int(g['impressions'])} impr, {fmt_int(g['clicks'])} clicks, {fmt_int(g['competing_impressions'])} impr on competing pages")
            body = [[p["page"], fmt_pct(p["share"]), fmt_int(p["clicks"]), fmt_int(p["impressions"]), fmt_pos(p["position"]), ("best" if p["page"] == g["best_page"] else "") + (f" (+{p['sitelinks']} sitelinks)" if p["sitelinks"] else "")] for p in g["pages"]]
            out.append(md_table(["page", "share", "clicks", "impr", "pos", ""], body))
            out.append("")
        if len(groups) > limit:
            out.append(f"_{len(groups) - limit} more not shown._")
        out.append("_Only pages that appear as separate results are compared: `#section` links and sitelinks shown under one result are folded into their page._")
        return "\n".join(out) + _source_note(source, len(rows), max_rows)

    @mcp.tool(annotations=READ)
    @guarded
    def striking_distance(
        site_url: str,
        days: int = 28,
        start_date: str | None = None,
        end_date: str | None = None,
        min_position: float = 8,
        max_position: float = 20,
        min_impressions: int = 10,
        with_pages: bool = True,
        query_filter: str | None = None,
        search_type: str = "web",
        limit: int = 30,
        source: str = "api",
        max_rows: int = 25000,
    ) -> str:
        """Queries ranking just off page one (default positions 8–20) with real demand — the quickest wins.

        potential_clicks estimates extra clicks at position 5. Spelling variants are merged first.
        """
        site = rt.site(site_url)
        rng = rt.range(days, start_date, end_date)
        dims = ["query", "page"] if with_pages else ["query"]
        rows = _rows(site, rng, dims, search_type, source, query_filter=query_filter, max_rows=max_rows)
        searches = _searches(site, rng, search_type, source, query_filter=query_filter, max_rows=max_rows) if with_pages else None
        hits = an.striking_distance(rows, min_position, max_position, min_impressions, "standard", rt.settings.lang, searches)
        if not hits:
            return f"Nothing between positions {min_position}–{max_position} with {min_impressions}+ impressions in {rng}."
        headers = ["query"] + (["page"] if with_pages else []) + ["pos", "impr", "clicks", "CTR", "potential +clicks"]
        body = [[h["query"]] + ([h["page"]] if with_pages else []) + [fmt_pos(h["position"]), fmt_int(h["impressions"]), fmt_int(h["clicks"]), fmt_pct(h["ctr"]), fmt_int(h["potential_clicks"])] for h in hits]
        return f"**{site}** · {rng} · {len(hits)} opportunities\n\n" + md_table(headers, body, max_rows=limit) + _source_note(source, len(rows), max_rows)

    @mcp.tool(annotations=READ)
    @guarded
    def low_ctr_opportunities(
        site_url: str,
        days: int = 28,
        start_date: str | None = None,
        end_date: str | None = None,
        min_impressions: int = 100,
        ratio: float = 0.5,
        max_position: float = 10,
        query_filter: str | None = None,
        search_type: str = "web",
        limit: int = 30,
        source: str = "api",
        max_rows: int = 25000,
    ) -> str:
        """Query/page pairs on page one whose CTR is far below what their position should earn — title/snippet work.

        Expected CTR is the site's own median per position when there is enough data, otherwise a benchmark
        curve; ratio=0.5 flags rows under half the expected CTR.
        """
        site = rt.site(site_url)
        rng = rt.range(days, start_date, end_date)
        rows = _rows(site, rng, ["query", "page"], search_type, source, query_filter=query_filter, max_rows=max_rows)
        searches = _searches(site, rng, search_type, source, query_filter=query_filter, max_rows=max_rows)
        hits, method = an.low_ctr(rows, min_impressions, ratio, max_position, "standard", rt.settings.lang, searches)
        if not hits:
            return f"No low-CTR rows with {min_impressions}+ impressions on positions ≤{max_position} in {rng} ({method})."
        body = [[h["query"], h["page"], fmt_pos(h["position"]), fmt_int(h["impressions"]), fmt_pct(h["ctr"]), fmt_pct(h["expected_ctr"]), fmt_int(h["missed_clicks"])] for h in hits]
        return f"**{site}** · {rng} · {len(hits)} rows · expected CTR from the {method}\n\n" + md_table(["query", "page", "pos", "impr", "CTR", "expected", "missed clicks"], body, max_rows=limit) + _source_note(source, len(rows), max_rows)

    @mcp.tool(annotations=READ)
    @guarded
    def content_movers(
        site_url: str,
        days: int = 28,
        start_date: str | None = None,
        end_date: str | None = None,
        dimension: str = "page",
        compare_to: str = "previous",
        threshold: float = 0.3,
        min_previous_clicks: int = 10,
        search_type: str = "web",
        limit: int = 20,
        source: str = "api",
        max_rows: int = 25000,
    ) -> str:
        """Pages (or queries) that lost or gained ≥ threshold of their clicks vs an earlier period.

        compare_to: previous | year_ago (same calendar dates) | 52_weeks (weekdays aligned).
        Decayed = dropped, rising = grew, lost = had clicks before and none now, new = the opposite.
        """
        site = rt.site(site_url)
        cur = rt.range(days, start_date, end_date)
        prev = _previous(cur, compare_to)
        dim = parse_dims(dimension)[0]
        a = _rows(site, cur, [dim], search_type, source, max_rows=max_rows)
        b = _rows(site, prev, [dim], search_type, source, max_rows=max_rows)
        m = an.movers(a, b, (dim,), min_previous_clicks, threshold, "standard", rt.settings.lang)
        if source == "history":
            st = search_type_name(search_type)
            tc = rt.store().totals(site, cur.start_iso, cur.end_iso, st)
            tp = rt.store().totals(site, prev.start_iso, prev.end_iso, st)
            label = "Stored totals"
        else:
            tc, tp = rt.period_totals(site, cur, search_type), rt.period_totals(site, prev, search_type)
            label = "Site totals"
            if tc is None or tp is None:
                tc, tp, label = m["totals"]["current"], m["totals"]["previous"], "Sum of fetched rows"
        head = [f"**{site}** · {dim} · {cur} vs {prev}", f"{label}: clicks {fmt_int(tc['clicks'])} vs {fmt_int(tp['clicks'])} ({fmt_delta(tc['clicks'], tp['clicks'])})", ""]
        out = list(head)

        def _tbl(rows: list[dict], title: str) -> None:
            if not rows:
                return
            out.append(f"## {title} ({len(rows)})")
            body = [[r[dim], fmt_int(r["clicks"]), fmt_int(r["prev_clicks"]), fmt_delta(r["clicks"], r["prev_clicks"]), fmt_pos(r["position"]) if r["clicks"] else "—", fmt_pos_delta(r["position"], r["prev_position"]) if r["status"] == "both" else r["status"]] for r in rows]
            out.append(md_table([dim, "clicks", "prev", "Δ", "pos", "Δ pos"], body, max_rows=limit))
            out.append("")

        _tbl(m["decayed"], "Decayed")
        _tbl(m["lost"], "Lost entirely")
        _tbl(m["rising"], "Rising")
        _tbl(m["new"], "New")
        if len(out) == len(head):
            out.append(f"No {dim} moved by {fmt_pct(threshold, 0)} or more (min {min_previous_clicks} previous clicks).")
        return "\n".join(out) + _source_note(source, max(len(a), len(b)), max_rows)

    @mcp.tool(annotations=READ)
    @guarded
    def brand_split(
        site_url: str,
        brand_terms: str,
        days: int = 28,
        start_date: str | None = None,
        end_date: str | None = None,
        level: str = "loose",
        search_type: str = "web",
        source: str = "api",
        max_rows: int = 25000,
    ) -> str:
        """Brand vs non-brand traffic. Give the brand in every script it is searched in, comma-separated
        (e.g. "toyota, تویوتا, トヨタ"). Each term matches its spelling variants, as whole words; with
        level=loose a term of 4+ characters also matches when glued to its neighbours (toyotacamry)."""
        site = rt.site(site_url)
        rng = rt.range(days, start_date, end_date)
        rows = _rows(site, rng, ["query"], search_type, source, max_rows=max_rows)
        terms = [t.strip() for t in brand_terms.replace("،", ",").split(",") if t.strip()]
        if not terms:
            raise ValueError("brand_terms is required")
        r = an.brand_split(rows, terms, level, rt.settings.lang)
        out = [
            f"**{site}** · {rng} · brand terms: {', '.join(terms)}",
            md_table(["segment", "queries", "clicks", "impr", "CTR", "pos"], [
                ["brand", fmt_int(r["brand_queries"]), fmt_int(r["brand"]["clicks"]), fmt_int(r["brand"]["impressions"]), fmt_pct(r["brand"]["ctr"]), fmt_pos(r["brand"]["position"])],
                ["non-brand", fmt_int(r["non_brand_queries"]), fmt_int(r["non_brand"]["clicks"]), fmt_int(r["non_brand"]["impressions"]), fmt_pct(r["non_brand"]["ctr"]), fmt_pos(r["non_brand"]["position"])],
            ]),
            f"Brand share of clicks: **{fmt_pct(r['brand_click_share'])}** (of the {len(rows):,} query rows analysed; anonymised queries are in neither segment)",
        ]
        if r["top_brand"]:
            out += ["", "Top brand queries: " + ", ".join(f"{q['query']} ({fmt_int(q['clicks'])})" for q in r["top_brand"][:8])]
        return "\n".join(out) + _source_note(source, len(rows), max_rows)

    # -- history -------------------------------------------------------------

    @mcp.tool(annotations=SYNC)
    @guarded
    def sync_history(
        site_url: str,
        days: int = 90,
        start_date: str | None = None,
        end_date: str | None = None,
        search_type: str = "web",
        dimensions: str = ",".join(DEFAULT_DIMS),
        refresh_provisional: bool = True,
    ) -> str:
        """Copy Search Analytics rows into the local SQLite history, one day at a time (keeps data past 16 months).

        Days already stored and final are skipped; recent or empty days are refreshed. dimensions defaults to
        query,page; add country,device for more detail (more rows). One call works for about 45 seconds and
        then reports how many days are left — call it again to continue, or run `gsc-mcp-full sync SITE
        --days N` in a terminal (no time limit; put it in cron to keep history growing).
        """
        site = rt.site(site_url)
        rng = rt.range(days, start_date, end_date)
        dims = check_dims(dimensions.replace(";", ",").split(","))
        res = sync_range(rt.client(), rt.store(), site, rng.start, rng.end, search_type, dims, refresh_provisional=refresh_provisional, max_seconds=SYNC_BUDGET)
        st = res["search_type"]
        cov = [c for c in rt.store().coverage(site) if c.search_type == st]
        out = [f"Synced **{site}** ({st}) for {rng}: {res['days_fetched']} day(s) fetched, {fmt_int(res['rows'])} rows, dims {', '.join(dims)}."]
        if res["days_pending"]:
            out.append(f"**{res['days_pending']} day(s) still to fetch** — call sync_history again with the same arguments to continue, or run `gsc-mcp-full sync` in a terminal for the whole range at once.")
        elif res["days_fetched"] == 0:
            out.append("Nothing to fetch — every day in the range was already stored and final.")
        if cov:
            c = cov[0]
            out.append(f"History now covers {c.first} → {c.last} ({c.days} days, {fmt_int(c.rows)} rows) in {rt.settings.db_path}.")
        return "\n".join(out)

    @mcp.tool(annotations=LOCAL_READ)
    @guarded
    def history_status(site_url: str | None = None) -> str:
        """What the local history contains: per property and search type, first/last day, rows, final days."""
        site = rt.site(site_url) if site_url else None
        cov = rt.store().coverage(site)
        if not cov:
            return "No history yet. Run sync_history first."
        body = [[c.search_type, c.first, c.last, c.days, c.final_days, fmt_int(c.rows), c.dims] for c in cov]
        return md_table(["property · type" if not site else "type", "first", "last", "days", "final", "rows", "dims"], body) + f"\n\n_Store: {rt.settings.db_path}_"

    @mcp.tool(annotations=LOCAL_READ)
    @guarded
    def history_query(
        site_url: str,
        start_date: str,
        end_date: str,
        dimensions: str = "query",
        query_contains: str | None = None,
        page_contains: str | None = None,
        country: str | None = None,
        device: str | None = None,
        search_type: str = "web",
        limit: int = 50,
    ) -> str:
        """Query the local history for any date range, grouped by dimensions (queries merged across spellings).

        dimensions: query, page, country, device, date. query_contains matches the multilingual match key,
        so «ماشين» finds «ماشین» and 空调 works without spaces.
        """
        site = rt.site(site_url)
        rng = rt.range(None, start_date, end_date)
        dims = [d.lower() for d in parse_dims(dimensions)]
        bad = [d for d in dims if d not in ("query", "page", "country", "device", "date")]
        if bad:
            raise ValueError(f"history has no {', '.join(bad)} dimension; use query, page, country, device or date")
        st = search_type_name(search_type)
        flt = dict(query_contains=query_contains, page_contains=page_contains, country=country, device=device)
        store = rt.store()
        rows = store.rows(site, rng.start_iso, rng.end_iso, st, by=tuple(dims), limit=max(1, int(limit)), **flt)
        if not rows:
            return f"No stored rows for {site} in {rng}. Check history_status and sync_history."
        total = store.totals(site, rng.start_iso, rng.end_iso, st, **flt)
        groups = store.count_groups(site, rng.start_iso, rng.end_iso, st, by=tuple(dims), **flt)
        body = [[r.get(d, "") for d in dims] + [fmt_int(r["clicks"]), fmt_int(r["impressions"]), fmt_pct(r["ctr"]), fmt_pos(r["position"])] for r in rows]
        more = f"\n\n_{groups - len(rows):,} more rows not shown (of {groups:,}). Narrow the request or raise `limit`._" if groups > len(rows) else ""
        return f"**{site}** · history · {rng}\nStored totals: {metrics_line(total)}\n\n" + md_table(dims + ["clicks", "impr", "CTR", "pos"], body) + more + HISTORY_NOTE

    @mcp.tool(annotations=LOCAL_READ)
    @guarded
    def history_trend(
        site_url: str,
        start_date: str,
        end_date: str,
        granularity: str = "month",
        query_contains: str | None = None,
        page_contains: str | None = None,
        search_type: str = "web",
    ) -> str:
        """Clicks/impressions/CTR/position per day, ISO week or month from the local history — any length of time."""
        site = rt.site(site_url)
        rng = rt.range(None, start_date, end_date)
        rows = rt.store().trend(site, rng.start_iso, rng.end_iso, search_type_name(search_type), granularity, query_contains, page_contains)
        if not rows:
            return f"No stored rows for {site} in {rng}."
        body = [[r["bucket"], r["days"], fmt_int(r["clicks"]), fmt_int(r["impressions"]), fmt_pct(r["ctr"]), fmt_pos(r["position"])] for r in rows]
        return f"**{site}** · history · {rng} · by {granularity}\n\n" + md_table([granularity, "days", "clicks", "impr", "CTR", "pos"], body, max_rows=120) + "\n\n_`days` = days with data in the bucket; a partial first/last bucket is normal._" + HISTORY_NOTE

    @mcp.tool(annotations=LOCAL_READ)
    @guarded
    def history_compare(
        site_url: str,
        start_date: str,
        end_date: str,
        previous_start: str,
        previous_end: str,
        dimension: str = "query",
        search_type: str = "web",
        limit: int = 25,
    ) -> str:
        """Compare two stored periods (e.g. this quarter vs the same quarter two years ago) — beyond the API's 16 months.

        dimension: query, page, country or device.
        """
        site = rt.site(site_url)
        cur = rt.range(None, start_date, end_date)
        prev = rt.range(None, previous_start, previous_end)
        dim = check_dims([dimension])[0]
        st = search_type_name(search_type)
        store = rt.store()
        a = store.rows(site, cur.start_iso, cur.end_iso, st, by=(dim,), limit=25_000)
        b = store.rows(site, prev.start_iso, prev.end_iso, st, by=(dim,), limit=25_000)
        if not a and not b:
            return "No stored rows for either period. Check history_status."
        cmp = an.compare(a, b, (dim,), "standard", rt.settings.lang)
        tc = store.totals(site, cur.start_iso, cur.end_iso, st)
        tp = store.totals(site, prev.start_iso, prev.end_iso, st)
        out = [f"**{site}** · history · {dim}", f"Current {cur}: {metrics_line(tc)}", f"Previous {prev}: {metrics_line(tp)}", f"Clicks {fmt_delta(tc['clicks'], tp['clicks'])} · impressions {fmt_delta(tc['impressions'], tp['impressions'])}", ""]
        body = [[r[dim], fmt_int(r["clicks"]), fmt_int(r["prev_clicks"]), fmt_delta(r["clicks"], r["prev_clicks"]), fmt_pos(r["position"]) if r["clicks"] else "—", fmt_pos_delta(r["position"], r["prev_position"]) if r["status"] == "both" else r["status"]] for r in cmp["rows"]]
        return "\n".join(out) + md_table([dim, "clicks", "prev", "Δ", "pos", "Δ pos"], body, max_rows=limit) + HISTORY_NOTE

    @mcp.tool(annotations=LOCAL_READ)
    @guarded
    def history_sql(sql: str, limit: int = 100) -> str:
        """Run a read-only SELECT on the history database. Table `rows` (site, search_type, date, query, qkey, page,
        country, device, clicks, impressions, position); `sync_days`. qkey is the multilingual match key."""
        cols, data = rt.store().sql(sql, limit)
        if not data:
            return "No rows."
        return md_table(cols, [list(r) for r in data]) + (f"\n\n_Capped at {limit} rows._" if len(data) >= limit else "")
