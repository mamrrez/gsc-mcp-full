"""Behaviour the server guarantees, one test per rule.

Each test states the rule it protects, so a change that breaks one fails with the reason attached.
"""

import asyncio
import re
import sys
import threading
import time
from datetime import date

import pytest

from conftest import SITE, FakeClient, call
from gsc_mcp_full import analysis
from gsc_mcp_full.auth import AuthError, _scopes_cover, credential_kind, load_credentials
from gsc_mcp_full.client import GSCClient, GSCError, _friendly, resolve_site
from gsc_mcp_full.dates import bucket_hours, resolve_range
from gsc_mcp_full.format import md_table
from gsc_mcp_full.i18n import api_regex, detect, match_key, term_frequency
from gsc_mcp_full.i18n.regexes import python_regex
from gsc_mcp_full.inspection import inspect_many
from gsc_mcp_full.runtime import ToolError
from gsc_mcp_full.settings import Settings
from gsc_mcp_full.store import HistoryStore, bucket_days
from gsc_mcp_full.sync import sync_range

# -- multilingual engine -----------------------------------------------------------


def test_folds_apply_inside_mixed_script_queries():
    # Folds apply to the letters of each script wherever they appear: brand/model queries
    # on a Persian site — the commonest kind — must merge like pure Persian ones.
    assert match_key("خريد iphone 13 pro max") == match_key("خرید iphone 13 pro max")
    assert match_key("samsung گوشي") == match_key("samsung گوشی")
    assert match_key("ёлка christmas tree") == match_key("елка christmas tree")
    assert match_key("قيمت toyota ۲۰۲۴") == match_key("قیمت toyota 2024")


def test_loose_accent_strip_does_not_eat_indic_vowel_signs():
    assert "ि" in match_key("café हिंदी", "loose") and match_key("café हिंदी", "loose").startswith("cafe")


def test_meaningful_punctuation_survives():
    # Only separator punctuation becomes a space: c++, c# and c are three keywords.
    assert len({match_key("c++"), match_key("c#"), match_key("c")}) == 3
    assert match_key(".net") != match_key("net")
    assert match_key("$100") != match_key("100%")
    assert match_key("3.5", "loose") != match_key("35", "loose") and match_key("1/2", "loose") != match_key("12", "loose")
    assert match_key("at&t") == "at&t"
    assert match_key("don't") == match_key("dont")
    assert match_key("HVAC-Design") == "hvac design"  # separators still separate


def test_query_filter_regex_is_case_insensitive_for_every_script():
    # Search Console lower-cases queries; without (?i) an upper-case letter in a mixed term matched nothing.
    assert api_regex("ماشین BMW", whole_word=False).startswith("(?i)")
    assert python_regex("ماشین BMW", whole_word=False).search("قیمت ماشین bmw")
    assert python_regex("iPhone ケース", whole_word=False).search("iphone ケース")


def test_regex_matches_what_the_match_key_merges():
    assert python_regex("کتابها").search("خرید کتاب‌ها")  # half-space inside a word
    assert python_regex("ماشـین").search("ماشین")  # tatweel in the term itself
    assert python_regex("елка").search("ёлка")
    assert python_regex("कमरा १२३", whole_word=False).search("कमरा १२३")  # a digit script must match itself
    assert python_regex("206", whole_word=False).search("پژو ۲۰۶")


def test_lang_hint_only_settles_ambiguous_queries():
    # A language hint decides ambiguous queries only; plainly Arabic or Urdu text keeps its label.
    assert detect("ایئر کنڈیشنر", "fa").lang == "ur"
    assert detect("أسعار السيارة", "fa").lang == "ar"
    assert detect("خريد ماشين", "fa").lang == "fa"  # Arabic keyboard, Persian words: the hint decides
    assert detect("خريد ماشين").lang == "ar"  # no hint: only the keyboard is known
    assert detect("ISPARTA klima", "tr").lang == "tr"


