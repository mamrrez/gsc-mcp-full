"""A fake Search Console and a server wired to it — no network, no credentials."""

import asyncio
import os

import pytest

SITE = "sc-domain:example.com"

# (query, page, country, device), clicks, impressions, position
DATA = [
    (("کولر گازی", "https://example.com/a", "irn", "MOBILE"), 10, 100, 2.0),
    (("كولر گازي", "https://example.com/a", "irn", "DESKTOP"), 2, 40, 3.0),
    (("کولر گازی", "https://example.com/b", "irn", "MOBILE"), 1, 30, 9.0),
    (("sghl", "https://example.com/a", "irn", "MOBILE"), 0, 5, 12.0),
    (("سلام", "https://example.com/c", "irn", "MOBILE"), 4, 50, 4.0),
    (("پکیج دیواری", "https://example.com/d", "irn", "MOBILE"), 6, 400, 11.0),
]
IDX = {"query": 0, "page": 1, "country": 2, "device": 3}


class FakeClient:
    """Enough of GSCClient for the tools to run. Returns Persian data with spelling variants."""

    dead = False

    def __init__(self, data=None):
        self.data = list(data or DATA)
        self.bodies = []
        self.inspect_delay = 0.0

    def sites_list(self):
        return [{"siteUrl": SITE, "permissionLevel": "siteOwner"}]

    def site_get(self, site):
        return {"siteUrl": site, "permissionLevel": "siteOwner"}

    def query_all(self, site, body, max_rows=25000):
        self.bodies.append(dict(body))
        dims = body.get("dimensions", [])
        data = self.data
        for g in body.get("dimensionFilterGroups", []):
            for f in g["filters"]:
                if f["dimension"] == "page" and f["operator"] == "contains":
                    data = [d for d in data if f["expression"] in d[0][1]]
                elif f["dimension"] == "page" and f["operator"] == "equals":
                    data = [d for d in data if f["expression"] == d[0][1]]
        meta = {"firstIncompleteDate": body["endDate"]}
        if not dims:  # no dimensions: one row of totals, as the real API answers
            if not data:
                return [], meta
            c, i = sum(d[1] for d in data), sum(d[2] for d in data)
            return [{"keys": [], "clicks": c, "impressions": i, "ctr": c / i, "position": sum(d[3] * d[2] for d in data) / i}], meta
        rows = []
        for keys, c, i, p in data:
            if "date" in dims:
                k = [body["startDate"]]
            elif "hour" in dims:
                k = [f"{body['startDate']}T14:00:00-07:00"]
            else:
                k = [keys[IDX[d]] for d in dims]
            rows.append({"keys": k, "clicks": c, "impressions": i, "ctr": c / i, "position": p})
        return rows[:max_rows], meta

    def sitemaps_list(self, site, index=None):
        return [{"path": "https://example.com/sitemap.xml", "lastSubmitted": "2026-09-01T00:00:00Z", "isPending": False, "isSitemapsIndex": True, "errors": "0", "warnings": "1", "contents": [{"type": "web", "submitted": "50"}]}]

    def sitemap_get(self, site, feed):
        return self.sitemaps_list(site)[0]

    def inspect(self, site, url, language_code="en-US", timeout=30.0):
        import time

        if self.inspect_delay:
            time.sleep(self.inspect_delay)
        bad = url.endswith("/b")
        return {
            "indexStatusResult": {"verdict": "NEUTRAL" if bad else "PASS", "coverageState": "Discovered - currently not indexed" if bad else "Submitted and indexed", "robotsTxtState": "ALLOWED", "pageFetchState": "SUCCESSFUL", "googleCanonical": url, "userCanonical": url, "lastCrawlTime": "2026-09-20T01:02:03Z", "crawledAs": "MOBILE"},
            "richResultsResult": {"verdict": "FAIL" if bad else "PASS", "detectedItems": [{"richResultType": "Product", "items": [{"issues": [{"issueMessage": "Missing field", "severity": "ERROR"}] if bad else []}]}]},
            "inspectionResultLink": "https://search.google.com/search-console/inspect?x",
        }


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    cfg = tmp_path_factory.mktemp("cfg")
    os.environ["GSC_CONFIG_DIR"] = str(cfg)
    os.environ["GSC_LANG"] = "fa"
    for var in ("GSC_ALLOW_WRITE", "GSC_SCOPE", "GSC_DB_PATH", "GSC_TOKEN_PATH", "GSC_CREDENTIALS_PATH"):
        os.environ.pop(var, None)
    from gsc_mcp_full import server as srv
    from gsc_mcp_full.settings import Settings
    from gsc_mcp_full.store import HistoryStore

    srv.rt.settings = Settings.from_env()
    srv.rt._client = FakeClient()
    srv.rt._store = HistoryStore(cfg / "h.sqlite")
    srv.rt._sites = None
    return srv


def call(server, name, **args) -> str:
    """Run a tool; a tool error comes back as text starting with 'Error:' so tests can assert on it."""
    from gsc_mcp_full.runtime import ToolError

    try:
        res = asyncio.run(server.mcp.call_tool(name, args))
    except ToolError as e:
        return f"Error: {e}"
    return "\n".join(getattr(c, "text", "") for c in res.content)
