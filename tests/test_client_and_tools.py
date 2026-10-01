"""End-to-end tool tests against a fake Search Console — no network, no credentials."""

import pytest

from conftest import SITE, call
from gsc_mcp_full.client import GSCClient, GSCError, resolve_site, rows_to_dicts

# -- client helpers ----------------------------------------------------------------


def test_resolve_site_loose_matching():
    sites = [{"siteUrl": "sc-domain:example.com"}, {"siteUrl": "https://www.other.com/"}]
    assert resolve_site(sites, "example.com") == "sc-domain:example.com"
    assert resolve_site(sites, "https://example.com/") == "sc-domain:example.com"
    assert resolve_site(sites, "other.com") == "https://www.other.com/"
    assert resolve_site(sites, "nope.com") is None


def test_rows_to_dicts():
    d = rows_to_dicts([{"keys": ["q", "p"], "clicks": 1, "impressions": 2, "ctr": 0.5, "position": 3}], ["query", "page"])
    assert d == [{"query": "q", "page": "p", "clicks": 1, "impressions": 2, "ctr": 0.5, "position": 3.0}]


class _Resp:
    def __init__(self, status, payload, headers=None):
        self.status_code = status
        self._p = payload
        self.headers = headers or {}
        self.content = b"x"
        self.text = str(payload)

    def json(self):
        return self._p


