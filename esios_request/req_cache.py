"""
HTTP sessions: retry policy and the optional on-disk response cache.

The cached session is created lazily (on first use, never at import time) and stored in a
persistent directory. Expiry is decided per request by ``EsiosClient``: a request whose time
window is already closed never expires, an open one expires after a short time.
"""

import os
import threading
from pathlib import Path

import platformdirs
import requests
import requests_cache
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Status codes that are retried: rate limiting and transient server errors.
RETRY_STATUSES = (429, 500, 502, 503, 504)

# Environment variable with the cache directory (used when no directory is passed explicitly).
CACHE_DIR_ENV_VAR = "ESIOS_CACHE_DIR"
# File name (without extension) of the sqlite database inside the cache directory.
CACHE_NAME = "esios_cache"
# Seconds a response is kept when its time window is still open (it ends now or in the future).
DEFAULT_RECENT_TTL = 600
# Seconds metadata (``indicator_info``, ``search``) is kept. Also the session default, applied to
# requests made without an explicit expiry (e.g. ``esios_get_request`` with a cached session).
METADATA_TTL = 86400

# Header that carries the e·sios token.
API_KEY_HEADER = "x-api-key"

_sessions: dict[Path, requests_cache.CachedSession] = {}
_sessions_lock = threading.Lock()


def _strip_api_key(session:requests.Session, prepared_request, response) -> None:
    """
    Remove the token from a redirected request that goes to another host.

    The API answers large requests with a 307 to a pre-signed temporary file in S3 (verified
    2026-11-11). ``requests`` only removes ``Authorization`` on such redirects, so without this the
    token would also be sent to the other host, which does not need it.
    """
    headers = prepared_request.headers
    if API_KEY_HEADER in headers and session.should_strip_auth(response.request.url, prepared_request.url):
        del headers[API_KEY_HEADER]


class EsiosSession(requests.Session):
    """``requests.Session`` that never forwards the token to another host on a redirect."""

    def rebuild_auth(self, prepared_request, response) -> None:
        super().rebuild_auth(prepared_request, response)
        _strip_api_key(self, prepared_request, response)


class EsiosCachedSession(requests_cache.CachedSession):
    """``CachedSession`` that never forwards the token to another host on a redirect."""

    def rebuild_auth(self, prepared_request, response) -> None:
        super().rebuild_auth(prepared_request, response)
        _strip_api_key(self, prepared_request, response)


def make_retry() -> Retry:
    """
    Retry policy: up to 5 retries with exponential backoff (waits of 0, 2, 4, 8 and 16 s; max. 60 s),
    GET only, honouring the API's ``Retry-After`` header. When retries are exhausted the last
    response is returned (``raise_on_status=False``) so the library can raise its own exception.
    """
    return Retry(
        total = 5,
        connect = 3,
        read = 3,
        status = 5,
        backoff_factor = 1,
        backoff_max = 60,
        status_forcelist = RETRY_STATUSES,
        allowed_methods = frozenset({"GET"}),
        respect_retry_after_header = True,
        raise_on_status = False,
    )


def mount_retries(session:requests.Session) -> requests.Session:
    """Mount an ``HTTPAdapter`` with the retry policy on ``session``."""
    adapter = HTTPAdapter(max_retries = make_retry())
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def resolve_cache_dir(cache_dir:str | os.PathLike | None = None) -> Path:
    """
    Directory of the response cache: ``cache_dir``, else the ``ESIOS_CACHE_DIR`` environment
    variable, else the user's cache directory (e.g. ``%LOCALAPPDATA%\\esios_request\\Cache`` on
    Windows, ``~/.cache/esios_request`` on Linux).
    """
    directory = cache_dir or os.environ.get(CACHE_DIR_ENV_VAR) or platformdirs.user_cache_dir(
        "esios_request", appauthor = False
    )
    return Path(directory).expanduser().resolve()


def get_session(
    use_cache:bool = False,
    cache_dir:str | os.PathLike | None = None,
    ) -> requests.Session | requests_cache.CachedSession:
    """
    Return the session to make requests (with retries), with cache optional.

    Without cache a new session is returned on every call. With cache, one shared session per
    cache directory is created on first use and reused afterwards (see ``resolve_cache_dir``).
    """
    if not use_cache:
        return mount_retries(EsiosSession())

    directory = resolve_cache_dir(cache_dir)
    with _sessions_lock:
        session = _sessions.get(directory)
        if session is None:
            directory.mkdir(parents = True, exist_ok = True)
            session = EsiosCachedSession(
                cache_name = str(directory / CACHE_NAME),
                backend = "sqlite",
                expire_after = METADATA_TTL,
                # Kept out of the cache key and never written to disk.
                ignored_parameters = [API_KEY_HEADER],
            )
            mount_retries(session)
            _sessions[directory] = session
        return session


def clear_cache(cache_dir:str | os.PathLike | None = None, *, expired_only:bool = False) -> None:
    """
    Delete the cached responses stored in ``cache_dir`` (default directory if None).
    With ``expired_only=True`` only the responses that have already expired are deleted.
    """
    directory = resolve_cache_dir(cache_dir)
    with _sessions_lock:
        known = directory in _sessions
    if not known and not (directory / f"{CACHE_NAME}.sqlite").exists():
        return  # nothing was ever cached there: do not create an empty cache just to clear it
    session = get_session(True, directory)
    if expired_only:
        session.cache.delete(expired = True)
    else:
        session.cache.clear()


def _close_sessions() -> None:
    """Close and forget every cached session (used by the tests to isolate cache directories)."""
    with _sessions_lock:
        for session in _sessions.values():
            session.close()
        _sessions.clear()
