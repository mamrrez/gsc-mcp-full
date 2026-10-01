"""Local history: Search Analytics rows kept in SQLite, forever.

Google keeps 16 months and caps what one request can return. Syncing each
day's rows into this store removes both limits: a year-over-year comparison
in month 20 works, and every row the API will give is kept. Rows carry a
``qkey`` (the multilingual match key) so grouping across spellings is one
``GROUP BY`` away.

The store is a single file (``GSC_DB_PATH``, default
``~/.config/gsc-mcp-full/history.sqlite``). Nothing in it is secret — it is
the same data Search Console shows — but it is the user's data, so it is
created readable by its owner only.

One caveat the numbers inherit from Google: rows that carry the query
dimension leave out anonymised (rare) queries, so totals computed from the
store are lower than the totals Search Console shows for the same period.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import threading
import time
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .i18n import match_key

DIMENSIONS = ("query", "page", "country", "device")
_INIT_LOCK = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS rows (
    site TEXT NOT NULL,
    search_type TEXT NOT NULL,
    date TEXT NOT NULL,
    query TEXT NOT NULL DEFAULT '',
    qkey TEXT NOT NULL DEFAULT '',
    page TEXT NOT NULL DEFAULT '',
    country TEXT NOT NULL DEFAULT '',
    device TEXT NOT NULL DEFAULT '',
    clicks INTEGER NOT NULL,
    impressions INTEGER NOT NULL,
    position REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS rows_day ON rows (site, search_type, date);
CREATE INDEX IF NOT EXISTS rows_qkey ON rows (site, qkey);
CREATE INDEX IF NOT EXISTS rows_page ON rows (site, page);
CREATE TABLE IF NOT EXISTS sync_days (
    site TEXT NOT NULL,
    search_type TEXT NOT NULL,
    date TEXT NOT NULL,
    dims TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    final INTEGER NOT NULL,
    synced_at TEXT NOT NULL,
    PRIMARY KEY (site, search_type, date)
);
CREATE TABLE IF NOT EXISTS inspections (
    site TEXT NOT NULL,
    day TEXT NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY (site, day)
);
"""


