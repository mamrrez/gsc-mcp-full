"""Configuration — environment variables only, read once at start.

Nothing here is secret except what the paths point at. The token and the
history database live under ``GSC_CONFIG_DIR`` with owner-only permissions.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "gsc-mcp-full"

SCOPES = {
    "readonly": "https://www.googleapis.com/auth/webmasters.readonly",
    "full": "https://www.googleapis.com/auth/webmasters",
}


def _truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")


def _path(v: str | None) -> Path | None:
    v = (v or "").strip()
    return Path(os.path.expanduser(v)) if v else None


@dataclass(frozen=True)
class Settings:
    config_dir: Path
    credentials_path: Path | None  # OAuth client secrets OR a service-account key (auto-detected)
    token_path: Path
    scope: str  # "readonly" | "full"
    allow_write: bool  # enables add/remove property and submit/delete sitemap
    data_state: str  # "all" (matches the UI) | "final"
    db_path: Path
    timezone: str | None  # default for local-day features, e.g. "Asia/Tehran"
    lang: str | None  # language hint for ambiguous scripts, e.g. "fa"
    row_cap: int  # hard cap on rows a tool will fetch from the API

    @classmethod
    def from_env(cls) -> Settings:
        config_dir = _path(os.environ.get("GSC_CONFIG_DIR")) or Path.home() / ".config" / APP_NAME
        creds = _path(os.environ.get("GSC_CREDENTIALS_PATH"))
        scope = (os.environ.get("GSC_SCOPE") or "readonly").strip().lower()
        allow_write = _truthy(os.environ.get("GSC_ALLOW_WRITE"))
        if allow_write:
            scope = "full"  # writing needs the full scope; do not make the user set both
        if scope not in SCOPES:
            raise ValueError(f"GSC_SCOPE must be 'readonly' or 'full', got {scope!r}")
        data_state = (os.environ.get("GSC_DATA_STATE") or "all").strip().lower()
        if data_state not in ("all", "final"):
            raise ValueError("GSC_DATA_STATE must be 'all' or 'final'")
        return cls(
            config_dir=config_dir,
            credentials_path=creds,
            token_path=_path(os.environ.get("GSC_TOKEN_PATH")) or config_dir / "token.json",
            scope=scope,
            allow_write=allow_write,
            data_state=data_state,
            db_path=_path(os.environ.get("GSC_DB_PATH")) or config_dir / "history.sqlite",
            timezone=(os.environ.get("GSC_TIMEZONE") or "").strip() or None,
            lang=(os.environ.get("GSC_LANG") or "").strip().lower() or None,
            row_cap=int(os.environ.get("GSC_ROW_CAP") or 100_000),
        )

    @property
    def scope_url(self) -> str:
        return SCOPES[self.scope]
