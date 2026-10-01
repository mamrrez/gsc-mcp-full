"""Shared state for the tools: settings, a lazily built client, the store.

Tools never touch credentials directly. They ask the runtime for a client,
resolve a loosely typed property name to the real one, and fetch rows with
filters that already understand the spellings of a term.
"""

from __future__ import annotations

import functools
import sqlite3
import threading
import time
from collections.abc import Callable

from .auth import AuthError, load_credentials
from .client import DIMENSIONS, SEARCH_TYPES, GSCClient, GSCError, dimension_name, resolve_site, rows_to_dicts, search_type_name
from .dates import DateRange, resolve_range
from .i18n import api_regex
from .settings import Settings
from .store import HistoryStore

try:  # MCP SDK 2.x
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:  # pragma: no cover - MCP SDK 1.x
    from mcp.server.fastmcp.exceptions import ToolError  # type: ignore[no-redef]

__all__ = ["DIMENSIONS", "SEARCH_TYPES", "Runtime", "ToolError", "guarded", "hints", "parse_dims"]


def hints(read_only: bool = True, destructive: bool = False, idempotent: bool = True, open_world: bool = True):
    """Tool annotations, so a client can tell a read from a write before asking the user."""
    try:
        from mcp.types import ToolAnnotations

        return ToolAnnotations(
            read_only_hint=read_only, destructive_hint=destructive, idempotent_hint=idempotent, open_world_hint=open_world
        )
    except Exception:  # pragma: no cover - older SDK without these fields
        return None


