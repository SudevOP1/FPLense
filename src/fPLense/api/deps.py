"""Shared request dependencies: the store, the FPL proxy and the per-IP rate limiter."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable

from fastapi import HTTPException, Request

from fPLense.api.fpl_proxy import FplProxy
from fPLense.api.store import Store


class TokenBucket:
    """Per-key token bucket: ``capacity`` requests at once, refilled at ``rate`` per second."""

    def __init__(self, capacity: float, rate: float, clock: Callable[[], float] = time.monotonic):
        self.capacity = float(capacity)
        self.rate = float(rate)
        self.clock = clock
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def take(self, key: str) -> float:
        """Spend a token; returns 0 if allowed, else the seconds until one is available."""
        with self._lock:
            now = self.clock()
            tokens, last = self._buckets.get(key, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            if tokens >= 1:
                self._buckets[key] = (tokens - 1, now)
                if len(self._buckets) > 10_000:  # forget idle clients
                    self._buckets = {k: v for k, v in self._buckets.items() if now - v[1] < 3600}
                return 0.0
            self._buckets[key] = (tokens, now)
            return (1 - tokens) / self.rate if self.rate > 0 else 60.0


def get_store(request: Request) -> Store:
    return request.app.state.store


def get_proxy(request: Request) -> FplProxy:
    return request.app.state.proxy


def rate_limit(request: Request) -> None:
    """429 with ``Retry-After`` when one IP calls the expensive endpoints too often."""
    limiter: TokenBucket = request.app.state.limiter
    key = request.client.host if request.client else "unknown"
    wait = limiter.take(key)
    if wait > 0:
        raise HTTPException(
            status_code=429,
            detail="Too many requests: slow down a little and try again.",
            headers={"Retry-After": str(max(1, math.ceil(wait)))},
        )
