"""Analysis over Search Analytics rows — pure functions, no network.

Every function takes plain row dicts (``query``/``page``/… plus ``clicks``,
``impressions``, ``ctr``, ``position``) and returns plain dicts, so the same
code runs on a fresh API response and on rows read back from the local
history store. Queries are compared by their multilingual match key, so
«خرید ماشین» and «خريد ماشين» count as one keyword everywhere here.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence

from .i18n import detect, normalize
from .i18n.scripts import UNSPACED_SCRIPTS

# Rough organic CTR by position, used only when a site has too few rows to
# compute its own curve. Numbers are typical published averages, not gospel.
_BENCHMARK_CTR = {
    1: 0.28, 2: 0.15, 3: 0.11, 4: 0.08, 5: 0.07, 6: 0.05, 7: 0.04, 8: 0.035, 9: 0.03, 10: 0.025,
}


def benchmark_ctr(position: float) -> float:
    if position < 1:
        return _BENCHMARK_CTR[1]
    p = int(round(position))
    if p in _BENCHMARK_CTR:
        return _BENCHMARK_CTR[p]
    if p <= 20:
        return 0.015
    return 0.005


def totals(rows: Iterable[dict]) -> dict:
    clicks = imps = 0
    pw = 0.0
    for r in rows:
        i = int(r.get("impressions", 0) or 0)
        clicks += int(r.get("clicks", 0) or 0)
        imps += i
        pw += float(r.get("position", 0) or 0) * i
    return {
        "clicks": clicks,
        "impressions": imps,
        "ctr": round(clicks / imps, 4) if imps else 0.0,
        "position": round(pw / imps, 2) if imps else 0.0,
    }


def _key_of(row: dict, fields: Sequence[str], level: str, lang_hint: str | None) -> tuple:
    parts = []
    for f in fields:
        v = row.get(f, "")
        parts.append(normalize(v, level, lang_hint).key if f == "query" else v)
    return tuple(parts)


def aggregate(rows: Iterable[dict], by: Sequence[str], level: str = "standard", lang_hint: str | None = None) -> list[dict]:
    """Sum rows that share the given fields (queries compared by match key).

    The displayed ``query`` of a group is its most-seen spelling.
    """
    groups: dict[tuple, dict] = {}
    for r in rows:
        k = _key_of(r, by, level, lang_hint)
        g = groups.get(k)
        i = int(r.get("impressions", 0) or 0)
        if g is None:
            g = groups[k] = {f: r.get(f, "") for f in by}
            g.update({"clicks": 0, "impressions": 0, "_pw": 0.0, "_top": -1, "variants": 0})
        g["clicks"] += int(r.get("clicks", 0) or 0)
        g["impressions"] += i
        g["_pw"] += float(r.get("position", 0) or 0) * i
        g["variants"] += 1
        if "query" in by and i > g["_top"]:
            g["_top"] = i
            g["query"] = r.get("query", "")
    out = []
    for g in groups.values():
        i = g["impressions"]
        g["ctr"] = round(g["clicks"] / i, 4) if i else 0.0
        g["position"] = round(g["_pw"] / i, 2) if i else 0.0
        del g["_pw"], g["_top"]
        out.append(g)
    out.sort(key=lambda g: (-g["clicks"], -g["impressions"]))
    return out


def compare(
    current: Iterable[dict],
    previous: Iterable[dict],
    by: Sequence[str] = ("query",),
    level: str = "standard",
    lang_hint: str | None = None,
) -> dict:
    """Join two periods on ``by`` and compute deltas.

    Returns ``{"totals": {...}, "rows": [...]}`` where each row carries
    ``clicks``/``prev_clicks``/``delta_clicks`` etc. Rows are sorted by absolute
    click change so the biggest movers, up or down, come first.
    """
    cur = {_key_of(g, by, level, lang_hint): g for g in aggregate(current, by, level, lang_hint)}
    prev = {_key_of(g, by, level, lang_hint): g for g in aggregate(previous, by, level, lang_hint)}
    rows = []
    for k in set(cur) | set(prev):
        c = cur.get(k, {})
        p = prev.get(k, {})
        base = c or p
        row = {f: base.get(f, "") for f in by}
        for m in ("clicks", "impressions", "ctr", "position"):
            row[m] = c.get(m, 0)
            row["prev_" + m] = p.get(m, 0)
        row["delta_clicks"] = row["clicks"] - row["prev_clicks"]
        row["delta_impressions"] = row["impressions"] - row["prev_impressions"]
        row["delta_position"] = round((row["prev_position"] - row["position"]), 2) if c and p else None
        row["status"] = "new" if not p else "lost" if not c else "both"
        rows.append(row)
    rows.sort(key=lambda r: -abs(r["delta_clicks"]))
    tc, tp = totals(current), totals(previous)
    return {"totals": {"current": tc, "previous": tp}, "rows": rows}


# Pages shown together in ONE search result (a result and its sitelinks) report the same
# position and almost the same impressions. Two separate results cannot do that.
SITELINK_POSITION_TOLERANCE = 0.25
SITELINK_IMPRESSION_BAND = (0.85, 1.18)
MAIN_PAGE_COVERAGE = 0.9  # the main page is in at least this share of the keyword's searches


def base_page(url: str) -> str:
    """The page without its ``#section`` — Google reports jump-to links as separate URLs."""
    return url.split("#", 1)[0]