def test_stopwords_are_compared_in_key_form():
    rows = [{"query": "سيارة في دبي", "clicks": 1, "impressions": 10}, {"query": "السفر إلى دبي", "clicks": 1, "impressions": 5}]
    terms = {t["term"] for t in term_frequency(rows, top=20)[0]}
    assert "في" not in terms and "إلى" not in terms and "دبي" in terms


def test_both_persian_keyboard_layouts():
    from gsc_mcp_full.i18n import find_layout_mistypes, remap_from_qwerty

    assert remap_from_qwerty("ovdn lhadk", "fa") == "خرید ماشین"
    assert remap_from_qwerty("\\v,", "fa2") == "پرو"  # پ sits on the backslash key in the other layout
    rows = [{"query": "خرید ماشین", "clicks": 9, "impressions": 90, "position": 2.0}, {"query": "ovdn lhadk", "clicks": 0, "impressions": 3, "position": 8.0}]
    hits = find_layout_mistypes(rows)
    assert len(hits) == 1 and hits[0].query == "ovdn lhadk" and hits[0].matched_query == "خرید ماشین"


# -- analysis ----------------------------------------------------------------------


def test_brand_split_matches_whole_words():
    rows = [{"query": q, "clicks": 1, "impressions": 10, "position": 1.0} for q in ("lg tv", "bulgaria trip", "php tutorial", "hp laptop", "toyotacamry", "تویوتا کمری")]
    r = analysis.brand_split(rows, ["lg", "hp", "toyota", "تويوتا"])
    assert r["brand_queries"] == 4 and r["non_brand_queries"] == 2  # bulgaria and php are not brand
    assert analysis.brand_split(rows, ["toyota"], level="standard")["brand_queries"] == 0  # glued form needs loose


def test_movers_with_zero_minimum_does_not_divide_by_zero():
    cur = [{"page": "/a", "clicks": 5, "impressions": 9, "position": 1.0}]
    prev = [{"page": "/a", "clicks": 0, "impressions": 9, "position": 1.0}]
    m = analysis.movers(cur, prev, ("page",), min_prev_clicks=0)
    assert m["decayed"] == [] and m["rising"] == []


# -- dates and formatting ----------------------------------------------------------


def test_hour_buckets_keep_half_hour_offsets():
    rows = [{"keys": ["2026-09-20T13:00:00-07:00"], "clicks": 1, "impressions": 2, "position": 1.0}]
    assert bucket_hours(rows, "Asia/Tehran", by="hour")[0]["bucket"] == "2026-09-20 23:30"
    assert bucket_hours(rows, "Asia/Kathmandu", by="hour")[0]["bucket"].endswith(":45")


def test_days_zero_is_an_error_not_28():
    with pytest.raises(ValueError):
        resolve_range(days=0)


def test_weeks_are_iso_weeks_across_new_year():
    days = [{"date": d, "clicks": 1, "impressions": 1, "position": 1.0} for d in ("2025-12-29", "2025-12-31", "2026-01-01", "2026-01-04")]
    assert [b["bucket"] for b in bucket_days(days, "week")] == ["2026-W01"]


def test_table_cells_cannot_act_as_markdown_and_urls_are_never_cut():
    long_url = "https://example.com/" + "%D8%AE%D8%B1%DB%8C%D8%AF-" * 12
    out = md_table(["q", "page"], [["![x](https://evil.example/i.png) <b>a|b\r\nc", long_url]])
    assert "![x]" not in out and "<b>" not in out and "a\\|b" in out and "\r" not in out
    assert long_url in out and "…" not in out


# -- client and auth ---------------------------------------------------------------


def test_403_diagnosis_ignores_the_word_scope_in_a_url():
    no_access = {"error": {"message": "User does not have sufficient permission for site 'https://horoscope.example/'.", "errors": [{"reason": "forbidden"}]}}
    assert "do not have access" in _friendly(403, no_access, "u")
    scope = {"error": {"message": "Request had insufficient authentication scopes.", "errors": [{"reason": "insufficientPermissions"}]}}
    assert "GSC_ALLOW_WRITE" in _friendly(403, scope, "u")


