"""Retry/backoff behaviour of the HTTP helper, with a fake session (no network)."""

from __future__ import annotations

import pytest
import requests

from fPLense.etl import net


class FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def get(self, url, timeout):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_retries_then_succeeds():
    sleeps: list[float] = []
    session = FakeSession(
        [requests.ConnectionError("boom"), FakeResponse(503), FakeResponse(200, {"ok": 1})]
    )
    out = net.get_json("http://x", session, retries=3, backoff=1.0, sleep=sleeps.append)
    assert out == {"ok": 1}
    assert session.calls == 3
    backoffs = [s for s in sleeps if s != net.config.REQUEST_SLEEP_S]
    assert backoffs == [1.0, 2.0]  # exponential


def test_polite_pause_before_every_call():
    sleeps: list[float] = []
    net.get("http://x", FakeSession([FakeResponse(200)]), sleep=sleeps.append)
    assert sleeps == [net.config.REQUEST_SLEEP_S]


def test_gives_up_after_retries():
    session = FakeSession([FakeResponse(429)] * 3)
    with pytest.raises(net.FetchError, match="after 3 attempts"):
        net.get("http://x", session, retries=2, sleep=lambda s: None)
    assert session.calls == 3


def test_non_retryable_status_fails_fast():
    session = FakeSession([FakeResponse(404), FakeResponse(200)])
    with pytest.raises(net.FetchError, match="404"):
        net.get("http://x", session, sleep=lambda s: None)
    assert session.calls == 1


def test_session_sends_browser_like_user_agent():
    assert net.make_session().headers["User-Agent"].startswith("Mozilla/5.0")