def collapse_pages(
    rows: Iterable[dict],
    level: str = "standard",
    lang_hint: str | None = None,
    query_impressions: dict[str, int] | None = None,
) -> list[dict]:
    """One row per (keyword, page), free of two artefacts of Google's per-page counting.

    When data is grouped by page, one search can produce several rows for what
    a person sees as a single result:

    - ``/page/#section`` links under a result are listed as their own URLs.
      They are folded into ``/page/``: clicks add up; impressions do not (it
      was one impression), so the largest is kept.
    - Sitelinks under a result are listed as their own pages, each credited
      with the impression and the parent's position. A page at the same
      position as the keyword's main page is folded into it (``sitelinks``
      counts them) when it must have been shown *with* the main page rather
      than instead of it.

    "With, not instead of" is decided from ``query_impressions`` — the
    keyword's impressions counted per search, keyed by match key — when given:
    if the main page already appears in nearly every search for the keyword,
    another page at the same position cannot be an alternative to it. Two
    pages that take turns (real cannibalization) each cover only part of the
    searches and are left alone. Without ``query_impressions`` the fallback is
    stricter: same position and nearly the same impressions.

    Without this, a brand query with sitelinks looks like six pages competing
    for one keyword. Rows need ``query`` and ``page``; spellings of a query are merged.
    """
    per: dict[tuple[str, str], dict] = {}
    for r in rows:
        q, page = r.get("query", ""), r.get("page", "")
        if not q or not page:
            continue
        k = (q, base_page(page))
        clicks = int(r.get("clicks", 0) or 0)
        imps = int(r.get("impressions", 0) or 0)
        pos = float(r.get("position", 0) or 0)
        e = per.get(k)
        if e is None:
            per[k] = {"query": q, "page": k[1], "clicks": clicks, "impressions": imps, "position": pos, "fragments": int("#" in page)}
        else:
            e["clicks"] += clicks
            e["fragments"] += int("#" in page)
            if imps > e["impressions"]:
                e["impressions"], e["position"] = imps, pos

    groups: dict[str, dict] = {}
    for e in per.values():
        key = normalize(e["query"], level, lang_hint).key
        g = groups.setdefault(key, {"query": e["query"], "_top": -1, "pages": {}})
        if e["impressions"] > g["_top"]:
            g["_top"], g["query"] = e["impressions"], e["query"]
        p = g["pages"].setdefault(e["page"], {"page": e["page"], "clicks": 0, "impressions": 0, "_pw": 0.0, "fragments": 0})
        p["clicks"] += e["clicks"]
        p["impressions"] += e["impressions"]
        p["_pw"] += e["position"] * e["impressions"]
        p["fragments"] += e["fragments"]

    low, high = SITELINK_IMPRESSION_BAND
    out = []
    for key, g in groups.items():
        pages = list(g["pages"].values())
        for p in pages:
            p["position"] = round(p.pop("_pw") / p["impressions"], 2) if p["impressions"] else 0.0
            p["sitelinks"] = 0
        pages.sort(key=lambda p: (-p["clicks"], -p["impressions"]))
        main, kept = pages[0], [pages[0]]
        for p in pages[1:]:
            same_position = main["impressions"] > 0 and abs(p["position"] - main["position"]) <= SITELINK_POSITION_TOLERANCE
            ratio = p["impressions"] / main["impressions"] if main["impressions"] else 0.0
            searches = (query_impressions or {}).get(key)
            if searches:
                shown_with_main = ratio <= high and main["impressions"] >= MAIN_PAGE_COVERAGE * searches
            else:
                shown_with_main = low <= ratio <= high
            if same_position and shown_with_main:
                main["clicks"] += p["clicks"]
                main["sitelinks"] += 1
            else:
                kept.append(p)
        for p in kept:
            i = p["impressions"]
            out.append({"query": g["query"], "key": key, **p, "ctr": round(p["clicks"] / i, 4) if i else 0.0})
    out.sort(key=lambda r: (-r["clicks"], -r["impressions"]))
    return out


