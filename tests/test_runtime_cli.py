"""What the server actually sends to Google, and how the CLI is invoked."""

from datetime import date

from gsc_mcp_full import cli
from gsc_mcp_full.dates import DateRange, today_pacific
from gsc_mcp_full.runtime import Runtime
from gsc_mcp_full.settings import Settings
from gsc_mcp_full.store import HistoryStore


class Recorder:
    def __init__(self):
        self.bodies = []

    def query_all(self, site, body, max_rows=25000):
        self.bodies.append((site, dict(body), max_rows))
        return [], {}


def _rt(tmp_path, monkeypatch) -> tuple[Runtime, Recorder]:
    monkeypatch.setenv("GSC_CONFIG_DIR", str(tmp_path))
    for var in ("GSC_DATA_STATE", "GSC_ALLOW_WRITE", "GSC_SCOPE", "GSC_ROW_CAP"):
        monkeypatch.delenv(var, raising=False)
    rt = Runtime(Settings.from_env())
    rec = Recorder()
    rt._client = rec
    return rt, rec


RNG = DateRange(date(2026, 9, 1), date(2026, 9, 7))


def test_fetch_sends_api_shaped_filters(tmp_path, monkeypatch):
    rt, rec = _rt(tmp_path, monkeypatch)
    rt.fetch("sc-domain:x.com", RNG, ["query", "page"], "web", query_filter="کولر", page_filter="/blog/", country="IRN", device="mobile")
    _, body, _ = rec.bodies[0]
    assert body["startDate"] == "2026-09-01" and body["endDate"] == "2026-09-07"
    assert body["dimensions"] == ["query", "page"] and body["type"] == "web" and body["dataState"] == "all"
    by_dim = {f["dimension"]: f for f in body["dimensionFilterGroups"][0]["filters"]}
    assert by_dim["device"]["expression"] == "MOBILE"  # the API documents DESKTOP / MOBILE / TABLET
    assert by_dim["country"]["expression"] == "irn"  # and returns countries in lower case
    assert by_dim["page"] == {"dimension": "page", "operator": "contains", "expression": "/blog/"}
    assert by_dim["query"]["operator"] == "includingRegex" and "[کك]" in by_dim["query"]["expression"]


def test_hour_dimension_forces_hourly_all_and_type_aliases(tmp_path, monkeypatch):
    rt, rec = _rt(tmp_path, monkeypatch)
    rt.fetch("s", RNG, ["hour"], "google_news", data_state="final")
    _, body, _ = rec.bodies[0]
    assert body["dataState"] == "hourly_all" and body["type"] == "googleNews"
    assert "dimensionFilterGroups" not in body


def test_row_cap_is_enforced(tmp_path, monkeypatch):
    rt, rec = _rt(tmp_path, monkeypatch)
    rt.fetch("s", RNG, ["query"], max_rows=10**9)
    assert rec.bodies[0][2] == rt.settings.row_cap


def test_hourly_range_runs_through_today(tmp_path, monkeypatch):
    rt, _ = _rt(tmp_path, monkeypatch)
    assert rt.range(3, None, None, lag=0).end == today_pacific()
    assert rt.range(3, None, None).end < today_pacific()


def test_write_flag_implies_full_scope(tmp_path, monkeypatch):
    monkeypatch.setenv("GSC_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("GSC_SCOPE", raising=False)
    monkeypatch.delenv("GSC_ALLOW_WRITE", raising=False)
    assert Settings.from_env().scope == "readonly" and not Settings.from_env().allow_write
    monkeypatch.setenv("GSC_ALLOW_WRITE", "1")
    st = Settings.from_env()
    assert st.allow_write and st.scope == "full" and st.scope_url.endswith("/webmasters")


def test_history_shows_most_seen_spelling_and_filters_country(tmp_path):
    st = HistoryStore(tmp_path / "h.sqlite")
    rows = [
        {"keys": ["كولر", "p", "irn", "MOBILE"], "clicks": 1, "impressions": 5, "position": 3.0},
        {"keys": ["کولر", "p", "irn", "MOBILE"], "clicks": 9, "impressions": 90, "position": 2.0},
        {"keys": ["کولر", "p", "deu", "DESKTOP"], "clicks": 1, "impressions": 4, "position": 8.0},
    ]
    st.replace_day("s", "web", "2026-09-01", ("query", "page", "country", "device"), rows, final=True)
    out = st.rows("s", "2026-09-01", "2026-09-01", by=("query",))
    assert len(out) == 1 and out[0]["query"] == "کولر" and out[0]["impressions"] == 99 and "_top" not in out[0]
    assert st.rows("s", "2026-09-01", "2026-09-01", by=("query",), country="IRN")[0]["impressions"] == 95
    assert st.rows("s", "2026-09-01", "2026-09-01", by=("query",), device="desktop")[0]["impressions"] == 4


def test_cli_defaults_to_serve(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "_serve", lambda args: seen.update(transport=args.transport, port=args.port) or 0)
    assert cli.main([]) == 0 and seen == {"transport": "stdio", "port": 8000}
    assert cli.main(["--transport", "streamable-http", "--port", "9123"]) == 0
    assert seen == {"transport": "streamable-http", "port": 9123}
    assert cli.main(["serve", "--port", "7"]) == 0 and seen["port"] == 7
