"""Core tools: properties, search analytics, hourly data, sitemaps, URL inspection, utilities."""

from __future__ import annotations

from . import __version__
from .analysis import collapse_pages, compare, totals
from .auth import AuthError, auth_status
from .client import GSCError
from .dates import bucket_hours, local_day_note
from .format import fmt_delta, fmt_int, fmt_pct, fmt_pos, fmt_pos_delta, kv, md_table, metrics_line
from .i18n import api_regex, group_queries, match_key
from .inspection import DAILY_QUOTA, canonical_mismatch, inspect_many, rich_results_failing, utc_day
from .runtime import Runtime, guarded, hints, parse_dims
from .store import bucket_days

READ = hints()
LOCAL = hints(read_only=False, open_world=False)  # changes only files on this machine
WRITE = hints(read_only=False)
DESTRUCTIVE = hints(read_only=False, destructive=True)


def _metric_cols(r: dict) -> list:
    return [fmt_int(r["clicks"]), fmt_int(r["impressions"]), fmt_pct(r["ctr"]), fmt_pos(r["position"])]


def _rows_table(rows: list[dict], dims: list[str], limit: int) -> str:
    headers = list(dims) + ["clicks", "impr", "CTR", "pos"]
    body = [[r.get(d, "") for d in dims] + _metric_cols(r) for r in rows]
    return md_table(headers, body, max_rows=limit)


def _sort(rows: list[dict], sort_by: str) -> list[dict]:
    key = (sort_by or "clicks").lower()
    if key not in ("clicks", "impressions", "ctr", "position"):
        raise ValueError("sort_by must be clicks, impressions, ctr or position")
    return sorted(rows, key=lambda r: r.get(key, 0), reverse=(key != "position"))


def _freshness_note(meta: dict) -> str:
    fi = meta.get("firstIncompleteDate") or meta.get("firstIncompleteHour")
    return f"\n\n_Data from {fi} onward is still being collected and will change._" if fi else ""


def _totals_line(real: dict | None, rows: list[dict]) -> str:
    """Period totals when Google gave them; otherwise an honestly labelled sum."""
    if real is not None:
        return "Period totals: " + metrics_line(real)
    return f"Sum of the {len(rows):,} rows fetched (not the period total): " + metrics_line(totals(rows))


def _split_urls(urls: str) -> list[str]:
    return [u.strip() for u in urls.replace(",", "\n").splitlines() if u.strip()]


def _tool_names(mcp) -> list[str]:
    try:
        return sorted(t.name for t in mcp._tool_manager.list_tools())
    except Exception:  # SDK internals moved; capabilities must still answer
        return []