def cannibalization(
    rows: Iterable[dict],
    level: str = "standard",
    lang_hint: str | None = None,
    min_impressions: int = 20,
    min_share: float = 0.10,
    query_impressions: dict[str, int] | None = None,
) -> list[dict]:
    """Queries where more than one page gets a meaningful share of impressions.

    Rows need ``query`` and ``page``. Section links and sitelinks are folded
    into their page first (see :func:`collapse_pages`), so only pages that
    appear as *separate* results count. A page counts when it has at least
    ``min_share`` of the query's impressions. Groups are scored by the
    impressions *not* going to the best-positioned page.
    """
    by_q: dict[str, list[dict]] = defaultdict(list)
    for r in collapse_pages(rows, level, lang_hint, query_impressions):
        by_q[r["key"]].append(r)
    out = []
    for key, found in by_q.items():
        total = sum(p["impressions"] for p in found)
        if total < min_impressions or len(found) < 2:
            continue
        pages = [
            {
                "page": p["page"],
                "clicks": p["clicks"],
                "impressions": p["impressions"],
                "share": round(p["impressions"] / total, 3),
                "position": p["position"],
                "sitelinks": p["sitelinks"],
            }
            for p in found
            if p["impressions"] / total >= min_share
        ]
        if len(pages) < 2:
            continue
        pages.sort(key=lambda p: p["position"])
        out.append(
            {
                "query": found[0]["query"],
                "key": key,
                "impressions": total,
                "clicks": sum(p["clicks"] for p in found),
                "pages": pages,
                "best_page": pages[0]["page"],
                "competing_impressions": sum(p["impressions"] for p in pages[1:]),
            }
        )
    out.sort(key=lambda g: -g["competing_impressions"])
    return out


def striking_distance(
    rows: Iterable[dict],
    min_position: float = 8.0,
    max_position: float = 20.0,
    min_impressions: int = 10,
    level: str = "standard",
    lang_hint: str | None = None,
    query_impressions: dict[str, int] | None = None,
) -> list[dict]:
    """Queries ranking just off the first page (default positions 8–20) with real demand.

    ``potential_clicks`` estimates the extra clicks at position 5 — a
    conservative target — using the benchmark curve.
    """
    out = []
    rows = list(rows)
    grouped = collapse_pages(rows, level, lang_hint, query_impressions) if any("page" in r for r in rows) else aggregate(rows, ("query",), level, lang_hint)
    for g in grouped:
        if min_position <= g["position"] <= max_position and g["impressions"] >= min_impressions:
            g["potential_clicks"] = max(0, int(g["impressions"] * benchmark_ctr(5)) - g["clicks"])
            out.append(g)
    out.sort(key=lambda g: (-g["impressions"], g["position"]))
    return out


