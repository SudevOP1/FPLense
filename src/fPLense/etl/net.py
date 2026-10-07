"""Polite HTTP helpers: browser-like User-Agent, pause between calls, retries with backoff."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import requests

from fPLense import config

RETRY_STATUSES = {429, 500, 502, 503, 504}


class FetchError(RuntimeError):
    """Raised when a URL still fails after all retries."""


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(config.REQUEST_HEADERS)
    return session


def get(
    url: str,
    session: requests.Session | None = None,
    *,
    retries: int = config.REQUEST_RETRIES,
    backoff: float = config.REQUEST_BACKOFF_S,
    sleep: Callable[[float], None] = time.sleep,
    timeout: float = config.REQUEST_TIMEOUT_S,
) -> requests.Response:
    """GET ``url``, retrying on connection errors and 429/5xx with exponential backoff.

    Always pauses ``config.REQUEST_SLEEP_S`` before the call so consecutive calls stay polite.
    Other 4xx responses fail immediately (retrying a 404 never helps).
    """
    session = session or make_session()
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        sleep(config.REQUEST_SLEEP_S)
        try:
            resp = session.get(url, timeout=timeout)
        except requests.RequestException as exc:
            last_error = exc
        else:
            if resp.status_code == 200:
                return resp
            if resp.status_code not in RETRY_STATUSES:
                raise FetchError(f"GET {url} -> HTTP {resp.status_code}")
            last_error = FetchError(f"GET {url} -> HTTP {resp.status_code}")
        if attempt < retries:
            sleep(backoff * 2**attempt)
    raise FetchError(f"GET {url} failed after {retries + 1} attempts: {last_error}")


def get_json(url: str, session: requests.Session | None = None, **kwargs: Any) -> Any:
    return get(url, session, **kwargs).json()