def test_typed_url_prefix_beats_the_domain_property():
    sites = [{"siteUrl": "sc-domain:example.com"}, {"siteUrl": "https://example.com/"}, {"siteUrl": "http://old.example.com/", "permissionLevel": "siteUnverifiedUser"}]
    assert resolve_site(sites, "https://example.com") == "https://example.com/"
    assert resolve_site(sites, "https://www.example.com") == "https://example.com/"
    assert resolve_site(sites, "example.com") == "sc-domain:example.com"
    assert resolve_site(sites, "old.example.com") == "http://old.example.com/"  # unverified only when nothing else fits


class _Raises:
    def __init__(self, exc):
        self.exc = exc
        self.calls = 0

    def request(self, *a, **k):
        self.calls += 1
        raise self.exc


def test_dead_refresh_token_becomes_an_auth_error_and_retires_the_client():
    from google.auth.exceptions import RefreshError

    c = GSCClient(credentials=None, session=_Raises(RefreshError("invalid_grant")))
    with pytest.raises(AuthError) as e:
        c.sites_list()
    assert "gsc-mcp-full auth" in str(e.value) and c.dead


def test_network_error_is_retried_then_reported(monkeypatch):
    import requests

    monkeypatch.setattr("gsc_mcp_full.client.time.sleep", lambda *_: None)
    s = _Raises(requests.ConnectionError("down"))
    with pytest.raises(GSCError) as e:
        GSCClient(credentials=None, session=s)._request("GET", "u", attempts=3)
    assert "Network error" in str(e.value) and s.calls == 3


def test_retry_after_is_capped(monkeypatch):
    slept = []
    monkeypatch.setattr("gsc_mcp_full.client.time.sleep", slept.append)

    class R:
        status_code, headers, content, text = 429, {"Retry-After": "3600"}, b"x", ""

        def json(self):
            return {}

    class S:
        def request(self, *a, **k):
            return R()

    with pytest.raises(GSCError):
        GSCClient(credentials=None, session=S())._request("GET", "u", attempts=2)
    assert slept == [30.0]


def _settings(tmp_path, monkeypatch, **env) -> Settings:
    for var in ("GSC_CREDENTIALS_PATH", "GSC_TOKEN_PATH", "GSC_SCOPE", "GSC_ALLOW_WRITE", "GSC_USE_ADC", "GOOGLE_APPLICATION_CREDENTIALS", "GSC_DB_PATH"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GSC_CONFIG_DIR", str(tmp_path / "cfg"))
    for k, v in env.items():
        monkeypatch.setenv(k, str(v))
    return Settings.from_env()


def test_no_credentials_fails_fast_without_probing_the_cloud(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))  # no gcloud ADC file here
    monkeypatch.delenv("APPDATA", raising=False)
    st = _settings(tmp_path, monkeypatch)
    t = time.monotonic()
    with pytest.raises(AuthError) as e:
        load_credentials(st, interactive=False)
    assert "No credentials configured" in str(e.value) and time.monotonic() - t < 2


def test_bad_credentials_files_give_auth_errors(tmp_path, monkeypatch):
    d = tmp_path / "adir"
    d.mkdir()
    with pytest.raises(AuthError):
        credential_kind(d)
    lst = tmp_path / "list.json"
    lst.write_text("[1, 2]")
    with pytest.raises(AuthError):
        load_credentials(_settings(tmp_path, monkeypatch, GSC_CREDENTIALS_PATH=lst), interactive=False)


def test_web_application_client_is_explained_not_attempted(tmp_path, monkeypatch):
    # A web client cannot redirect to a free local port; say which type is needed instead of failing in the browser.
    web = tmp_path / "web.json"
    web.write_text('{"web": {"client_id": "x", "client_secret": "y", "redirect_uris": ["http://localhost:3000/cb"]}}')
    assert credential_kind(web) == "oauth_web_client"
    with pytest.raises(AuthError) as e:
        load_credentials(_settings(tmp_path, monkeypatch, GSC_CREDENTIALS_PATH=web), interactive=True)
    assert "Desktop app" in str(e.value)