def low_ctr(
    rows: Iterable[dict],
    min_impressions: int = 100,
    ratio: float = 0.5,
    max_position: float = 10.0,
    level: str = "standard",
    lang_hint: str | None = None,
    query_impressions: dict[str, int] | None = None,
) -> tuple[list[dict], str]:
    """Rows whose CTR is far below what their position should earn.

    Expected CTR comes from the site's own median CTR per position bucket when
    the bucket has enough rows (≥ 8), otherwise from the benchmark curve. Returns
    ``(rows, method)`` where ``method`` says which curve was used.
    """
    rows = list(rows)
    # With pages, sitelinks would look like page-one results nobody clicks; fold them away first.
    grouped = collapse_pages(rows, level, lang_hint, query_impressions) if any("page" in r for r in rows) else aggregate(rows, ("query",), level, lang_hint)
    agg = [g for g in grouped if g["impressions"] >= min_impressions]
    buckets: dict[int, list[float]] = defaultdict(list)
    for g in agg:
        buckets[int(round(g["position"]))].append(g["ctr"])
    own: dict[int, float] = {}
    for b, vals in buckets.items():
        if len(vals) >= 8:
            vals.sort()
            own[b] = vals[len(vals) // 2]
    method = "site's own CTR curve" if own else "benchmark CTR curve"
    out = []
    for g in agg:
        if g["position"] > max_position:
            continue
        b = int(round(g["position"]))
        expected = own.get(b, benchmark_ctr(g["position"]))
        if expected and g["ctr"] < expected * ratio:
            g["expected_ctr"] = round(expected, 4)
            g["missed_clicks"] = int(g["impressions"] * expected) - g["clicks"]
            out.append(g)
    out.sort(key=lambda g: -g["missed_clicks"])
    return out, method


def brand_split(rows: Iterable[dict], brand_terms: Sequence[str], level: str = "loose", lang_hint: str | None = None) -> dict:
    """Split rows into brand / non-brand.

    Give the brand in every script it is searched in («تویوتا», «toyota», トヨタ);
    each term is normalised the same way as the queries, so spelling variants
    still match.

    A term matches as whole words («lg» is not inside «bulgaria»). With
    ``level="loose"`` a term of four or more characters also matches when it
    is glued to its neighbours («toyotacamry»), and terms in scripts written
    without spaces always match by containment.
    """
    terms = []
    for t in brand_terms:
        std = normalize(t, "standard", lang_hint)
        if std.key:
            terms.append((f" {std.key} ", std.key.replace(" ", ""), std.script in UNSPACED_SCRIPTS or std.script == "japanese"))
    brand, non = [], []
    for r in rows:
        qk = normalize(r.get("query", ""), "standard", lang_hint).key
        padded, glued = f" {qk} ", qk.replace(" ", "")
        hit = any(
            spaced in padded or ((unspaced or (level == "loose" and len(joined) >= 4)) and joined in glued)
            for spaced, joined, unspaced in terms
        )
        (brand if hit else non).append(r)
    tb, tn = totals(brand), totals(non)
    all_clicks = tb["clicks"] + tn["clicks"]
    return {
        "brand": tb,
        "non_brand": tn,
        "brand_queries": len(brand),
        "non_brand_queries": len(non),
        "brand_click_share": round(tb["clicks"] / all_clicks, 3) if all_clicks else 0.0,
        "top_brand": aggregate(brand, ("query",), level, lang_hint)[:10],
    }


def language_breakdown(rows: Iterable[dict], lang_hint: str | None = None) -> list[dict]:
    """Share of clicks/impressions per detected script + language of the query."""
    agg: dict[tuple[str, str], dict] = {}
    for r in rows:
        d = detect(r.get("query", ""), lang_hint)
        k = (d.script, d.lang or "?")
        a = agg.setdefault(k, {"script": d.script, "lang": d.lang or "?", "queries": 0, "clicks": 0, "impressions": 0, "_pw": 0.0, "example": r.get("query", "")})
        i = int(r.get("impressions", 0) or 0)
        a["queries"] += 1
        a["clicks"] += int(r.get("clicks", 0) or 0)
        a["impressions"] += i
        a["_pw"] += float(r.get("position", 0) or 0) * i
    total_clicks = sum(a["clicks"] for a in agg.values()) or 1
    out = []
    for a in agg.values():
        a["position"] = round(a["_pw"] / a["impressions"], 2) if a["impressions"] else 0.0
        a["ctr"] = round(a["clicks"] / a["impressions"], 4) if a["impressions"] else 0.0
        a["click_share"] = round(a["clicks"] / total_clicks, 3)
        del a["_pw"]
        out.append(a)
    out.sort(key=lambda a: -a["clicks"])
    return out


def movers(
    current: Iterable[dict],
    previous: Iterable[dict],
    by: Sequence[str] = ("page",),
    min_prev_clicks: int = 10,
    threshold: float = 0.30,
    level: str = "standard",
    lang_hint: str | None = None,
) -> dict:
    """Pages (or queries) that lost or gained at least ``threshold`` of their clicks.

    Returns ``{"decayed": [...], "rising": [...], "lost": [...], "new": [...]}``.
    """
    cmp = compare(current, previous, by, level, lang_hint)
    decayed, rising, lost, new = [], [], [], []
    for r in cmp["rows"]:
        if r["status"] == "lost" and r["prev_clicks"] >= min_prev_clicks:
            lost.append(r)
        elif r["status"] == "new" and r["clicks"] >= min_prev_clicks:
            new.append(r)
        elif r["status"] == "both" and r["prev_clicks"] >= max(min_prev_clicks, 1):  # a ratio needs a baseline
            change = (r["clicks"] - r["prev_clicks"]) / r["prev_clicks"]
            r["change"] = round(change, 3)
            if change <= -threshold:
                decayed.append(r)
            elif change >= threshold:
                rising.append(r)
    decayed.sort(key=lambda r: r["delta_clicks"])
    rising.sort(key=lambda r: -r["delta_clicks"])
    lost.sort(key=lambda r: -r["prev_clicks"])
    new.sort(key=lambda r: -r["clicks"])
    return {"decayed": decayed, "rising": rising, "lost": lost, "new": new, "totals": cmp["totals"]}


def top_pages_for_query(rows: Iterable[dict], query: str, level: str = "standard", lang_hint: str | None = None) -> list[dict]:
    k = normalize(query, level, lang_hint).key
    hits = [r for r in rows if normalize(r.get("query", ""), level, lang_hint).key == k]
    return aggregate(hits, ("page",), level, lang_hint)