class Runtime:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings.from_env()
        self._client: GSCClient | None = None
        self._store: HistoryStore | None = None
        self._sites: tuple[float, list[dict]] | None = None
        # Tools run on worker threads. Without the lock, three parallel first calls
        # start three browser sign-ins and race to create the history database.
        self._lock = threading.RLock()

    # -- singletons ----------------------------------------------------------

    def client(self) -> GSCClient:
        with self._lock:
            if self._client is not None and getattr(self._client, "dead", False):
                self._client = None  # Google rejected its sign-in; build a fresh one
                self._sites = None
            if self._client is None:
                creds = load_credentials(self.settings, interactive=True)
                self._client = GSCClient(creds)
            return self._client

    def store(self) -> HistoryStore:
        with self._lock:
            if self._store is None:
                self._store = HistoryStore(self.settings.db_path)
            return self._store

    def reset(self) -> None:
        with self._lock:
            self._client = None
            self._sites = None

    def require_write(self) -> None:
        if not self.settings.allow_write:
            raise GSCError(
                "Write tools are disabled. Set GSC_ALLOW_WRITE=1 in the MCP server's environment "
                "(this also switches the token to the full scope — run `gsc-mcp-full auth --force`) and restart."
            )

    # -- properties ----------------------------------------------------------

    def sites(self, max_age: float = 300.0) -> list[dict]:
        now = time.monotonic()
        with self._lock:
            cached = self._sites
        if cached is None or now - cached[0] > max_age:
            cached = (now, self.client().sites_list())
            with self._lock:
                self._sites = cached
        return cached[1]

    def site(self, given: str) -> str:
        """The exact property URL for what the user typed, or a helpful error."""
        given = (given or "").strip()
        if not given:
            raise GSCError("site_url is required — call list_properties to see the choices.")
        sites = self.sites()
        found = resolve_site(sites, given)
        if found:
            return found
        names = ", ".join(sorted(s.get("siteUrl", "") for s in sites)) or "(none — this account has no properties)"
        raise GSCError(f"No property matches {given!r}. Properties on this account: {names}")

    # -- search analytics ----------------------------------------------------

    def range(self, days: int | None, start: str | None, end: str | None, period: str | None = None, lag: int = 1) -> DateRange:
        return resolve_range(days=days, start=start, end=end, period=period, lag=lag)

    def fetch(
        self,
        site: str,
        rng: DateRange,
        dims: list[str],
        search_type: str = "web",
        *,
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
        aggregation: str | None = None,
        max_rows: int = 25_000,
    ) -> tuple[list[dict], dict]:
        """Rows as dicts (one key per dimension + metrics) and the response metadata.

        ``query_filter`` becomes a case-insensitive regex that matches the common
        spellings of the term (ی/ي, ک/ك, half-space, vowel marks, digit scripts).
        """
        st = search_type_name(search_type)
        dims = [dimension_name(d) for d in dims]
        filters: list[dict] = []
        if query_filter:
            filters.append({"dimension": "query", "operator": "includingRegex", "expression": api_regex(query_filter, whole_word=False)})
        if query_regex:
            filters.append({"dimension": "query", "operator": "includingRegex", "expression": query_regex})
        if query_regex_exclude:
            filters.append({"dimension": "query", "operator": "excludingRegex", "expression": query_regex_exclude})
        if page_exact:
            filters.append({"dimension": "page", "operator": "equals", "expression": page_exact})
        if page_filter:
            filters.append({"dimension": "page", "operator": "contains", "expression": page_filter})
        if page_filter_exclude:
            filters.append({"dimension": "page", "operator": "notContains", "expression": page_filter_exclude})
        if page_regex:
            filters.append({"dimension": "page", "operator": "includingRegex", "expression": page_regex})
        if country:
            filters.append({"dimension": "country", "operator": "equals", "expression": country.strip().lower()})
        if device:
            filters.append({"dimension": "device", "operator": "equals", "expression": device.strip().upper()})
        if search_appearance:
            filters.append({"dimension": "searchAppearance", "operator": "equals", "expression": search_appearance.strip()})
        body: dict = {
            "startDate": rng.start_iso,
            "endDate": rng.end_iso,
            "type": st,
            "dataState": (data_state or self.settings.data_state).lower(),
        }
        if dims:
            body["dimensions"] = dims
        if "hour" in dims:
            body["dataState"] = "hourly_all"
        if filters:
            body["dimensionFilterGroups"] = [{"groupType": "and", "filters": filters}]
        if aggregation:
            body["aggregationType"] = aggregation
        max_rows = max(1, min(int(max_rows), self.settings.row_cap))
        rows, meta = self.client().query_all(site, body, max_rows=max_rows)
        return rows_to_dicts(rows, dims), meta

    def period_totals(self, site: str, rng: DateRange, search_type: str = "web", **filters) -> dict | None:
        """The real totals for a period: one request with no dimensions.

        Summing fetched rows undercounts — only the top rows are fetched and
        Google leaves anonymised queries out of query-level rows — so header
        lines use this. ``None`` when the API will not answer (the caller then
        labels its own sum as a sum of rows).
        """
        try:
            rows, _ = self.fetch(site, rng, [], search_type, max_rows=1, **filters)
        except GSCError:
            return None
        if not rows:
            return {"clicks": 0, "impressions": 0, "ctr": 0.0, "position": 0.0}
        return {k: rows[0][k] for k in ("clicks", "impressions", "ctr", "position")}


def parse_dims(s: str | None, default: str = "query") -> list[str]:
    raw = (s or default).replace(";", ",").split(",")
    dims = [dimension_name(x) for x in raw if x.strip()]
    if not dims:
        raise ValueError("at least one dimension is required")
    return dims


def guarded(fn: Callable[..., str]) -> Callable[..., str]:
    """Turn every failure into a tool error that carries its reason.

    The MCP SDK reports an exception it does not know as the bare text
    "Error executing tool <name>" — the model then has nothing to correct
    itself with. Raising ``ToolError`` keeps the message and sets ``isError``,
    so clients can tell a failure from data.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs) -> str:
        try:
            return fn(*args, **kwargs)
        except ToolError:
            raise
        except AuthError as e:
            raise ToolError(f"Authentication problem: {e}") from e
        except GSCError as e:
            raise ToolError(str(e)) from e
        except sqlite3.Error as e:
            raise ToolError(f"SQL error: {e}") from e
        except ValueError as e:
            raise ToolError(str(e)) from e
        except LookupError as e:  # includes an unknown timezone name
            raise ToolError(f"Not found: {e}") from e
        except Exception as e:
            raise ToolError(f"Unexpected {type(e).__name__}: {e}") from e

    return wrapper
