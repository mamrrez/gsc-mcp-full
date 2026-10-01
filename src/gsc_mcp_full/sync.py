"""Pull Search Analytics into the local history store, one day at a time.

A day is fetched with ``dataState: all`` so it matches the UI. It is marked
final — and never fetched again — only when Google says it is complete and it
actually has rows; an empty day stays provisional for a while, because "no
rows yet" is what a processing delay looks like. Fetching per day is what
gets past the per-request row cap: each day gets its own 25,000-row pages.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from datetime import date

from .client import GSCClient, search_type_name
from .dates import is_final, today_pacific
from .store import HistoryStore, check_dims

DEFAULT_DIMS: tuple[str, ...] = ("query", "page")
EMPTY_FINAL_AFTER_DAYS = 10  # an empty day older than this really was empty


def sync_range(
    client: GSCClient,
    store: HistoryStore,
    site: str,
    start: date,
    end: date,
    search_type: str = "web",
    dims: Sequence[str] = DEFAULT_DIMS,
    max_rows_per_day: int = 100_000,
    refresh_provisional: bool = True,
    progress: Callable[[str], None] | None = None,
    max_seconds: float | None = None,
) -> dict:
    """Fetch and store every missing day in [start, end].

    ``max_seconds`` stops early (between days) so a tool call can return before
    its client gives up; the summary then says how many days are still pending.
    """
    st = search_type_name(search_type)
    dims = check_dims(dims)
    days = store.missing_days(site, st, start, end, refresh_provisional, dims)
    deadline = time.monotonic() + max_seconds if max_seconds else None
    today = today_pacific()
    fetched_rows = 0
    done = 0
    for d in days:
        if deadline is not None and done and time.monotonic() > deadline:
            break
        iso = d.isoformat()
        body = {"startDate": iso, "endDate": iso, "dimensions": list(dims), "type": st, "dataState": "all"}
        rows, meta = client.query_all(site, body, max_rows=max_rows_per_day)
        incomplete_from = meta.get("firstIncompleteDate")
        settled = is_final(d) and not (incomplete_from and iso >= incomplete_from)
        has_data = bool(rows) or (today - d).days >= EMPTY_FINAL_AFTER_DAYS
        n = store.replace_day(site, st, iso, dims, rows, final=settled and has_data)
        fetched_rows += n
        done += 1
        if progress:
            progress(f"{iso}: {n:,} rows")
    return {
        "days_requested": (end - start).days + 1,
        "days_fetched": done,
        "days_pending": len(days) - done,
        "rows": fetched_rows,
        "dims": list(dims),
        "search_type": st,
    }
