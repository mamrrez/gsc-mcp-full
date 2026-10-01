from datetime import date

import pytest

from gsc_mcp_full import analysis
from gsc_mcp_full.dates import DateRange, bucket_hours, resolve_range
from gsc_mcp_full.store import HistoryStore

# -- analysis ----------------------------------------------------------------------


def _r(q, page="", clicks=0, imps=0, pos=1.0):
    d = {"query": q, "clicks": clicks, "impressions": imps, "ctr": clicks / imps if imps else 0, "position": pos}
    if page:
        d["page"] = page
    return d


def test_totals_weight_position_by_impressions():
    t = analysis.totals([_r("a", imps=100, pos=1.0), _r("b", imps=300, pos=5.0)])
    assert t["position"] == 4.0 and t["impressions"] == 400


def test_aggregate_merges_spellings_and_keeps_most_seen():
    rows = [_r("کولر", clicks=1, imps=10, pos=3), _r("كولر", clicks=5, imps=90, pos=2)]
    g = analysis.aggregate(rows, ("query",))
    assert len(g) == 1 and g[0]["query"] == "كولر" and g[0]["variants"] == 2 and g[0]["clicks"] == 6


def test_compare_marks_new_lost_and_deltas():
    cur = [_r("a", clicks=10, imps=100, pos=2), _r("b", clicks=5, imps=50, pos=4)]
    prev = [_r("a", clicks=20, imps=100, pos=3), _r("c", clicks=7, imps=70, pos=6)]
    cmp = analysis.compare(cur, prev)
    by = {r["query"]: r for r in cmp["rows"]}
    assert by["a"]["delta_clicks"] == -10 and by["a"]["delta_position"] == 1.0
    assert by["b"]["status"] == "new" and by["c"]["status"] == "lost"
    assert cmp["rows"][0]["query"] == "a"  # biggest absolute mover first


def test_cannibalization_merges_spellings_across_pages():
    rows = [
        _r("کولر گازی", "/a", clicks=5, imps=60, pos=3),
        _r("كولر گازي", "/b", clicks=1, imps=40, pos=8),
        _r("پکیج", "/c", clicks=1, imps=100, pos=1),
    ]
    out = analysis.cannibalization(rows, min_impressions=20)
    assert len(out) == 1
    g = out[0]
    assert g["best_page"] == "/a" and g["competing_impressions"] == 40 and g["impressions"] == 100


def test_striking_distance_and_potential():
    rows = [_r("x", "/p", clicks=1, imps=200, pos=12.0), _r("y", "/p", clicks=50, imps=200, pos=1.5)]
    hits = analysis.striking_distance(rows)
    assert [h["query"] for h in hits] == ["x"] and hits[0]["potential_clicks"] == int(200 * 0.07) - 1


def test_low_ctr_uses_benchmark_when_few_rows():
    rows = [_r("x", "/p", clicks=0, imps=1000, pos=1.0), _r("y", "/q", clicks=300, imps=1000, pos=1.0)]
    hits, method = analysis.low_ctr(rows)
    assert method == "benchmark CTR curve" and [h["query"] for h in hits] == ["x"]


def test_brand_split_matches_every_script():
    rows = [_r("midea aircon", clicks=5, imps=50), _r("کولر مدیا", clicks=3, imps=30), _r("كولر مديا", clicks=2, imps=20), _r("hvac", clicks=10, imps=100)]
    r = analysis.brand_split(rows, ["Midea", "مدیا"])
    assert r["brand"]["clicks"] == 10 and r["non_brand"]["clicks"] == 10 and r["brand_click_share"] == 0.5


def test_language_breakdown():
    rows = [_r("کولر", clicks=3, imps=30), _r("aircon", clicks=1, imps=10), _r("空调", clicks=0, imps=5)]
    br = analysis.language_breakdown(rows)
    assert br[0]["lang"] == "fa" and br[0]["click_share"] == 0.75


def test_movers_buckets():
    cur = [_r("/a", clicks=5), _r("/b", clicks=40), _r("/d", clicks=15)]
    prev = [_r("/a", clicks=20), _r("/b", clicks=20), _r("/c", clicks=12)]
    for r in cur + prev:
        r["page"] = r.pop("query")
    m = analysis.movers(cur, prev, ("page",))
    assert [r["page"] for r in m["decayed"]] == ["/a"]
    assert [r["page"] for r in m["rising"]] == ["/b"]
    assert [r["page"] for r in m["lost"]] == ["/c"] and [r["page"] for r in m["new"]] == ["/d"]