def test_token_without_recorded_scopes_is_not_rejected():
    assert _scopes_cover(None, "x") and _scopes_cover([], "x")


def test_failed_refresh_never_deletes_the_token_and_network_trouble_is_not_a_login(tmp_path, monkeypatch):
    from google.auth.exceptions import TransportError
    from google.oauth2.credentials import Credentials

    client = tmp_path / "client.json"
    client.write_text('{"installed": {"client_id": "x", "client_secret": "y", "auth_uri": "a", "token_uri": "t"}}')
    st = _settings(tmp_path, monkeypatch, GSC_CREDENTIALS_PATH=client)
    st.token_path.parent.mkdir(parents=True)
    token = '{"token": "old", "refresh_token": "r", "client_id": "x", "client_secret": "y", "token_uri": "t", "scopes": ["https://www.googleapis.com/auth/webmasters.readonly"], "expiry": "2020-01-01T00:00:00Z"}'
    st.token_path.write_text(token)

    def boom(self, request):
        raise TransportError("offline")

    monkeypatch.setattr(Credentials, "refresh", boom)
    with pytest.raises(AuthError) as e:
        load_credentials(st, interactive=True)  # must NOT open a browser for a network blip
    assert "untouched" in str(e.value) and st.token_path.read_text() == token


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_token_directory_permissions_are_left_alone(tmp_path):
    from gsc_mcp_full.auth import _write_private

    shared = tmp_path / "shared"
    shared.mkdir(mode=0o755)
    _write_private(shared / "token.json", "{}")
    assert (shared.stat().st_mode & 0o777) == 0o755 and ((shared / "token.json").stat().st_mode & 0o777) == 0o600


# -- store and sync ----------------------------------------------------------------


def test_store_survives_parallel_first_use(tmp_path):
    errors = []

    def open_store():
        try:
            HistoryStore(tmp_path / "fresh" / "h.sqlite").inspections_today("s", "2026-01-01")
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=open_store) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == []


def test_page_filter_is_literal_and_sql_path_is_escaped(tmp_path):
    odd = "odd #dir" if sys.platform == "win32" else "odd #dir?"  # Windows forbids ? in a name; # alone still breaks a raw URI
    st = HistoryStore(tmp_path / odd / "h.sqlite")
    rows = [
        {"keys": ["q", "https://x.com/air_conditioner"], "clicks": 1, "impressions": 1, "position": 1.0},
        {"keys": ["q", "https://x.com/air-conditioner"], "clicks": 1, "impressions": 1, "position": 1.0},
        {"keys": ["q", "https://x.com/%D9%85"], "clicks": 1, "impressions": 1, "position": 1.0},
    ]
    st.replace_day("s", "web", "2026-01-01", ("query", "page"), rows, final=True)
    assert [r["page"] for r in st.rows("s", "2026-01-01", "2026-01-01", by=("page",), page_contains="air_conditioner")] == ["https://x.com/air_conditioner"]
    assert len(st.rows("s", "2026-01-01", "2026-01-01", by=("page",), page_contains="%D9%85")) == 1
    assert st.sql("SELECT COUNT(*) FROM rows")[1][0][0] == 3  # the path with # and ? opens the right file
    with pytest.raises(ValueError):
        st.rows("s", "2026-01-01", "2026-01-01", query_contains="?")
    with pytest.raises(ValueError):
        st.replace_day("s", "web", "2026-01-02", ("query", "searchappearance"), [], final=True)


class _DayClient:
    def __init__(self, empty_days=(), incomplete_from=None):
        self.empty, self.incomplete, self.calls = set(empty_days), incomplete_from, []

    def query_all(self, site, body, max_rows=0):
        self.calls.append((body["startDate"], tuple(body["dimensions"]), body["type"]))
        meta = {"firstIncompleteDate": self.incomplete} if self.incomplete else {}
        rows = [] if body["startDate"] in self.empty else [{"keys": ["q", "p", "irn", "MOBILE"][: len(body["dimensions"])], "clicks": 1, "impressions": 1, "position": 1.0}]
        return rows, meta