def default_db_path() -> Path:
    env = os.environ.get("GSC_DB_PATH")
    if env:
        return Path(os.path.expanduser(env))
    base = os.environ.get("GSC_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".config", "gsc-mcp-full")
    return Path(base) / "history.sqlite"


def check_dims(dims: Sequence[str]) -> tuple[str, ...]:
    """The dimensions the store can hold, lower-cased; anything else is an error, not a silent drop."""
    out = tuple(d.strip().lower() for d in dims if d.strip())
    bad = [d for d in out if d not in DIMENSIONS]
    if bad or not out:
        raise ValueError(f"history stores only {', '.join(DIMENSIONS)}; cannot use {', '.join(bad) or 'an empty list'}")
    return out


@dataclass(frozen=True)
class Coverage:
    search_type: str
    first: str
    last: str
    days: int
    final_days: int
    rows: int
    dims: str


class HistoryStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else default_db_path()
        if not self.path.parent.exists():
            # Only a directory this call creates is made private: GSC_DB_PATH may
            # point into a shared directory whose permissions are not ours to change.
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with contextlib.suppress(OSError):
                os.chmod(self.path.parent, 0o700)
        with _INIT_LOCK:
            self._init_schema()
        self._protect()

    def _init_schema(self) -> None:
        """Create the tables, tolerating another thread or process doing the same.

        Switching a new file to WAL needs an exclusive lock that SQLite refuses
        at once rather than waiting for — which is what the server starting
        while a cron ``sync`` runs looks like. So: only switch when needed, and retry.
        """
        delay = 0.05
        for attempt in range(8):
            try:
                with self._tx() as c:
                    if str(c.execute("PRAGMA journal_mode").fetchone()[0]).lower() != "wal":
                        c.execute("PRAGMA journal_mode=WAL")
                    c.executescript(_SCHEMA)
                return
            except sqlite3.OperationalError as e:
                busy = "locked" in str(e).lower() or "busy" in str(e).lower()
                if not busy or attempt == 7:
                    raise
                time.sleep(delay)
                delay *= 2

    @contextlib.contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        """One connection per call (the tools run on several threads), committed and closed."""
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        try:
            with c:
                yield c
        finally:
            c.close()

    def _protect(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            with contextlib.suppress(OSError):
                os.chmod(str(self.path) + suffix, 0o600)

    # -- writing -----------------------------------------------------------

    def synced_days(self, site: str, search_type: str) -> dict[str, tuple[int, bool, frozenset[str]]]:
        with self._tx() as c:
            return {
                r["date"]: (r["row_count"], bool(r["final"]), frozenset(r["dims"].split(",")))
                for r in c.execute("SELECT date, row_count, final, dims FROM sync_days WHERE site=? AND search_type=?", (site, search_type))
            }

    def replace_day(self, site: str, search_type: str, day: str, dims: Sequence[str], rows: Iterable[dict], final: bool) -> int:
        """Store one day's rows, replacing whatever was there for that day."""
        dims = check_dims(dims)
        recs = []
        for r in rows:
            keys = dict(zip(dims, r.get("keys", [])))
            q = keys.get("query", "")
            recs.append(
                (
                    site, search_type, day, q, match_key(q) if q else "", keys.get("page", ""),
                    keys.get("country", ""), keys.get("device", ""),
                    int(r.get("clicks", 0)), int(r.get("impressions", 0)), float(r.get("position", 0)),
                )
            )
        with self._tx() as c:
            c.execute("DELETE FROM rows WHERE site=? AND search_type=? AND date=?", (site, search_type, day))
            c.executemany(
                "INSERT INTO rows (site, search_type, date, query, qkey, page, country, device, clicks, impressions, position) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                recs,
            )
            c.execute(
                "INSERT OR REPLACE INTO sync_days (site, search_type, date, dims, row_count, final, synced_at) VALUES (?,?,?,?,?,?,datetime('now'))",
                (site, search_type, day, ",".join(dims), len(recs), int(final)),
            )
        self._protect()
        return len(recs)

    # -- reading -----------------------------------------------------------

    def coverage(self, site: str | None = None) -> list[Coverage]:
        sql = "SELECT site, search_type, MIN(date) f, MAX(date) l, COUNT(*) d, SUM(final) fd, SUM(row_count) r, MAX(dims) dims FROM sync_days"
        args: tuple = ()
        if site:
            sql += " WHERE site=?"
            args = (site,)
        sql += " GROUP BY site, search_type ORDER BY site, search_type"
        with self._tx() as c:
            return [Coverage(f"{r['site']} · {r['search_type']}" if not site else r["search_type"], r["f"], r["l"], r["d"], r["fd"] or 0, r["r"] or 0, r["dims"]) for r in c.execute(sql, args)]

    def sites(self) -> list[str]:
        with self._tx() as c:
            return [r["site"] for r in c.execute("SELECT DISTINCT site FROM sync_days ORDER BY site")]

    def missing_days(
        self,
        site: str,
        search_type: str,
        start: date,
        end: date,
        refresh_provisional: bool = True,
        dims: Sequence[str] | None = None,
    ) -> list[date]:
        """Days in [start, end] to fetch: not stored, still provisional, or stored with fewer dimensions than now asked for."""
        have = self.synced_days(site, search_type)
        want = frozenset(dims or ())
        out = []
        d = start
        while d <= end:
            got = have.get(d.isoformat())
            if got is None or (refresh_provisional and not got[1]) or not want <= got[2]:
                out.append(d)
            d = d.fromordinal(d.toordinal() + 1)
        return out

    @staticmethod
    def _where(
        site: str,
        search_type: str,
        start: str,
        end: str,
        query_contains: str | None = None,
        page_contains: str | None = None,
        country: str | None = None,
        device: str | None = None,
    ) -> tuple[str, list]:
        where = ["site=?", "search_type=?", "date BETWEEN ? AND ?"]
        args: list = [site, search_type, start, end]
        if query_contains:
            key = match_key(query_contains)
            if not key:
                raise ValueError("query_contains needs at least one letter or digit")
            where.append("instr(qkey, ?) > 0")
            args.append(key)
        if page_contains:
            # instr, not LIKE: a URL is full of % and _ which LIKE treats as wildcards.
            where.append("instr(page, ?) > 0")
            args.append(page_contains)
        if country:
            where.append("country=?")
            args.append(country.lower())  # the API returns country codes in lower case
        if device:
            where.append("device=?")
            args.append(device.upper())
        return " AND ".join(where), args

    def rows(
        self,
        site: str,
        start: str,
        end: str,
        search_type: str = "web",
        by: Sequence[str] = ("query",),
        query_contains: str | None = None,
        page_contains: str | None = None,
        country: str | None = None,
        device: str | None = None,
        limit: int = 5000,
        merge_spellings: bool = True,
    ) -> list[dict]:
        """Aggregated rows for a range, grouped by ``by``.

        Queries are grouped by match key and shown as their most-seen spelling;
        pass ``merge_spellings=False`` to get one row per spelling instead
        (what ``query_variants`` needs). ``query_contains`` is matched against
        the match key, so it finds every spelling and works for Chinese or
        Japanese without word boundaries.
        """
        by = tuple(b for b in by if b in DIMENSIONS or b == "date")
        cols, group = [], []
        for b in by:
            if b == "query" and merge_spellings:
                # SQLite fills a bare column from the row holding the MAX(): the most-seen spelling.
                cols += ["query", "MAX(impressions) AS _top"]
                group.append("qkey")
            else:
                cols.append(b)
                group.append(b)
        select = ", ".join(cols + ["SUM(clicks) AS clicks", "SUM(impressions) AS impressions", "SUM(position*impressions)/NULLIF(SUM(impressions),0) AS position"])
        where, args = self._where(site, search_type, start, end, query_contains, page_contains, country, device)
        sql = f"SELECT {select} FROM rows WHERE {where}"
        if group:
            sql += " GROUP BY " + ", ".join(group)
        sql += " ORDER BY clicks DESC, impressions DESC LIMIT ?"
        args.append(int(limit))
        with self._tx() as c:
            out = []
            for r in c.execute(sql, args):
                d = dict(r)
                i = d.get("impressions") or 0
                d["ctr"] = round((d.get("clicks") or 0) / i, 4) if i else 0.0
                d["position"] = round(d.get("position") or 0.0, 2)
                d.pop("_top", None)
                out.append(d)
            return out

    def totals(self, site: str, start: str, end: str, search_type: str = "web", **filters) -> dict:
        """Totals over every stored row that matches — not just the rows a report shows."""
        where, args = self._where(site, search_type, start, end, **filters)
        sql = f"SELECT SUM(clicks) c, SUM(impressions) i, SUM(position*impressions) pw FROM rows WHERE {where}"
        with self._tx() as c:
            r = c.execute(sql, args).fetchone()
        clicks, imps = r["c"] or 0, r["i"] or 0
        return {
            "clicks": clicks,
            "impressions": imps,
            "ctr": round(clicks / imps, 4) if imps else 0.0,
            "position": round((r["pw"] or 0.0) / imps, 2) if imps else 0.0,
        }

    def count_groups(self, site: str, start: str, end: str, search_type: str = "web", by: Sequence[str] = ("query",), **filters) -> int:
        group = ["qkey" if b == "query" else b for b in by if b in DIMENSIONS or b == "date"]
        where, args = self._where(site, search_type, start, end, **filters)
        inner = f"SELECT 1 FROM rows WHERE {where}" + (" GROUP BY " + ", ".join(group) if group else "")
        with self._tx() as c:
            return c.execute(f"SELECT COUNT(*) FROM ({inner})", args).fetchone()[0]

    def trend(
        self,
        site: str,
        start: str,
        end: str,
        search_type: str = "web",
        granularity: str = "week",
        query_contains: str | None = None,
        page_contains: str | None = None,
    ) -> list[dict]:
        if granularity not in ("day", "week", "month"):
            raise ValueError("granularity must be day, week or month")
        where, args = self._where(site, search_type, start, end, query_contains, page_contains)
        sql = f"SELECT date, SUM(clicks) c, SUM(impressions) i, SUM(position*impressions) pw FROM rows WHERE {where} GROUP BY date ORDER BY date"
        with self._tx() as c:
            daily = c.execute(sql, args).fetchall()
        return bucket_days([{"date": r["date"], "clicks": r["c"] or 0, "impressions": r["i"] or 0, "_pw": r["pw"] or 0.0} for r in daily], granularity)

    def sql(self, query: str, limit: int = 200) -> tuple[list[str], list[tuple]]:
        """Run a read-only SELECT against the store (opened in read-only mode)."""
        q = query.strip().rstrip(";")
        if not q.lower().startswith(("select", "with")):
            raise ValueError("only SELECT queries are allowed")
        # as_uri() percent-encodes the path; a raw path containing # or ? would open another file.
        c = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
        try:
            cur = c.execute(q)
            cols = [d[0] for d in cur.description] if cur.description else []
            return cols, cur.fetchmany(int(limit))
        finally:
            c.close()

    # -- URL inspection quota ---------------------------------------------

    def inspections_today(self, site: str, day: str) -> int:
        with self._tx() as c:
            r = c.execute("SELECT count FROM inspections WHERE site=? AND day=?", (site, day)).fetchone()
            return r["count"] if r else 0

    def add_inspections(self, site: str, day: str, n: int) -> int:
        with self._tx() as c:
            c.execute(
                "INSERT INTO inspections (site, day, count) VALUES (?,?,?) ON CONFLICT(site, day) DO UPDATE SET count = count + excluded.count",
                (site, day, n),
            )
            return c.execute("SELECT count FROM inspections WHERE site=? AND day=?", (site, day)).fetchone()["count"]


def bucket_days(daily: Iterable[dict], granularity: str) -> list[dict]:
    """Daily totals rolled up into day, ISO-week or month buckets.

    Each input needs ``date``, ``clicks``, ``impressions`` and either ``_pw``
    (position × impressions) or ``position``. ISO weeks are used so the week
    containing 1 January is not split in two.
    """
    agg: dict[str, dict] = {}
    for r in daily:
        day = r["date"]
        if granularity == "day":
            b = day
        elif granularity == "month":
            b = day[:7]
        elif granularity == "week":
            y, w, _ = date.fromisoformat(day).isocalendar()
            b = f"{y}-W{w:02d}"
        else:
            raise ValueError("granularity must be day, week or month")
        a = agg.setdefault(b, {"bucket": b, "clicks": 0, "impressions": 0, "_pw": 0.0, "days": 0})
        imps = int(r.get("impressions", 0) or 0)
        a["clicks"] += int(r.get("clicks", 0) or 0)
        a["impressions"] += imps
        a["_pw"] += r["_pw"] if "_pw" in r else float(r.get("position", 0) or 0) * imps
        a["days"] += 1
    out = []
    for b in sorted(agg):
        a = agg[b]
        imps = a["impressions"]
        a["ctr"] = round(a["clicks"] / imps, 4) if imps else 0.0
        a["position"] = round(a["_pw"] / imps, 2) if imps else 0.0
        del a["_pw"]
        out.append(a)
    return out
