"""Cached, rate-limited calls to the public FPL ``entry/*`` endpoints (PLAN.md §8 P6).

The browser never calls FPL directly: the backend does, politely.

- One global limiter spaces upstream calls at least ``min_interval`` (0.25 s) apart.
- Retries with exponential backoff on connection errors, 429 and 5xx.
- Every response is schema-checked (the API is unofficial and can change).
- TTL cache: ``entry`` and ``history`` 10 min; picks of the current GW 10 min; picks of a
  **finished** GW never change, so they sit in an LRU cache with no expiry.
- Upstream 404 -> :class:`FplNotFound`; FPL's "the game is being updated" 503 ->
  :class:`FplUnavailable`; anything else -> :class:`FplUpstreamError`.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from fPLense import config
from fPLense.etl.fetch_api import SchemaError, check_entry, check_entry_history, check_picks


class FplError(RuntimeError):
    status = 502


class FplNotFound(FplError):
    status = 404


class FplUnavailable(FplError):
    status = 503


class FplUpstreamError(FplError):
    status = 502


class FplProxy:
    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        base_url: str = config.FPL_API_BASE_URL,
        min_interval: float = config.REQUEST_SLEEP_S,
        retries: int = config.FPL_PROXY_RETRIES,
        backoff: float = config.REQUEST_BACKOFF_S,
        ttl: float = config.FPL_PROXY_TTL_S,
        lru_size: int = config.FPL_PROXY_LRU_SIZE,
        timeout: float = config.FPL_PROXY_TIMEOUT_S,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.base_url = base_url.rstrip("/")
        self.min_interval = min_interval
        self.retries = retries
        self.backoff = backoff
        self.ttl = ttl
        self.lru_size = lru_size
        self.clock = clock
        self.sleep = sleep
        self._transport = transport
        self._timeout = timeout
        # created lazily inside the running event loop: pooled connections (and the limiter's
        # lock) belong to one loop, and a client made at import time would outlive it
        self._client: httpx.AsyncClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock: asyncio.Lock | None = None
        self._last_call = -1e9
        self._ttl_cache: dict[str, tuple[float, Any]] = {}
        self._lru: OrderedDict[str, Any] = OrderedDict()
        self.upstream_calls = 0

    async def aclose(self) -> None:
        if self._client is not None and self._loop is asyncio.get_running_loop():
            await self._client.aclose()
        self._client = None

    def _bind(self) -> httpx.AsyncClient:
        loop = asyncio.get_running_loop()
        if self._client is None or self._loop is not loop:
            self._client = httpx.AsyncClient(
                transport=self._transport,
                headers=config.REQUEST_HEADERS,
                timeout=self._timeout,
                follow_redirects=True,
            )
            self._loop = loop
            self._lock = asyncio.Lock()
        return self._client

    # --- public calls -------------------------------------------------------------------------

    async def entry(self, team_id: int) -> dict:
        return await self._cached(f"entry/{int(team_id)}/", check_entry, team_id=team_id)

    async def history(self, team_id: int) -> dict:
        return await self._cached(
            f"entry/{int(team_id)}/history/", check_entry_history, team_id=team_id
        )

    async def picks(self, team_id: int, gw: int, finished: bool) -> dict:
        path = f"entry/{int(team_id)}/event/{int(gw)}/picks/"
        if finished:
            if path in self._lru:
                self._lru.move_to_end(path)
                return self._lru[path]
            data = await self._fetch(path, check_picks, team_id=team_id, gw=gw)
            self._lru[path] = data
            while len(self._lru) > self.lru_size:
                self._lru.popitem(last=False)
            return data
        return await self._cached(path, check_picks, team_id=team_id, gw=gw)

    # --- plumbing -----------------------------------------------------------------------------

    async def _cached(self, path: str, check, **ctx) -> dict:
        hit = self._ttl_cache.get(path)
        now = self.clock()
        if hit is not None and hit[0] > now:
            return hit[1]
        data = await self._fetch(path, check, **ctx)
        self._ttl_cache[path] = (self.clock() + self.ttl, data)
        if len(self._ttl_cache) > 4 * self.lru_size:  # drop expired entries now and then
            self._ttl_cache = {k: v for k, v in self._ttl_cache.items() if v[0] > now}
        return data

    async def _throttle(self) -> None:
        self._bind()
        async with self._lock:
            wait = self._last_call + self.min_interval - self.clock()
            if wait > 0:
                await self.sleep(wait)
            self._last_call = self.clock()

    async def _fetch(self, path: str, check, team_id: int, gw: int | None = None) -> dict:
        url = f"{self.base_url}/{path}"
        last = ""
        for attempt in range(self.retries + 1):
            await self._throttle()
            self.upstream_calls += 1
            try:
                resp = await self._bind().get(url)
            except httpx.HTTPError as exc:
                last = f"network error: {exc.__class__.__name__}"
            else:
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        check(data)
                    except (ValueError, SchemaError) as exc:
                        raise FplUpstreamError(f"FPL sent an unexpected response: {exc}") from exc
                    return data
                if resp.status_code == 404:
                    if gw is None:
                        raise FplNotFound(f"No FPL team with ID {team_id}.")
                    raise FplNotFound(
                        f"No picks for FPL team {team_id} in GW{gw} (picks become public after "
                        "the deadline)."
                    )
                if resp.status_code not in (429, 500, 502, 503, 504):
                    raise FplUpstreamError(f"FPL answered HTTP {resp.status_code}.")
                last = f"HTTP {resp.status_code}"
                if resp.status_code == 503 and attempt == self.retries:
                    raise FplUnavailable(
                        "FPL is updating the game right now; try again in a few minutes."
                    )
            if attempt < self.retries:
                await self.sleep(self.backoff * 2**attempt)
        if last.startswith("HTTP 503"):
            raise FplUnavailable("FPL is updating the game right now; try again in a few minutes.")
        raise FplUpstreamError(f"FPL couldn't be reached ({last}); try again shortly.")
