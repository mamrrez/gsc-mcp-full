"""The Search Console API, as thin as it can be.

One class, one method per endpoint, plus ``query_all`` which pages through
Search Analytics results. Errors become :class:`GSCError` with a message a
person can act on. Retries with backoff on 429 and 5xx.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote

import requests
from google.auth import exceptions as google_exceptions

from .auth import AuthError

V3 = "https://www.googleapis.com/webmasters/v3"
V1 = "https://searchconsole.googleapis.com/v1"
MAX_ROW_LIMIT = 25_000
MAX_RETRY_AFTER = 30.0  # never sleep longer than this inside a tool call
_RETRY_STATUSES = {429, 500, 502, 503, 504}

SEARCH_TYPES = ("web", "image", "video", "news", "discover", "googleNews")
DIMENSIONS = ("query", "page", "country", "device", "date", "searchAppearance", "hour")


class GSCError(Exception):
    def __init__(self, message: str, status: int | None = None, reason: str | None = None):
        super().__init__(message)
        self.status = status
        self.reason = reason


def search_type_name(s: str | None) -> str:
    """The API's spelling of a search type, whatever case or separator was typed."""
    s = (s or "web").strip()
    low = {t.lower(): t for t in SEARCH_TYPES}
    if s.lower() in low:
        return low[s.lower()]
    if s.lower().replace("-", "_") in ("google_news", "gnews"):
        return "googleNews"
    raise ValueError(f"search_type must be one of {', '.join(SEARCH_TYPES)}")


def dimension_name(d: str) -> str:
    d = d.strip()
    low = {x.lower(): x for x in DIMENSIONS}
    if d.lower() in low:
        return low[d.lower()]
    if d.lower() in ("search_appearance", "appearance"):
        return "searchAppearance"
    raise ValueError(f"unknown dimension {d!r}; use {', '.join(DIMENSIONS)}")


def _friendly(status: int, payload: Any, url: str) -> str:
    msg = ""
    reason = ""
    if isinstance(payload, dict):
        err = payload.get("error", {})
        if isinstance(err, dict):
            msg = err.get("message", "") or ""
            details = err.get("errors") or []
            if details and isinstance(details[0], dict):
                reason = details[0].get("reason", "") or ""
        else:
            msg = str(err)
    if status == 401:
        return "Google rejected the credentials (401). Run `gsc-mcp-full auth` to sign in again."
    if status == 403:
        # Decided on Google's reason code and exact phrase — never on a word that could
        # also appear in the property URL (a site called horoscope.example contains "scope").
        if reason in ("insufficientPermissions", "ACCESS_TOKEN_SCOPE_INSUFFICIENT") or "authentication scope" in msg.lower():
            return (
                "This action needs the full (write) scope but the token is read-only. "
                "Set GSC_ALLOW_WRITE=1 and run `gsc-mcp-full auth --force`. (403)"
            )
        return (
            f"Google says you do not have access to this property (403: {msg or 'forbidden'}). "
            "Check the exact property URL with list_properties — `sc-domain:example.com` and "
            "`https://example.com/` are different properties — and that this Google account "
            "(or the service account's email) has been added as a user in Search Console."
        )
    if status == 404:
        return f"Not found (404: {msg or url}). The property or sitemap URL is probably not spelled exactly as Search Console has it."
    if status == 429:
        return f"Search Console API quota exceeded (429: {msg}). Wait a minute and try again, or inspect fewer URLs."
    if status == 400:
        return f"Bad request (400): {msg or 'the API rejected the parameters'}"
    return f"Search Console API error {status}: {msg or url}"