def test_sync_does_not_freeze_an_empty_day_and_refetches_for_more_dimensions(tmp_path, monkeypatch):
    monkeypatch.setattr("gsc_mcp_full.sync.today_pacific", lambda: date(2026, 9, 10))
    monkeypatch.setattr("gsc_mcp_full.sync.is_final", lambda d: d <= date(2026, 9, 7))
    st = HistoryStore(tmp_path / "h.sqlite")
    c = _DayClient(empty_days={"2026-09-05"})
    res = sync_range(c, st, "s", date(2026, 9, 4), date(2026, 9, 6), "Web")
    assert res["search_type"] == "web" and res["days_fetched"] == 3 and res["days_pending"] == 0
    assert c.calls[0][2] == "web"  # "Web" is normalised before it is sent or stored
    c2 = _DayClient()
    assert sync_range(c2, st, "s", date(2026, 9, 4), date(2026, 9, 6))["days_fetched"] == 1  # only the empty day again
    assert [x[0] for x in c2.calls] == ["2026-09-05"]
    c3 = _DayClient()
    assert sync_range(c3, st, "s", date(2026, 9, 4), date(2026, 9, 6), dims=("query", "page", "country", "device"))["days_fetched"] == 3
    c4 = _DayClient(incomplete_from="2026-09-06")
    sync_range(c4, st, "s2", date(2026, 9, 6), date(2026, 9, 6))
    assert st.synced_days("s2", "web")["2026-09-06"][1] is False  # Google said it is still incomplete
    with pytest.raises(ValueError):
        sync_range(_DayClient(), st, "s", date(2026, 9, 4), date(2026, 9, 4), dims=("query", "date"))


def test_sync_time_budget_reports_pending_days(tmp_path, monkeypatch):
    clock = iter(range(0, 10_000, 30))
    monkeypatch.setattr("gsc_mcp_full.sync.time.monotonic", lambda: next(clock))
    res = sync_range(_DayClient(), HistoryStore(tmp_path / "h.sqlite"), "s", date(2026, 1, 1), date(2026, 1, 10), max_seconds=45)
    assert 0 < res["days_fetched"] < 10 and res["days_pending"] == 10 - res["days_fetched"]


# -- inspection --------------------------------------------------------------------


def test_inspection_batch_respects_its_time_budget(tmp_path):
    client = FakeClient()
    client.inspect_delay = 0.4
    st = HistoryStore(tmp_path / "h.sqlite")
    urls = [f"https://example.com/p{i}" for i in range(12)]
    t = time.monotonic()
    res = inspect_many(client, st, SITE, urls, concurrency=2, budget_seconds=0.6)
    assert time.monotonic() - t < 2.5  # returned on the budget, not after 12 × 0.4 s
    skipped = [r for r in res if r.get("skipped")]
    assert skipped and len(res) == 12 and any(r["ok"] for r in res)
    assert st.inspections_today(SITE, __import__("gsc_mcp_full.inspection", fromlist=["utc_day"]).utc_day()) < 12  # unsent URLs cost no quota


# -- tools through the server ------------------------------------------------------


def test_errors_are_real_tool_errors_with_their_reason(server):
    with pytest.raises(ToolError) as e:
        asyncio.run(server.mcp.call_tool("history_sql", {"sql": "SELECT nope FROM rows"}))
    assert "no such column" in str(e.value)  # the model needs this to fix its SQL
    with pytest.raises(ToolError) as e:
        asyncio.run(server.mcp.call_tool("get_property", {"site_url": "nope.com"}))
    assert "No property matches" in str(e.value)
    with pytest.raises(ToolError) as e:
        asyncio.run(server.mcp.call_tool("hourly_performance", {"site_url": SITE, "timezone": "Mars/Olympus"}))
    assert "Mars/Olympus" in str(e.value)


def test_history_variants_are_found(server):
    call(server, "sync_history", site_url=SITE, days=3)
    r = resolve_range(days=3)
    out = call(server, "query_variants", site_url=SITE, source="history", start_date=r.start_iso, end_date=r.end_iso)
    assert "letter-forms" in out and "كولر گازي" in out  # history keeps each spelling so variants can be found