# -- dates -------------------------------------------------------------------------


def test_resolve_range_defaults_and_periods():
    r = resolve_range(days=7)
    assert r.days == 7
    assert resolve_range(period="last_28_days").days == 28
    assert resolve_range(start="2026-01-01", end="2026-01-31").days == 31
    with pytest.raises(ValueError):
        resolve_range(start="2026-02-01", end="2026-01-01")
    with pytest.raises(ValueError):
        resolve_range(period="last_week_ish")


def test_previous_and_year_ago():
    r = DateRange(date(2026, 3, 1), date(2026, 3, 28))
    assert r.previous() == DateRange(date(2026, 2, 1), date(2026, 2, 28))
    assert r.year_ago() == DateRange(date(2025, 3, 1), date(2025, 3, 28))  # the same calendar dates
    assert r.weeks_52_ago().start == date(2025, 3, 2)  # 364 days keeps weekdays aligned
    assert DateRange(date(2024, 2, 29), date(2024, 2, 29)).year_ago().start == date(2023, 2, 28)


def test_bucket_hours_into_local_days():
    rows = [
        {"keys": ["2026-09-20T14:00:00-07:00"], "clicks": 1, "impressions": 10, "position": 2.0},  # 21 Sep 00:30 Tehran
        {"keys": ["2026-09-20T12:00:00-07:00"], "clicks": 1, "impressions": 10, "position": 4.0},  # 20 Sep 22:30 Tehran
    ]
    b = bucket_hours(rows, "Asia/Tehran")
    assert [x["bucket"] for x in b] == ["2026-09-20", "2026-09-21"]
    assert bucket_hours(rows, "America/Los_Angeles")[0]["impressions"] == 20


# -- store -------------------------------------------------------------------------


def test_store_roundtrip_grouping_and_sql(tmp_path):
    st = HistoryStore(tmp_path / "h.sqlite")
    api_rows = [
        {"keys": ["کولر گازی", "https://x.com/a"], "clicks": 3, "impressions": 30, "position": 2.0},
        {"keys": ["كولر گازي", "https://x.com/a"], "clicks": 1, "impressions": 10, "position": 4.0},
        {"keys": ["پکیج", "https://x.com/b"], "clicks": 2, "impressions": 20, "position": 5.0},
    ]
    n = st.replace_day("sc-domain:x.com", "web", "2026-09-01", ("query", "page"), api_rows, final=True)
    assert n == 3
    rows = st.rows("sc-domain:x.com", "2026-09-01", "2026-09-30", by=("query",))
    assert rows[0]["clicks"] == 4 and rows[0]["impressions"] == 40  # spellings merged by qkey
    assert st.rows("sc-domain:x.com", "2026-09-01", "2026-09-30", by=("query",), query_contains="كولر")[0]["clicks"] == 4
    cov = st.coverage("sc-domain:x.com")
    assert cov[0].days == 1 and cov[0].rows == 3 and cov[0].final_days == 1
    assert st.missing_days("sc-domain:x.com", "web", date(2026, 9, 1), date(2026, 9, 3)) == [date(2026, 9, 2), date(2026, 9, 3)]
    cols, data = st.sql("SELECT COUNT(*) AS n FROM rows")
    assert cols == ["n"] and data[0][0] == 3
    with pytest.raises(ValueError):
        st.sql("DELETE FROM rows")
    tr = st.trend("sc-domain:x.com", "2026-09-01", "2026-09-30", granularity="month")
    assert tr[0]["bucket"] == "2026-09" and tr[0]["clicks"] == 6


def test_store_replace_day_is_idempotent(tmp_path):
    st = HistoryStore(tmp_path / "h.sqlite")
    rows = [{"keys": ["q", "p"], "clicks": 1, "impressions": 1, "position": 1.0}]
    st.replace_day("s", "web", "2026-01-01", ("query", "page"), rows, final=False)
    st.replace_day("s", "web", "2026-01-01", ("query", "page"), rows, final=True)
    assert st.sql("SELECT COUNT(*) FROM rows")[1][0][0] == 1
    assert st.inspections_today("s", "2026-01-01") == 0
    assert st.add_inspections("s", "2026-01-01", 5) == 5 and st.add_inspections("s", "2026-01-01", 2) == 7
