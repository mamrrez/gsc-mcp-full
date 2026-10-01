"""Credentials: OAuth (your own Google account) or a service account.

Read-only by default. The OAuth token is written with owner-only permissions
and is never logged. When the browser flow has to run while the server is
already talking MCP over stdio, everything the flow would print goes to
stderr so it cannot corrupt the protocol stream.

A saved sign-in is never deleted or overwritten by a failure: it is replaced
only after a new sign-in has succeeded.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
from pathlib import Path

from .settings import SCOPES, Settings

SIGN_IN_TIMEOUT = 300  # seconds to finish the browser flow before giving up


class AuthError(Exception):
    """A configuration problem the user has to fix; the message says how."""


def _write_private(path: Path, text: str) -> None:
    """Write ``text`` readable by the owner only.

    The directory's permissions are changed only if this call created it — a
    token path pointing into the home directory must not lock the home directory.
    """
    if not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(path.parent, 0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)


def _read_json(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError as e:
        raise AuthError(f"Credentials file not found: {path}") from e
    except json.JSONDecodeError as e:
        raise AuthError(f"Credentials file is not valid JSON: {path}") from e
    except OSError as e:  # a directory, or no permission
        raise AuthError(f"Cannot read credentials file {path}: {e.strerror or e}") from e
    if not isinstance(data, dict):
        raise AuthError(f"{path} is not a Google credentials file (expected a JSON object).")
    return data


def credential_kind(path: Path | None) -> str:
    """``service_account`` | ``oauth_client`` | ``oauth_web_client`` | ``none`` | ``missing`` | ``unknown``."""
    if not path:
        return "none"
    if not path.exists():
        return "missing"
    data = _read_json(path)
    if data.get("type") == "service_account":
        return "service_account"
    if "installed" in data:
        return "oauth_client"
    if "web" in data:
        return "oauth_web_client"
    return "unknown"


def _scopes_cover(have: list[str] | None, need: str) -> bool:
    if not have:
        return True  # the token file does not say; let Google decide rather than reject a good token
    if need in have:
        return True
    # The full scope implies read-only.
    return need == SCOPES["readonly"] and SCOPES["full"] in have


def _adc_configured() -> bool:
    """True only when Application Default Credentials were set up on purpose.

    ``google.auth.default()`` otherwise probes the cloud metadata server and
    stalls every call for about twelve seconds on a normal machine.
    """
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        return True
    if (os.environ.get("GSC_USE_ADC") or "").strip().lower() in ("1", "true", "yes", "on"):
        return True
    well_known = [Path.home() / ".config" / "gcloud" / "application_default_credentials.json"]
    if os.environ.get("APPDATA"):
        well_known.append(Path(os.environ["APPDATA"]) / "gcloud" / "application_default_credentials.json")
    return any(p.exists() for p in well_known)


def load_credentials(settings: Settings, interactive: bool = True, force_login: bool = False):
    """Return google-auth credentials for the configured scope.

    Order: service account file → OAuth token on disk (refreshed if needed) →
    OAuth browser flow (only when ``interactive``) → Application Default
    Credentials. Raises :class:`AuthError` with instructions otherwise.
    """
    need = settings.scope_url
    kind = credential_kind(settings.credentials_path)

    if kind == "missing":
        raise AuthError(f"GSC_CREDENTIALS_PATH points at a file that does not exist: {settings.credentials_path}")

    if kind == "service_account":
        from google.oauth2 import service_account

        try:
            return service_account.Credentials.from_service_account_file(str(settings.credentials_path), scopes=[need])
        except (ValueError, KeyError) as e:
            raise AuthError(f"{settings.credentials_path} is not a usable service-account key: {e}") from e

    if kind == "oauth_web_client":
        # A "Web application" client only redirects to the exact addresses registered for it;
        # the sign-in here listens on a free local port, which only a "Desktop app" client allows.
        raise AuthError(
            f"{settings.credentials_path} is an OAuth client of type \"Web application\". This server needs "
            "type \"Desktop app\": in Google Cloud Console open Credentials, choose Create credentials → "
            "OAuth client ID → Application type: Desktop app, download its JSON and use that file instead."
        )

    if kind == "unknown":
        raise AuthError(
            f"{settings.credentials_path} is neither a service-account key nor an OAuth client "
            "secrets file. Download one of those from Google Cloud Console (see the setup guide)."
        )

    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    token_path = settings.token_path
    creds = None
    if token_path.exists() and not force_login:
        try:
            creds = Credentials.from_authorized_user_file(str(token_path))
        except Exception:
            creds = None  # unreadable token: a new login will replace it
        if creds is not None and not _scopes_cover(list(creds.scopes or []), need):
            creds = None  # token was issued for a narrower scope than now requested
        if creds is not None and not creds.valid:
            if not creds.refresh_token:
                creds = None
            else:
                try:
                    creds.refresh(Request())
                    _write_private(token_path, creds.to_json())
                except RefreshError:
                    creds = None  # revoked or expired for good: sign in again
                except Exception as e:  # network trouble is not a dead token
                    raise AuthError(
                        f"Could not reach Google to refresh the sign-in ({type(e).__name__}). "
                        "Your saved sign-in is untouched; check the connection and try again."
                    ) from e
        if creds is not None and creds.valid:
            return creds

    if kind == "oauth_client":
        if not interactive:
            raise AuthError("No valid sign-in. Run `gsc-mcp-full auth` in a terminal once to sign in with Google.")
        from google_auth_oauthlib.flow import InstalledAppFlow

        try:
            flow = InstalledAppFlow.from_client_secrets_file(str(settings.credentials_path), scopes=[need])
            # Keep stdout clean: under stdio transport it IS the MCP channel.
            with contextlib.redirect_stdout(sys.stderr):
                creds = flow.run_local_server(
                    port=0,
                    open_browser=True,
                    authorization_prompt_message="Open this link to sign in with Google:\n{url}\n",
                    success_message="Signed in. You can close this tab and go back to your MCP client.",
                    timeout_seconds=SIGN_IN_TIMEOUT,
                )
        except Exception as e:  # timeout, no browser, consent denied, malformed client file
            raise AuthError(
                f"Google sign-in was not completed ({type(e).__name__}). Run `gsc-mcp-full auth` in a "
                "terminal to sign in, then try again."
            ) from e
        _write_private(token_path, creds.to_json())
        return creds

    # No credentials file at all. Last resort: Application Default Credentials
    # (gcloud auth application-default login, a workload identity, or a Cloud VM).
    if _adc_configured():
        try:
            import google.auth

            adc, _ = google.auth.default(scopes=[need])
            return adc
        except Exception as e:
            raise AuthError(f"Application Default Credentials are configured but could not be loaded: {e}") from e
    raise AuthError(
        "No credentials configured. Set GSC_CREDENTIALS_PATH to your OAuth client secrets JSON "
        "(or a service-account key) and run `gsc-mcp-full auth`. Setup guide: "
        "https://mamrrez.github.io/gsc-mcp-full/setup"
    )


def auth_status(settings: Settings) -> dict:
    """What a `doctor`/capabilities call reports — never the token itself."""
    try:
        kind = credential_kind(settings.credentials_path)
    except AuthError as e:
        kind = f"unreadable ({e})"
    token = settings.token_path.exists()
    info: dict = {
        "credentials": kind,
        "credentials_path": str(settings.credentials_path) if settings.credentials_path else None,
        "token_present": token,
        "token_path": str(settings.token_path),
        "scope": settings.scope,
        "write_enabled": settings.allow_write,
    }
    if token:
        try:
            data = _read_json(settings.token_path)
            info["token_scopes"] = [s.rsplit("/", 1)[-1] for s in data.get("scopes") or []] or "not recorded"
        except AuthError:
            info["token_scopes"] = "unreadable"
    return info