class GSCClient:
    def __init__(self, credentials, timeout: float = 60.0, session: requests.Session | None = None):
        if session is None:
            from google.auth.transport.requests import AuthorizedSession

            session = AuthorizedSession(credentials)
        self._s = session
        self.timeout = timeout
        self.dead = False  # set when Google rejects the sign-in; the runtime then builds a new client

    # -- transport ---------------------------------------------------------

    def _request(
        self,
        method: str,
        url: str,
        json: dict | None = None,
        params: dict | None = None,
        timeout: float | None = None,
        attempts: int = 6,
    ) -> dict:
        delay = 0.5
        last: GSCError | None = None
        for attempt in range(attempts):
            final = attempt == attempts - 1
            try:
                r = self._s.request(method, url, json=json, params=params, timeout=timeout or self.timeout)
            except google_exceptions.RefreshError as e:
                # The refresh token expired (7 days for an app in "Testing") or was revoked.
                self.dead = True
                raise AuthError(
                    "Google no longer accepts the saved sign-in (it expired or was revoked). "
                    "Run `gsc-mcp-full auth` to sign in again."
                ) from e
            except (requests.RequestException, google_exceptions.TransportError) as e:
                last = GSCError(f"Network error talking to Google: {e}")
                if not final:
                    time.sleep(delay)
                    delay *= 2
                continue
            except google_exceptions.GoogleAuthError as e:
                self.dead = True
                raise AuthError(f"Sign-in problem: {e}. Run `gsc-mcp-full auth`.") from e
            if r.status_code in _RETRY_STATUSES and not final:
                retry_after = r.headers.get("Retry-After", "")
                wait = float(retry_after) if retry_after.isdigit() else delay
                time.sleep(min(wait, MAX_RETRY_AFTER))
                delay *= 2
                continue
            if r.status_code >= 400:
                try:
                    payload = r.json()
                except ValueError:
                    payload = r.text
                raise GSCError(_friendly(r.status_code, payload, url), r.status_code)
            if r.status_code == 204 or not r.content:
                return {}
            try:
                return r.json()
            except ValueError as e:
                raise GSCError(f"Google returned something that is not JSON from {url}") from e
        raise last or GSCError("Gave up after repeated retries")

    @staticmethod
    def _site(site_url: str) -> str:
        return quote(site_url, safe="")

    # -- sites -------------------------------------------------------------

    def sites_list(self) -> list[dict]:
        return self._request("GET", f"{V3}/sites").get("siteEntry", [])

    def site_get(self, site_url: str) -> dict:
        return self._request("GET", f"{V3}/sites/{self._site(site_url)}")

    def site_add(self, site_url: str) -> None:
        self._request("PUT", f"{V3}/sites/{self._site(site_url)}")

    def site_delete(self, site_url: str) -> None:
        self._request("DELETE", f"{V3}/sites/{self._site(site_url)}")

    # -- sitemaps ----------------------------------------------------------

    def sitemaps_list(self, site_url: str, sitemap_index: str | None = None) -> list[dict]:
        params = {"sitemapIndex": sitemap_index} if sitemap_index else None
        return self._request("GET", f"{V3}/sites/{self._site(site_url)}/sitemaps", params=params).get("sitemap", [])

    def sitemap_get(self, site_url: str, feedpath: str) -> dict:
        return self._request("GET", f"{V3}/sites/{self._site(site_url)}/sitemaps/{quote(feedpath, safe='')}")

    def sitemap_submit(self, site_url: str, feedpath: str) -> None:
        self._request("PUT", f"{V3}/sites/{self._site(site_url)}/sitemaps/{quote(feedpath, safe='')}")

    def sitemap_delete(self, site_url: str, feedpath: str) -> None:
        self._request("DELETE", f"{V3}/sites/{self._site(site_url)}/sitemaps/{quote(feedpath, safe='')}")

    # -- search analytics --------------------------------------------------

    def query(self, site_url: str, body: dict) -> dict:
        return self._request("POST", f"{V3}/sites/{self._site(site_url)}/searchAnalytics/query", json=body)

    def query_all(self, site_url: str, body: dict, max_rows: int = MAX_ROW_LIMIT) -> tuple[list[dict], dict]:
        """Page through results up to ``max_rows``. Returns ``(rows, metadata)``."""
        body = dict(body)
        page = min(MAX_ROW_LIMIT, max_rows)
        body["rowLimit"] = page
        start = int(body.get("startRow", 0))
        rows: list[dict] = []
        meta: dict = {}
        while True:
            body["startRow"] = start
            res = self.query(site_url, body)
            meta = res.get("metadata") or meta
            chunk = res.get("rows", [])
            rows.extend(chunk)
            if len(chunk) < page or len(rows) >= max_rows:
                break
            start += page
        return rows[:max_rows], meta

    # -- url inspection ----------------------------------------------------

    def inspect(self, site_url: str, page_url: str, language_code: str = "en-US", timeout: float = 30.0) -> dict:
        """One URL Inspection. Short timeout and a single retry: a batch must not outlive the client's patience."""
        body = {"inspectionUrl": page_url, "siteUrl": site_url, "languageCode": language_code}
        return self._request("POST", f"{V1}/urlInspection/index:inspect", json=body, timeout=timeout, attempts=2).get("inspectionResult", {})


# -- helpers used by the tools -------------------------------------------


def rows_to_dicts(rows: list[dict], dimensions: list[str]) -> list[dict]:
    """Flatten API rows (``keys`` list) into dicts keyed by dimension name."""
    out = []
    for r in rows:
        d = dict(zip(dimensions, r.get("keys", [])))
        d["clicks"] = int(r.get("clicks", 0))
        d["impressions"] = int(r.get("impressions", 0))
        d["ctr"] = float(r.get("ctr", 0))
        d["position"] = float(r.get("position", 0))
        out.append(d)
    return out


def resolve_site(sites: list[dict], given: str) -> str | None:
    """Match a loosely typed site to a real property URL.

    An exact match always wins. Input with a scheme (``https://example.com``)
    means a URL-prefix property and is tried as one first; a bare host
    (``example.com``) means the domain property first. Properties the account
    has not verified are only used when nothing else matches.
    """
    urls = [s.get("siteUrl", "") for s in sites]
    if given in urls:
        return given
    verified = [s.get("siteUrl", "") for s in sites if s.get("permissionLevel") != "siteUnverifiedUser"]
    g = given.strip()
    has_scheme = g.startswith(("http://", "https://"))
    bare = g
    for prefix in ("sc-domain:", "https://", "http://"):
        if bare.startswith(prefix):
            bare = bare[len(prefix) :]
    bare = bare.rstrip("/")
    host, _, path = bare.partition("/")
    path = "/" + path if path else ""
    nowww = host.removeprefix("www.")
    prefixes = []
    schemes = [g.split("://")[0]] if has_scheme else []
    schemes += [s for s in ("https", "http") if s not in schemes]
    hosts = [host] + ([f"www.{host}"] if host == nowww else [nowww])
    for scheme in schemes:
        for h in hosts:
            prefixes.append(f"{scheme}://{h}{path}/")
    domains = [f"sc-domain:{nowww}"] if not path else []
    candidates = prefixes + domains if has_scheme else domains + prefixes
    for pool in (verified, urls):
        for c in candidates:
            if c in pool:
                return c
    return None