def test_history_totals_cover_all_rows_not_just_the_shown_ones(server):
    call(server, "sync_history", site_url=SITE, days=3)
    r = resolve_range(days=3)
    out = call(server, "history_query", site_url=SITE, start_date=r.start_iso, end_date=r.end_iso, limit=1)
    assert "Stored totals: clicks 69" in out and "3 more rows not shown (of 4)" in out
    assert "no searchappearance" in call(server, "history_query", site_url=SITE, start_date=r.start_iso, end_date=r.end_iso, dimensions="searchAppearance").lower()
    assert "history stores only" in call(server, "history_compare", site_url=SITE, start_date=r.start_iso, end_date=r.end_iso, previous_start="2026-01-01", previous_end="2026-01-03", dimension="searchAppearance")


def test_compare_custom_needs_both_dates(server):
    assert "needs both" in call(server, "compare_periods", site_url=SITE, compare_to="custom")
    assert "compare_to must be" in call(server, "compare_periods", site_url=SITE, compare_to="last_decade")
    assert "Error" not in call(server, "compare_periods", site_url=SITE, compare_to="52_weeks")


def test_24_hour_view_and_granularity(server):
    out = call(server, "hourly_performance", site_url=SITE, hours=24, timezone="Asia/Tehran")
    assert "by local hour" in out and re.search(r"\| \d{4}-\d\d-\d\d \d\d:30 \|", out)  # Tehran hours fall on :30
    monthly = call(server, "performance_overview", site_url=SITE, days=90, granularity="month")
    assert "## By month" in monthly and re.search(r"\| \d{4}-\d\d \|", monthly)
    assert "## By week" in call(server, "performance_overview", site_url=SITE, days=90)
    assert "granularity must be" in call(server, "performance_overview", site_url=SITE, granularity="hour")


def test_tools_declare_whether_they_write(server):
    tools = {t.name: t for t in server.mcp._tool_manager.list_tools()}
    assert all(t.annotations is not None for t in tools.values())
    assert tools["query_search_analytics"].annotations.read_only_hint is True
    assert tools["delete_sitemap"].annotations.destructive_hint is True and tools["delete_sitemap"].annotations.read_only_hint is False
    assert tools["submit_sitemap"].annotations.destructive_hint is False and tools["sync_history"].annotations.read_only_hint is False


def test_http_mode_can_allow_a_proxy_host(monkeypatch):
    from gsc_mcp_full.server import _transport_security

    monkeypatch.delenv("GSC_ALLOWED_HOSTS", raising=False)
    assert _transport_security() is None
    monkeypatch.setenv("GSC_ALLOWED_HOSTS", "mcp.example.com")
    s = _transport_security()
    assert s.enable_dns_rebinding_protection and "mcp.example.com" in s.allowed_hosts and "https://mcp.example.com" in s.allowed_origins


# -- per-page counting --------------------------------------------------------------


def _qp(q, page, clicks, imps, pos):
    return {"query": q, "page": page, "clicks": clicks, "impressions": imps, "position": pos}


def test_section_links_and_sitelinks_are_not_competing_pages():
    rows = [
        # one article and two of its #section links: one result, not three pages
        _qp("used car checklist", "https://x.com/blog/checklist/", 1200, 50000, 3.7),
        _qp("used car checklist", "https://x.com/blog/checklist/#engine", 8, 30000, 3.7),
        _qp("used car checklist", "https://x.com/blog/checklist/#papers", 2, 30000, 3.7),
        # a brand result and its sitelinks: same position, almost the same impressions
        _qp("acme", "https://x.com/", 19000, 24000, 1.0),
        _qp("acme", "https://x.com/store/", 400, 23000, 1.0),
        _qp("acme", "https://x.com/contact/", 60, 22000, 1.0),
        # a real conflict: two pages ranking separately for one keyword
        _qp("boiler repair", "https://x.com/repair/", 50, 600, 3.0),
        _qp("boiler repair", "https://x.com/blog/repair-guide/", 5, 400, 8.0),
    ]
    found = analysis.cannibalization(rows)
    assert [g["query"] for g in found] == ["boiler repair"]
    pages = {r["query"]: r for r in analysis.collapse_pages(rows) if r["page"] in ("https://x.com/", "https://x.com/blog/checklist/")}
    assert pages["acme"]["sitelinks"] == 2 and pages["acme"]["clicks"] == 19460 and pages["acme"]["impressions"] == 24000
    assert pages["used car checklist"]["clicks"] == 1210 and pages["used car checklist"]["impressions"] == 50000  # one impression, not three
    low, _ = analysis.low_ctr(rows, min_impressions=100)
    assert all(r["query"] != "acme" for r in low)  # a sitelink is not a page-one result nobody clicks