class _Session:
    """Scripted responses; records the requests it saw."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, json=None, params=None, timeout=None):
        self.calls.append((method, url, json, params))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_query_all_pages_until_short_page(monkeypatch):
    monkeypatch.setattr("gsc_mcp_full.client.MAX_ROW_LIMIT", 2)
    s = _Session([_Resp(200, {"rows": [{"keys": ["a"]}, {"keys": ["b"]}]}), _Resp(200, {"rows": [{"keys": ["c"]}], "metadata": {"firstIncompleteDate": "2026-09-27"}})])
    rows, meta = GSCClient(credentials=None, session=s).query_all("sc-domain:x", {"dimensions": ["query"]}, max_rows=10)
    assert [r["keys"][0] for r in rows] == ["a", "b", "c"]
    assert meta["firstIncompleteDate"] == "2026-09-27"
    assert s.calls[1][2]["startRow"] == 2


def test_retry_then_friendly_403(monkeypatch):
    monkeypatch.setattr("gsc_mcp_full.client.time.sleep", lambda *_: None)
    s = _Session([_Resp(503, {}), _Resp(403, {"error": {"message": "User does not have sufficient permission", "errors": [{"reason": "forbidden"}]}})])
    with pytest.raises(GSCError) as e:
        GSCClient(credentials=None, session=s).sites_list()
    assert "do not have access" in str(e.value) and len(s.calls) == 2


# -- tools ---------------------------------------------------------------------------


def test_all_tools_registered(server):
    names = {t.name for t in server.mcp._tool_manager.list_tools()}
    expected = {
        "get_capabilities", "reauthenticate", "build_query_regex", "list_properties", "get_property", "add_property", "remove_property",
        "query_search_analytics", "performance_overview", "compare_periods", "queries_for_page", "pages_for_query", "hourly_performance",
        "data_freshness", "list_sitemaps", "get_sitemap", "submit_sitemap", "delete_sitemap", "inspect_url", "inspect_urls",
        "indexing_summary", "inspection_quota", "query_variants", "language_breakdown", "keyboard_mistypes", "top_terms",
        "find_cannibalization", "striking_distance", "low_ctr_opportunities", "content_movers", "brand_split", "sync_history",
        "history_status", "history_query", "history_trend", "history_compare", "history_sql",
    }
    assert names == expected, names ^ expected


def test_list_and_resolve_property(server):
    assert SITE in call(server, "list_properties")
    assert "siteOwner" in call(server, "get_property", site_url="example.com")
    assert "No property matches" in call(server, "get_property", site_url="nope.com")


def test_query_search_analytics_groups_variants(server):
    out = call(server, "query_search_analytics", site_url="example.com", group_variants=True)
    assert "کولر گازی" in out and "| 3 |" in out  # three spellings/rows merged into one keyword
    assert "still being collected" in out
    assert "Period totals: clicks 23" in out  # from a no-dimension request, not a sum of rows


def test_query_variants_shows_hidden_impressions(server):
    out = call(server, "query_variants", site_url=SITE)
    assert "letter-forms" in out and "Impressions hidden" in out


def test_keyboard_mistypes_finds_sghl(server):
    out = call(server, "keyboard_mistypes", site_url=SITE)
    assert "sghl" in out and "سلام" in out


def test_cannibalization_and_opportunities(server):
    out = call(server, "find_cannibalization", site_url=SITE, min_impressions=10)
    assert "https://example.com/a" in out and "https://example.com/b" in out and "best" in out
    assert "پکیج دیواری" in call(server, "striking_distance", site_url=SITE)
    assert "کولر" in call(server, "pages_for_query", site_url=SITE, query="كولر گازي")


def test_queries_for_page_exact_then_contains(server):
    exact = call(server, "queries_for_page", site_url=SITE, page_url="https://example.com/a")
    assert "کولر گازی" in exact and "page https://example.com/a" in exact and "پکیج" not in exact
    loose = call(server, "queries_for_page", site_url=SITE, page_url="example.com/")
    assert "no page is exactly" in loose and "پکیج دیواری" in loose
    assert "No queries for" in call(server, "queries_for_page", site_url=SITE, page_url="https://example.com/zzz")


def test_hourly_local_days(server):
    out = call(server, "hourly_performance", site_url=SITE, days=2, timezone="Asia/Tehran")
    assert "Asia/Tehran" in out and "| 2026-" in out


def test_write_tools_are_gated(server):
    assert "disabled" in call(server, "submit_sitemap", site_url=SITE, sitemap_url="https://example.com/s.xml")
    assert "disabled" in call(server, "remove_property", site_url=SITE)


def test_inspection_and_quota(server):
    out = call(server, "indexing_summary", site_url=SITE, urls="https://example.com/a\nhttps://example.com/b")
    assert "1 indexed cleanly, 1 with problems" in out and "not indexed" in out and "rich results FAIL" in out
    assert "2/2000" in call(server, "inspection_quota", site_url=SITE)
    assert "Missing field" in call(server, "inspect_url", site_url=SITE, page_url="https://example.com/b")
    assert "Missing field" not in call(server, "inspect_url", site_url=SITE, page_url="https://example.com/a")
    table = call(server, "inspect_urls", site_url=SITE, urls="https://example.com/a, https://example.com/b")
    assert "| index |" in table and "| rich results |" in table and "FAIL" in table  # a failing page is never shown as clean


def test_every_analysis_tool_runs(server):
    # Tool names shadow same-named analysis functions inside the registration closure,
    # so every analysis tool is run for real here.
    assert "fa" in call(server, "language_breakdown", site_url=SITE)
    assert "کولر" in call(server, "top_terms", site_url=SITE)
    assert "brand" in call(server, "brand_split", site_url=SITE, brand_terms="کولر, cooler")
    out = call(server, "low_ctr_opportunities", site_url=SITE, min_impressions=10)
    assert "CTR curve" in out and "Error" not in out  # the fake data has no under-performers; the tool must say so
    out = call(server, "content_movers", site_url=SITE)
    assert "vs" in out and "Error" not in out
    out = call(server, "compare_periods", site_url=SITE)
    assert "Current (totals):" in out and "Error" not in out
    assert "Error" not in call(server, "performance_overview", site_url=SITE)
    assert "Error" not in call(server, "data_freshness", site_url=SITE)
    assert "[کك]" in call(server, "build_query_regex", term="کولر گازی")  # letter classes, not the literal


def test_sitemaps(server):
    out = call(server, "list_sitemaps", site_url=SITE)
    assert "sitemap.xml" in out and "| 50 |" in out


def test_history_sync_query_trend(server):
    out = call(server, "sync_history", site_url=SITE, days=3)
    assert "3 day(s) fetched" in out
    assert "Nothing to fetch" not in out
    st = call(server, "history_status", site_url=SITE)
    assert "web" in st
    from gsc_mcp_full.dates import resolve_range

    r = resolve_range(days=3)
    q = call(server, "history_query", site_url=SITE, start_date=r.start_iso, end_date=r.end_iso, query_contains="كولر")
    assert "کولر گازی" in q and "Stored totals" in q
    t = call(server, "history_trend", site_url=SITE, start_date=r.start_iso, end_date=r.end_iso, granularity="day")
    assert t.count("| 2026-") >= 3 or t.count("| 20") >= 3
    assert "n |" in call(server, "history_sql", sql="SELECT COUNT(*) AS n FROM rows")
    assert "only SELECT" in call(server, "history_sql", sql="DELETE FROM rows")


def test_capabilities_lists_tools(server):
    out = call(server, "get_capabilities")
    assert "query_variants" in out and "readonly" in out
