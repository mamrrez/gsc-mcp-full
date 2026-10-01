"""URL Inspection: concurrent, quota-aware, time-boxed, flattened.

Google allows about 2,000 inspections per property per day and 600 per
minute. The count is tracked locally so a big batch is refused *before* it
burns the day's quota on a typo. One inspection takes 2–10 seconds, so a
batch also gets a time budget: whatever is not finished in time is reported
as not inspected instead of making the whole call time out in the client.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone

from .client import GSCClient, GSCError
from .store import HistoryStore

DAILY_QUOTA = 2000
MAX_BATCH = 50
DEFAULT_BUDGET = 45.0  # seconds; MCP clients commonly give a tool call 60


def utc_day() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def flatten(result: dict) -> dict:
    """Pull the useful fields out of an inspection result."""
    idx = result.get("indexStatusResult", {}) or {}
    rich = result.get("richResultsResult", {}) or {}
    mobile = result.get("mobileUsabilityResult", {}) or {}
    amp = result.get("ampResult", {}) or {}
    issues = []
    for item in rich.get("detectedItems", []) or []:
        for it in item.get("items", []) or []:
            for iss in it.get("issues", []) or []:
                issues.append(f"{item.get('richResultType', '?')}: {iss.get('issueMessage', '?')} ({iss.get('severity', '?')})")
    return {
        "verdict": idx.get("verdict", "UNKNOWN"),
        "coverage": idx.get("coverageState", ""),
        "indexing_state": idx.get("indexingState", ""),
        "page_fetch": idx.get("pageFetchState", ""),
        "robots": idx.get("robotsTxtState", ""),
        "last_crawl": idx.get("lastCrawlTime", ""),
        "crawled_as": idx.get("crawledAs", ""),
        "google_canonical": idx.get("googleCanonical", ""),
        "user_canonical": idx.get("userCanonical", ""),
        "referring_urls": len(idx.get("referringUrls", []) or []),
        "sitemaps": idx.get("sitemap", []) or [],
        "rich_results": rich.get("verdict", ""),
        "rich_result_types": [d.get("richResultType", "") for d in rich.get("detectedItems", []) or []],
        "rich_result_issues": issues,
        "mobile": mobile.get("verdict", ""),
        "amp": amp.get("verdict", ""),
        "link": result.get("inspectionResultLink", ""),
    }


def canonical_mismatch(flat: dict) -> bool:
    return bool(flat["google_canonical"] and flat["user_canonical"] and flat["google_canonical"] != flat["user_canonical"])


def rich_results_failing(flat: dict) -> bool:
    """Structured data Google is rejecting, or has raised issues on."""
    return flat["rich_results"] == "FAIL" or bool(flat["rich_result_issues"])


def inspect_many(
    client: GSCClient,
    store: HistoryStore | None,
    site: str,
    urls: list[str],
    concurrency: int = 8,
    language: str = "en-US",
    budget_seconds: float = DEFAULT_BUDGET,
) -> list[dict]:
    """Inspect ``urls`` concurrently. Each result is ``{"url", "ok", "data" | "error"}``.

    URLs that the time budget did not reach come back with ``ok: False`` and
    ``skipped: True``; they used no quota and can simply be sent again.
    """
    urls = [u.strip() for u in urls if u.strip()]
    if not urls:
        raise GSCError("Give at least one URL to inspect.")
    if len(urls) > MAX_BATCH:
        raise GSCError(f"At most {MAX_BATCH} URLs per call (you gave {len(urls)}); the daily quota is {DAILY_QUOTA}.")
    if store is not None:
        used = store.inspections_today(site, utc_day())
        if used + len(urls) > DAILY_QUOTA:
            raise GSCError(
                f"This would exceed the daily URL Inspection quota for {site}: {used} used today, "
                f"{len(urls)} requested, {DAILY_QUOTA} allowed."
            )

    def one(u: str) -> dict:
        try:
            return {"url": u, "ok": True, "data": flatten(client.inspect(site, u, language))}
        except GSCError as e:
            return {"url": u, "ok": False, "error": str(e)}

    ex = ThreadPoolExecutor(max_workers=max(1, min(int(concurrency), 10)))
    try:
        futures = [(u, ex.submit(one, u)) for u in urls]
        wait([f for _, f in futures], timeout=budget_seconds)
        results, started = [], 0
        for u, f in futures:
            if f.done() and not f.cancelled():
                started += 1
                results.append(f.result())
            elif f.cancel():
                results.append({"url": u, "ok": False, "skipped": True, "error": "not inspected — time budget reached; send this URL again"})
            else:  # still running: the request was sent, so it counts against quota
                started += 1
                results.append({"url": u, "ok": False, "skipped": True, "error": "still running when the time budget ended; try again"})
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    if store is not None and started:
        store.add_inspections(site, utc_day(), started)
    return results