def register(mcp, rt: Runtime) -> None:  # noqa: C901 - one registration function is clearer than 20 modules
    # -- utilities -----------------------------------------------------------

    @mcp.tool(annotations=READ)
    @guarded
    def get_capabilities() -> str:
        """Auth status, scope, write access, history coverage and the list of tools. Call this first when unsure."""
        st = rt.settings
        status = auth_status(st)
        lines = [f"# gsc-mcp-full {__version__}", "", "## Auth", kv(status.items()), ""]
        try:
            sites = rt.sites()
            lines.append(f"Signed in; {len(sites)} properties visible (use list_properties).")
        except (AuthError, GSCError) as e:
            lines.append(f"Not signed in: {e}")
        lines += ["", "## Settings", kv([("data_state", st.data_state), ("timezone", st.timezone or "(not set — pass timezone= to hourly tools)"), ("lang hint", st.lang or "(auto)"), ("history db", str(st.db_path))])]
        try:
            cov = rt.store().coverage()
            if cov:
                lines += ["", "## History coverage", md_table(["property · type", "first", "last", "days", "rows"], [[c.search_type, c.first, c.last, c.days, fmt_int(c.rows)] for c in cov])]
            else:
                lines.append("\nNo history synced yet — sync_history stores rows locally for ranges beyond 16 months.")
        except Exception as e:  # the store must never break capabilities
            lines.append(f"\nHistory store unavailable: {e}")
        lines += ["", "## Tools", ", ".join(_tool_names(mcp)) or "(ask your client to list the tools)"]
        return "\n".join(lines)

    @mcp.tool(annotations=LOCAL)
    @guarded
    def reauthenticate() -> str:
        """Forget the cached client and sign in again (switch Google accounts or scopes)."""
        from .auth import load_credentials

        rt.reset()
        load_credentials(rt.settings, interactive=True, force_login=True)
        rt.reset()
        return f"Signed in again with scope '{rt.settings.scope}'. Token: {rt.settings.token_path}"

    @mcp.tool(annotations=hints(open_world=False))
    @guarded
    def build_query_regex(term: str, whole_word: bool = True, loose: bool = False) -> str:
        """Build a Search Console regex for a term that works in any script and matches its common spellings.

        Use the result as query_regex in other tools or paste it into the Search Console UI
        (regex filter). RE2's \\b is ASCII-only, so this uses Unicode-safe boundaries; Arabic
        script gets ی/ي, ک/ك, ه/ة, ا/أ/إ/آ classes with optional vowel marks and half-spaces;
        digits match Persian, Arabic-Indic and full-width forms; Cyrillic е/ё; case-insensitive.
        loose=True also lets words run together. Accent and kana variants are not covered.
        """
        return f"`{api_regex(term, whole_word=whole_word, loose=loose)}`"

    # -- properties ----------------------------------------------------------

    @mcp.tool(annotations=READ)
    @guarded
    def list_properties() -> str:
        """List every Search Console property this account can see, with the permission level."""
        sites = rt.sites(max_age=0)
        if not sites:
            return "This account has no Search Console properties (or the service account was not added as a user)."
        rows = [[s.get("siteUrl"), s.get("permissionLevel", "")] for s in sorted(sites, key=lambda s: s.get("siteUrl", ""))]
        return md_table(["property", "permission"], rows)

    @mcp.tool(annotations=READ)
    @guarded
    def get_property(site_url: str) -> str:
        """Details of one property (exact URL and permission level). Accepts loose input like example.com."""
        site = rt.site(site_url)
        d = rt.client().site_get(site)
        return kv([("property", d.get("siteUrl")), ("permission", d.get("permissionLevel"))])

    @mcp.tool(annotations=WRITE)
    @guarded
    def add_property(site_url: str) -> str:
        """Add a property to this account (needs GSC_ALLOW_WRITE=1). Verification still happens in Search Console."""
        rt.require_write()
        rt.client().site_add(site_url.strip())
        rt.reset()
        return f"Added {site_url}. It will show as unverified until you verify ownership in Search Console."

    @mcp.tool(annotations=DESTRUCTIVE)
    @guarded
    def remove_property(site_url: str) -> str:
        """Remove a property from this account (needs GSC_ALLOW_WRITE=1). Data is not deleted at Google."""
        rt.require_write()
        site = rt.site(site_url)
        rt.client().site_delete(site)
        rt.reset()
        return f"Removed {site} from this account."

    # -- search analytics ----------------------------------------------------

    @mcp.tool(annotations=READ)
    @guarded
    def query_search_analytics(
        site_url: str,
        days: int = 28,
        start_date: str | None = None,
        end_date: str | None = None,
        dimensions: str = "query",
        search_type: str = "web",
        query_filter: str | None = None,
        query_regex: str | None = None,
        query_regex_exclude: str | None = None,
        page_filter: str | None = None,
        page_exact: str | None = None,
        page_filter_exclude: str | None = None,
        page_regex: str | None = None,
        country: str | None = None,
        device: str | None = None,
        search_appearance: str | None = None,
        data_state: str | None = None,
        group_variants: bool = False,
        level: str = "standard",
        sort_by: str = "clicks",
        limit: int = 50,
        max_rows: int = 5000,
    ) -> str:
        """Search Analytics rows with any dimensions and filters. The general-purpose query tool.

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
        """
        site = rt.site(site_url)
        rng = rt.range(days, start_date, end_date)
        dims = parse_dims(dimensions)
        flt = dict(
            query_filter=query_filter, query_regex=query_regex, query_regex_exclude=query_regex_exclude,
            page_filter=page_filter, page_exact=page_exact, page_filter_exclude=page_filter_exclude, page_regex=page_regex,
            country=country, device=device, search_appearance=search_appearance, data_state=data_state,
        )
        rows, meta = rt.fetch(site, rng, dims, search_type, max_rows=max_rows, **flt)
        head = f"**{site}** · {rng} · {search_type} · {len(rows):,} rows fetched"
        if not rows:
            return head + "\n\nNo data for this range/filter."
        notes = ""
        if len(rows) >= max_rows:
            notes += f"\n\n_Only the top {max_rows:,} rows by clicks were fetched; raise max_rows for more._"
            if (sort_by or "clicks").lower() != "clicks":
                notes += f" _The {sort_by} sort is within those rows — rows outside Google's top {max_rows:,} by clicks are not in it._"
        head += "\n" + _totals_line(rt.period_totals(site, rng, search_type, **flt), rows)
        if group_variants and dims == ["query"]:
            groups = group_queries(rows, level, rt.settings.lang)
            merged = sum(1 for g in groups if g["variant_count"] > 1)
            body = [[g["canonical"], g["variant_count"], fmt_int(g["clicks"]), fmt_int(g["impressions"]), fmt_pct(g["ctr"]), fmt_pos(g["position"])] for g in _sort(groups, sort_by)]
            head += f"\n{len(groups):,} distinct queries after grouping ({merged} had spelling variants)"
            return head + "\n\n" + md_table(["query", "variants", "clicks", "impr", "CTR", "pos"], body, max_rows=limit) + notes + _freshness_note(meta)
        return head + "\n\n" + _rows_table(_sort(rows, sort_by), dims, limit) + notes + _freshness_note(meta)

    @mcp.tool(annotations=READ)
    @guarded
    def performance_overview(
        site_url: str,
        days: int = 28,
        start_date: str | None = None,
        end_date: str | None = None,
        search_type: str = "web",
        granularity: str = "auto",
        top: int = 10,
    ) -> str:
        """One-screen summary: totals, trend, top queries and pages, devices, countries, and how fresh the data is.

        granularity: day, week, month or auto — the same choice as the Performance report's time-granularity
        menu (for hourly, use hourly_performance). auto picks day up to 31 days, week up to six months, then month.
        """
        site = rt.site(site_url)
        rng = rt.range(days, start_date, end_date)
        g = (granularity or "auto").lower()
        if g == "auto":
            g = "day" if rng.days <= 31 else "week" if rng.days <= 190 else "month"
        if g not in ("day", "week", "month"):
            raise ValueError("granularity must be auto, day, week or month (use hourly_performance for hours)")
        by_date, meta = rt.fetch(site, rng, ["date"], search_type)
        out = [f"# {site} · {rng} · {search_type}", "Period totals: " + metrics_line(totals(by_date)), ""]
        if by_date:
            trend = [[b["bucket"]] + _metric_cols(b) + ([b["days"]] if g != "day" else []) for b in bucket_days(by_date, g)]
            out += [f"## By {g}", md_table([g, "clicks", "impr", "CTR", "pos"] + (["days"] if g != "day" else []), trend, max_rows=62)]

        def section(title: str, dim: str, n: int) -> None:
            # Discover and Google News do not offer every dimension; skip a section rather than fail the overview.
            try:
                rows, _ = rt.fetch(site, rng, [dim], search_type, max_rows=n)
            except GSCError:
                out.extend(["", f"_{title}: not available for search type {search_type}._"])
                return
            if rows:
                out.extend(["", f"## {title}", _rows_table(rows, [dim], n)])

        section(f"Top {top} queries", "query", top)
        section(f"Top {top} pages", "page", top)
        section("Devices", "device", 3)
        section("Countries", "country", 8)
        out.append(_freshness_note(meta) or "\n_All days in this range are final._")
        out.append(local_day_note(rt.settings.timezone))
        return "\n".join(out)

    @mcp.tool(annotations=READ)
    @guarded
    def compare_periods(
        site_url: str,
        days: int = 28,
        start_date: str | None = None,
        end_date: str | None = None,
        compare_to: str = "previous",
        previous_start: str | None = None,
        previous_end: str | None = None,
        dimension: str = "query",
        search_type: str = "web",
        query_filter: str | None = None,
        page_filter: str | None = None,
        level: str = "standard",
        limit: int = 25,
    ) -> str:
        """Compare a period with an earlier one; biggest movers first.

        compare_to: previous (the same number of days just before) | year_ago (the same calendar dates last
        year) | 52_weeks (364 days back, weekdays aligned) | custom (give previous_start and previous_end).
        dimension: query, page, country, device or searchAppearance. Queries are matched across spellings.
        """
        site = rt.site(site_url)
        cur = rt.range(days, start_date, end_date)
        mode = "custom" if (previous_start or previous_end) else (compare_to or "previous").lower()
        if mode == "custom":
            if not (previous_start and previous_end):
                raise ValueError("compare_to=custom needs both previous_start and previous_end (YYYY-MM-DD)")
            prev = rt.range(None, previous_start, previous_end)
        elif mode == "year_ago":
            prev = cur.year_ago()
        elif mode in ("52_weeks", "52weeks", "weeks_52"):
            prev = cur.weeks_52_ago()
        elif mode == "previous":
            prev = cur.previous()
        else:
            raise ValueError("compare_to must be previous, year_ago, 52_weeks or custom")
        dim = parse_dims(dimension)[0]
        flt = dict(query_filter=query_filter, page_filter=page_filter)
        a, meta = rt.fetch(site, cur, [dim], search_type, **flt)
        b, _ = rt.fetch(site, prev, [dim], search_type, **flt)
        cmp = compare(a, b, (dim,), level, rt.settings.lang)
        tc, tp = rt.period_totals(site, cur, search_type, **flt), rt.period_totals(site, prev, search_type, **flt)
        label = "totals"
        if tc is None or tp is None:
            tc, tp, label = cmp["totals"]["current"], cmp["totals"]["previous"], "sum of fetched rows"
        out = [
            f"# {site} · {dim} · {search_type}",
            f"Current ({label}): {cur} — {metrics_line(tc)}",
            f"Previous ({label}): {prev} — {metrics_line(tp)}",
            f"Change: clicks {fmt_delta(tc['clicks'], tp['clicks'])} · impressions {fmt_delta(tc['impressions'], tp['impressions'])} · "
            f"CTR {fmt_delta(tc['ctr'], tp['ctr'])} · position {fmt_pos_delta(tc['position'], tp['position'])}",
            "",
        ]
        rows = []
        for r in cmp["rows"]:
            rows.append([
                r[dim],
                fmt_int(r["clicks"]), fmt_int(r["prev_clicks"]), fmt_delta(r["clicks"], r["prev_clicks"]),
                fmt_int(r["impressions"]), fmt_delta(r["impressions"], r["prev_impressions"]),
                fmt_pos(r["position"]) if r["status"] != "lost" else "—",
                fmt_pos_delta(r["position"], r["prev_position"]) if r["status"] == "both" else r["status"],
            ])
        out.append(md_table([dim, "clicks", "prev", "Δ clicks", "impr", "Δ impr", "pos", "Δ pos"], rows, max_rows=limit))
        return "\n".join(out) + _freshness_note(meta)

    @mcp.tool(annotations=READ)
    @guarded
    def queries_for_page(
        site_url: str,
        page_url: str,
        days: int = 28,
        start_date: str | None = None,
        end_date: str | None = None,
        search_type: str = "web",
        group_variants: bool = True,
        level: str = "standard",
        limit: int = 50,
    ) -> str:
        """Which queries send traffic to one page. Spelling variants are merged unless group_variants=False.

        Give the exact page URL. If nothing matches exactly, pages whose URL contains the text are used
        instead and listed, so a path such as /blog/ works too.
        """
        site = rt.site(site_url)
        rng = rt.range(days, start_date, end_date)
        page = page_url.strip()
        rows, meta = rt.fetch(site, rng, ["query"], search_type, page_exact=page)
        if rows:
            head = f"**{site}** · {rng} · page {page}\n" + _totals_line(rt.period_totals(site, rng, search_type, page_exact=page), rows)
        else:
            both, meta = rt.fetch(site, rng, ["page", "query"], search_type, page_filter=page)
            if not both:
                return f"No queries for {page} in {rng}. Check the exact URL (with/without trailing slash, http/https)."
            pages = sorted({r["page"] for r in both})
            rows = both
            head = (
                f"**{site}** · {rng} · no page is exactly {page}; showing the {len(pages)} page(s) whose URL contains it: "
                f"{', '.join(pages[:5])}{' …' if len(pages) > 5 else ''}\n" + _totals_line(rt.period_totals(site, rng, search_type, page_filter=page), rows)
            )
        if group_variants:
            groups = group_queries(rows, level, rt.settings.lang)
            body = [[g["canonical"], g["variant_count"], fmt_int(g["clicks"]), fmt_int(g["impressions"]), fmt_pct(g["ctr"]), fmt_pos(g["position"])] for g in groups]
            return head + "\n\n" + md_table(["query", "variants", "clicks", "impr", "CTR", "pos"], body, max_rows=limit) + _freshness_note(meta)
        return head + "\n\n" + _rows_table(_sort(rows, "clicks"), ["query"], limit) + _freshness_note(meta)

    @mcp.tool(annotations=READ)
    @guarded
    def pages_for_query(
        site_url: str,
        query: str,
        days: int = 28,
        start_date: str | None = None,
        end_date: str | None = None,
        search_type: str = "web",
        level: str = "standard",
        limit: int = 25,
    ) -> str:
        """Which pages rank for one query — in each of its spellings — and how the impressions split between them."""
        site = rt.site(site_url)
        rng = rt.range(days, start_date, end_date)
        rows, meta = rt.fetch(site, rng, ["query", "page"], search_type, query_filter=query)
        key = match_key(query, level, rt.settings.lang)
        mine = [r for r in rows if match_key(r["query"], level, rt.settings.lang) == key]
        if not mine:
            similar = sorted({r["query"] for r in rows})[:10]
            return f"No page ranks for «{query}» in {rng}." + (f" Queries containing it: {', '.join(similar)}" if similar else "")
        spellings = sorted({r["query"] for r in mine}, key=lambda q: -sum(r["impressions"] for r in mine if r["query"] == q))
        per_search, _ = rt.fetch(site, rng, ["query"], search_type, query_filter=query)
        searches = sum(r["impressions"] for r in per_search if match_key(r["query"], level, rt.settings.lang) == key)
        hits = collapse_pages(mine, level, rt.settings.lang, {key: searches} if searches else None)
        head = f"**{site}** · «{query}» · {rng} · {len(spellings)} spelling(s): {', '.join(spellings[:8])}"
        if searches:
            head += f"\nSearches that showed the site for this keyword: {fmt_int(searches)}"
        body = [[h["page"], fmt_int(h["clicks"]), fmt_int(h["impressions"]), fmt_pct(h["ctr"]), fmt_pos(h["position"]), f"+{h['sitelinks']} sitelinks" if h["sitelinks"] else ""] for h in hits]
        note = "\n\n_One row per page that appears as its own result; `#section` links and sitelinks are folded into their page (their clicks are included)._"
        return head + "\n\n" + md_table(["page", "clicks", "impr", "CTR", "pos", ""], body, max_rows=limit) + note + _freshness_note(meta)

    @mcp.tool(annotations=READ)
    @guarded
    def hourly_performance(
        site_url: str,
        days: int = 7,
        hours: int | None = None,
        timezone: str | None = None,
        by: str = "day",
        search_type: str = "web",
        query_filter: str | None = None,
        page_filter: str | None = None,
    ) -> str:
        """Hourly data for the last 10 days — Search Console's 24-hour view, and the only way to get true LOCAL days.

        hours=24 reproduces the Performance report's 24-hour view: the most recent 24 hourly points,
        including preliminary ones. Otherwise the last `days` (max 10) are returned. Search Console's daily
        numbers are Pacific-Time days; with timezone= (e.g. Asia/Tehran, Asia/Tokyo) the hours are re-cut
        into local days (by=day) or listed per local hour (by=hour).
        """
        site = rt.site(site_url)
        if hours is not None:
            hours = max(1, min(int(hours), 240))
            days, by = min(10, hours // 24 + 2), "hour"
        days = max(1, min(int(days), 10))
        if by not in ("day", "hour"):
            raise ValueError("by must be day or hour")
        rng = rt.range(days, None, None, lag=0)  # hourly data runs up to the current hour
        tz = timezone or rt.settings.timezone or "America/Los_Angeles"
        rows, meta = rt.fetch(site, rng, ["hour"], search_type, query_filter=query_filter, page_filter=page_filter, max_rows=25_000)
        if not rows:
            return f"No hourly data for {site} in the last {days} days (hourly data covers only the last 10 days)."
        api_rows = [{"keys": [r["hour"]], "clicks": r["clicks"], "impressions": r["impressions"], "position": r["position"]} for r in rows]
        buckets = bucket_hours(api_rows, tz, by=by)
        if hours is not None:
            buckets = buckets[-hours:]
            span = f"last {len(buckets)} hours"
        else:
            span = f"last {days} days"
        body = [[b["bucket"], fmt_int(b["clicks"]), fmt_int(b["impressions"]), fmt_pct(b["ctr"]), fmt_pos(b["position"])] for b in buckets]
        head = f"**{site}** · {span} · by local {by} in **{tz}**\n" + metrics_line(totals(buckets))
        note = ""
        if meta.get("firstIncompleteHour"):
            note += f"\n\n_Hours from {meta['firstIncompleteHour']} onward are preliminary and will change._"
        if by == "day":
            note += "\n\n_The first and last local day are partial because the API window is cut on Pacific hours. In a zone on a :30 or :45 offset a local day here runs from 00:30 (or 00:45), since Google's hours start on the Pacific hour._"
        return head + "\n\n" + md_table([by, "clicks", "impr", "CTR", "pos"], body, max_rows=24 * 10) + note

    @mcp.tool(annotations=READ)
    @guarded
    def data_freshness(site_url: str, search_type: str = "web") -> str:
        """Which recent days are final and which are still changing, for daily and hourly data."""
        site = rt.site(site_url)
        rng = rt.range(10, None, None, lag=0)
        rows, meta = rt.fetch(site, rng, ["date"], search_type, data_state="all")
        last = max((r["date"] for r in rows), default=None)
        lines = [f"**{site}** · {search_type}", kv([
            ("latest day with data", last or "none in the last 10 days"),
            ("first incomplete day", meta.get("firstIncompleteDate") or "none reported — all returned days final"),
        ])]
        try:
            hrows, hmeta = rt.fetch(site, rt.range(2, None, None, lag=0), ["hour"], search_type)
            lines.append(kv([("latest hour with data", max((r["hour"] for r in hrows), default="none")), ("first incomplete hour", hmeta.get("firstIncompleteHour") or "none reported")]))
        except GSCError as e:
            lines.append(f"hourly: {e}")
        lines.append(local_day_note(rt.settings.timezone))
        return "\n".join(lines)

    # -- sitemaps ------------------------------------------------------------

    def _sitemap_row(s: dict) -> list:
        contents = s.get("contents") or []
        submitted = sum(int(c.get("submitted", 0) or 0) for c in contents)
        types = ",".join(sorted({c.get("type", "") for c in contents})) or ""
        return [
            s.get("path", ""),
            "index" if s.get("isSitemapsIndex") else types or "sitemap",
            (s.get("lastSubmitted") or "")[:10],
            (s.get("lastDownloaded") or "")[:10],
            fmt_int(submitted),
            s.get("errors", 0),
            s.get("warnings", 0),
            "pending" if s.get("isPending") else "",
        ]

    @mcp.tool(annotations=READ)
    @guarded
    def list_sitemaps(site_url: str, sitemap_index: str | None = None) -> str:
        """Sitemaps submitted for a property, with errors/warnings and URL counts. Pass sitemap_index to list its children."""
        site = rt.site(site_url)
        maps = rt.client().sitemaps_list(site, sitemap_index)
        if not maps:
            return f"No sitemaps submitted for {site}" + (f" under {sitemap_index}" if sitemap_index else "") + "."
        rows = [_sitemap_row(s) for s in maps]
        note = "\n\n_`URLs` is the count Google read from the file; the API's `indexed` counter has been unreliable for years, so it is not shown — use inspect_urls or the Pages report for indexing._"
        return md_table(["sitemap", "type", "submitted", "downloaded", "URLs", "err", "warn", ""], rows) + note

    @mcp.tool(annotations=READ)
    @guarded
    def get_sitemap(site_url: str, sitemap_url: str) -> str:
        """Details of one sitemap: submission/download dates, errors, warnings, per-type URL counts."""
        site = rt.site(site_url)
        s = rt.client().sitemap_get(site, sitemap_url.strip())
        contents = s.get("contents") or []
        out = [kv([
            ("sitemap", s.get("path")), ("index", bool(s.get("isSitemapsIndex"))), ("pending", bool(s.get("isPending"))),
            ("last submitted", s.get("lastSubmitted")), ("last downloaded", s.get("lastDownloaded")),
            ("errors", s.get("errors", 0)), ("warnings", s.get("warnings", 0)),
        ])]
        if contents:
            out.append(md_table(["type", "submitted"], [[c.get("type"), fmt_int(int(c.get("submitted", 0) or 0))] for c in contents]))
        return "\n".join(out)

    @mcp.tool(annotations=WRITE)
    @guarded
    def submit_sitemap(site_url: str, sitemap_url: str) -> str:
        """Submit (or resubmit) a sitemap URL (needs GSC_ALLOW_WRITE=1)."""
        rt.require_write()
        site = rt.site(site_url)
        rt.client().sitemap_submit(site, sitemap_url.strip())
        return f"Submitted {sitemap_url} for {site}. Google fetches it on its own schedule; check list_sitemaps later."

    @mcp.tool(annotations=DESTRUCTIVE)
    @guarded
    def delete_sitemap(site_url: str, sitemap_url: str) -> str:
        """Remove a sitemap from Search Console (needs GSC_ALLOW_WRITE=1). The file itself is untouched."""
        rt.require_write()
        site = rt.site(site_url)
        rt.client().sitemap_delete(site, sitemap_url.strip())
        return f"Deleted {sitemap_url} from {site}."

    # -- url inspection ------------------------------------------------------

    def _flat_lines(url: str, f: dict) -> str:
        items = [
            ("URL", url), ("index verdict", f["verdict"]), ("coverage", f["coverage"]), ("indexing", f["indexing_state"]),
            ("fetch", f["page_fetch"]), ("robots.txt", f["robots"]), ("last crawl", f["last_crawl"]), ("crawled as", f["crawled_as"]),
            ("Google canonical", f["google_canonical"]), ("declared canonical", f["user_canonical"]),
            ("referring URLs", f["referring_urls"]), ("in sitemaps", ", ".join(f["sitemaps"]) or "none"),
            ("rich results verdict", f"{f['rich_results']} {', '.join(f['rich_result_types'])}".strip() or "none detected"),
            ("mobile", f["mobile"] if f["mobile"] not in ("", "VERDICT_UNSPECIFIED") else "not reported"), ("inspect in UI", f["link"]),
        ]
        s = kv(items)
        if f["rich_result_issues"]:
            s += "\n- **rich result issues:**\n  - " + "\n  - ".join(f["rich_result_issues"])
        if canonical_mismatch(f):
            s += "\n- ⚠ **Google chose a different canonical than the page declares.**"
        return s

    @mcp.tool(annotations=READ)
    @guarded
    def inspect_url(site_url: str, page_url: str, language: str = "en-US") -> str:
        """Full URL Inspection for one page: index verdict, crawl, canonical, robots, sitemaps, rich results, mobile."""
        site = rt.site(site_url)
        res = inspect_many(rt.client(), rt.store(), site, [page_url], concurrency=1, language=language)[0]
        if not res["ok"]:
            raise GSCError(f"Inspection failed for {page_url}: {res['error']}")
        return _flat_lines(page_url, res["data"])

    def _notes(f: dict) -> str:
        notes = []
        if canonical_mismatch(f):
            notes.append("⚠ canonical differs")
        if f["rich_result_issues"]:
            notes.append(f"{len(f['rich_result_issues'])} rich-result issue(s)")
        return "; ".join(notes)

    @mcp.tool(annotations=READ)
    @guarded
    def inspect_urls(site_url: str, urls: str, concurrency: int = 8, language: str = "en-US") -> str:
        """Inspect up to 50 URLs in parallel (comma- or newline-separated). Quota is checked first.

        Columns: `index` is the indexing verdict, `rich results` the structured-data verdict — a page can
        PASS one and FAIL the other. URLs not reached within the time budget are marked and can be re-sent.
        """
        site = rt.site(site_url)
        results = inspect_many(rt.client(), rt.store(), site, _split_urls(urls), concurrency=concurrency, language=language)
        rows = []
        for r in results:
            if r["ok"]:
                f = r["data"]
                rows.append([r["url"], f["verdict"], f["coverage"], (f["last_crawl"] or "")[:10], f["rich_results"] or "none", _notes(f)])
            else:
                rows.append([r["url"], "NOT INSPECTED" if r.get("skipped") else "ERROR", r["error"], "", "", ""])
        used = rt.store().inspections_today(site, utc_day())
        skipped = sum(1 for r in results if r.get("skipped"))
        tail = f"\n\n_{used}/{DAILY_QUOTA} inspections used today for this property._"
        if skipped:
            tail += f" _{skipped} URL(s) were not inspected within the time budget — send them again._"
        return md_table(["URL", "index", "coverage", "last crawl", "rich results", "note"], rows) + tail

    @mcp.tool(annotations=READ)
    @guarded
    def indexing_summary(site_url: str, urls: str, concurrency: int = 8, language: str = "en-US") -> str:
        """Problems only: which of the given URLs are not indexed or have structured-data failures, and why. Up to 50 URLs."""
        site = rt.site(site_url)
        results = inspect_many(rt.client(), rt.store(), site, _split_urls(urls), concurrency=concurrency, language=language)
        ok, bad, skipped = [], [], []
        for r in results:
            if r.get("skipped"):
                skipped.append(r["url"])
                continue
            if not r["ok"]:
                bad.append([r["url"], "error", r["error"]])
                continue
            f = r["data"]
            problems = []
            if f["verdict"] != "PASS":
                problems.append(f"{f['verdict']}: {f['coverage']}")
            if f["page_fetch"] and f["page_fetch"] != "SUCCESSFUL":
                problems.append(f"fetch {f['page_fetch']}")
            if f["robots"] and f["robots"] != "ALLOWED":
                problems.append(f"robots {f['robots']}")
            if canonical_mismatch(f):
                problems.append(f"canonical → {f['google_canonical']}")
            if rich_results_failing(f):
                problems.append(f"rich results {f['rich_results'] or 'issues'} ({len(f['rich_result_issues'])} issue(s))")
            (bad if problems else ok).append([r["url"], f["verdict"], "; ".join(problems)])
        out = [f"**{site}** · {len(ok)} indexed cleanly, {len(bad)} with problems" + (f", {len(skipped)} not inspected" if skipped else "")]
        if bad:
            out += ["", md_table(["URL", "index", "problems"], bad)]
        if ok:
            out += ["", "Clean: " + ", ".join(r[0] for r in ok)]
        if skipped:
            out += ["", "Not inspected within the time budget — send these again: " + ", ".join(skipped)]
        return "\n".join(out)

    @mcp.tool(annotations=hints(open_world=False))
    @guarded
    def inspection_quota(site_url: str) -> str:
        """How many URL inspections this server has used today for a property (Google allows ~2,000/day)."""
        site = rt.site(site_url)
        used = rt.store().inspections_today(site, utc_day())
        return f"{used}/{DAILY_QUOTA} used today (UTC day) for {site}, as counted by this server."