def test_occasional_sitelinks_fold_but_alternating_pages_do_not():
    rows = [
        # the homepage is in every search for the brand; /search/ and /login/ show under it only sometimes
        _qp("acme", "https://x.com/", 19000, 24000, 1.0),
        _qp("acme", "https://x.com/search/", 100, 17000, 1.0),
        _qp("acme", "https://x.com/login/", 20, 2000, 1.2),
        # two articles take turns at the same position: each covers part of the searches
        _qp("flu remedy", "https://x.com/blog/flu/", 40, 600, 4.0),
        _qp("flu remedy", "https://x.com/blog/flu-treatment/", 30, 420, 4.1),
    ]
    searches = {"acme": 24200, "flu remedy": 1000}
    found = analysis.cannibalization(rows, query_impressions=searches)
    assert [g["query"] for g in found] == ["flu remedy"]
    home = next(r for r in analysis.collapse_pages(rows, query_impressions=searches) if r["page"] == "https://x.com/")
    assert home["sitelinks"] == 2 and home["clicks"] == 19120
    # without per-search counts only near-identical impressions are folded, so nothing is hidden by guesswork
    assert {g["query"] for g in analysis.cannibalization(rows)} == {"acme", "flu remedy"}


def test_layout_keys_that_type_letters_are_not_separators():
    # On a Persian layout ; , ' \ type letters. Treating them as punctuation paired unrelated queries.
    from gsc_mcp_full.i18n import find_layout_mistypes, remap_from_qwerty

    typed = "\\vhdn ;hv;vni"
    assert remap_from_qwerty(typed, "fa2") == "پراید کارکرده"
    rows = [
        {"query": "پراید کارکرده", "clicks": 900, "impressions": 1000, "position": 1.0},
        {"query": "پرایدکارکرده", "clicks": 90, "impressions": 100, "position": 1.0},  # no space: a different key
        {"query": "وراید کارکرده", "clicks": 5, "impressions": 6, "position": 1.0},  # a typo, not a layout slip
        {"query": typed, "clicks": 29, "impressions": 38, "position": 1.0},
        {"query": "میگو", "clicks": 3, "impressions": 40, "position": 4.0},
        {"query": "ld", "clicks": 1, "impressions": 19, "position": 9.0},  # maps to «می», not to «میگو»
    ]
    hits = find_layout_mistypes(rows)
    assert [(h.query, h.intended) for h in hits] == [(typed, "پراید کارکرده")]


def test_variants_say_how_they_differ_from_the_most_seen_spelling():
    from gsc_mcp_full.i18n import group_queries

    rows = [
        {"query": "آگهی خودرو", "clicks": 70, "impressions": 3000, "position": 8.7},
        {"query": "اگهی خودرو", "clicks": 10, "impressions": 140, "position": 7.9},
    ]
    g = group_queries(rows)[0]
    assert g["canonical"] == "آگهی خودرو"
    assert g["variants"][0]["differs"] == [] and g["variants"][1]["differs"] == ["letter-forms"]


def test_bare_numbers_are_not_terms():
    terms, _ = term_frequency([{"query": "پژو ۲۰۶", "clicks": 1, "impressions": 9}, {"query": "قیمت 207", "clicks": 1, "impressions": 5}], top=10)
    assert {t["term"] for t in terms} == {"پژو", "قیمت"}
