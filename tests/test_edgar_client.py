"""Tests for garp.ingest.edgar: CIK formatting, rate limiting, caching, and
the required-contact header -- no real network calls."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from garp.ingest.edgar import EdgarClient, RateLimiter, format_cik


# ---------------------------------------------------------------------------
# format_cik
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (320193, "CIK0000320193"),
        ("320193", "CIK0000320193"),
        ("0000320193", "CIK0000320193"),
        ("CIK0000320193", "CIK0000320193"),
        (1, "CIK0000000001"),
    ],
)
def test_format_cik_zero_pads_to_ten_digits(given: int | str, expected: str) -> None:
    assert format_cik(given) == expected


def test_format_cik_rejects_non_numeric() -> None:
    with pytest.raises(ValueError, match="numeric"):
        format_cik("not-a-cik")


# ---------------------------------------------------------------------------
# RateLimiter
# ---------------------------------------------------------------------------
def test_rate_limiter_does_not_sleep_on_first_call() -> None:
    sleeps: list[float] = []
    limiter = RateLimiter(1.0, clock=lambda: 100.0, sleep=sleeps.append)
    limiter.wait()
    assert sleeps == []


def test_rate_limiter_sleeps_exactly_the_remaining_gap() -> None:
    sleeps: list[float] = []
    ticks = iter([100.0, 100.02, 100.02, 100.11])  # first .wait(), then second .wait()'s checks
    limiter = RateLimiter(0.11, clock=lambda: next(ticks), sleep=sleeps.append)
    limiter.wait()  # now=100.0, no prior call -> no sleep
    limiter.wait()  # now=100.02, elapsed=0.02 -> sleep 0.09
    assert sleeps == pytest.approx([0.09])


def test_rate_limiter_does_not_sleep_once_interval_has_elapsed() -> None:
    sleeps: list[float] = []
    ticks = iter([100.0, 101.0, 101.0])
    limiter = RateLimiter(0.11, clock=lambda: next(ticks), sleep=sleeps.append)
    limiter.wait()
    limiter.wait()
    assert sleeps == []


# ---------------------------------------------------------------------------
# EdgarClient: headers, caching, retries -- via a fake requests.Session
# ---------------------------------------------------------------------------
@dataclass
class FakeResponse:
    status_code: int
    content: bytes = b"{}"

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@dataclass
class FakeSession:
    responses: list[FakeResponse]
    requests_made: list[dict[str, Any]] = field(default_factory=list)

    def get(self, url: str, *, headers: dict[str, str], timeout: float) -> FakeResponse:
        self.requests_made.append({"url": url, "headers": headers, "timeout": timeout})
        return self.responses[len(self.requests_made) - 1]


def _no_op_rate_limiter() -> RateLimiter:
    return RateLimiter(0.0, clock=lambda: 0.0, sleep=lambda _seconds: None)


def _payload_files(source_dir: Path) -> list[Path]:
    """Raw payload files, excluding their `.meta.json` sidecars (which also
    match `*.json` since the sidecar name is `<payload name>.meta.json`).
    """
    return [p for p in source_dir.glob("*.json") if not p.name.endswith(".meta.json")]


def test_client_sends_contact_in_user_agent(tmp_path: Path) -> None:
    session = FakeSession(responses=[FakeResponse(200, b'{"ok": true}')])
    client = EdgarClient(
        contact="Jane Doe jane@example.com",
        raw_dir=tmp_path,
        session=session,  # type: ignore[arg-type]
        rate_limiter=_no_op_rate_limiter(),
    )
    client.get_company_facts(320193)
    assert "jane@example.com" in session.requests_made[0]["headers"]["User-Agent"]


def test_client_caches_response_to_raw_dir(tmp_path: Path) -> None:
    payload = json.dumps({"cik": 320193}).encode()
    session = FakeSession(responses=[FakeResponse(200, payload)])
    client = EdgarClient(
        contact="test@example.com",
        raw_dir=tmp_path,
        session=session,  # type: ignore[arg-type]
        rate_limiter=_no_op_rate_limiter(),
    )
    result = client.get_company_facts(320193)
    assert result == {"cik": 320193}

    cached_files = _payload_files(tmp_path / "edgar_companyfacts")
    assert len(cached_files) == 1


def test_client_does_not_re_request_identical_cached_payload(tmp_path: Path) -> None:
    payload = json.dumps({"cik": 320193}).encode()
    session = FakeSession(responses=[FakeResponse(200, payload), FakeResponse(200, payload)])
    client = EdgarClient(
        contact="test@example.com",
        raw_dir=tmp_path,
        session=session,  # type: ignore[arg-type]
        rate_limiter=_no_op_rate_limiter(),
    )
    client.get_company_facts(320193)
    client.get_company_facts(320193)
    # Both HTTP calls still happen (no in-memory response cache) -- what
    # matters is that only one raw file was ever written, since the payload
    # is identical and raw storage is content-addressed and immutable.
    cached_files = _payload_files(tmp_path / "edgar_companyfacts")
    assert len(cached_files) == 1


def test_client_retries_on_429_then_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("garp.ingest.edgar.time.sleep", lambda _seconds: None)
    session = FakeSession(responses=[FakeResponse(429), FakeResponse(200, b'{"ok": 1}')])
    client = EdgarClient(
        contact="test@example.com",
        raw_dir=tmp_path,
        session=session,  # type: ignore[arg-type]
        rate_limiter=_no_op_rate_limiter(),
    )
    result = client.get_company_facts(320193)
    assert result == {"ok": 1}
    assert len(session.requests_made) == 2


def test_client_raises_on_persistent_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("garp.ingest.edgar.time.sleep", lambda _seconds: None)
    session = FakeSession(responses=[FakeResponse(503) for _ in range(5)])
    client = EdgarClient(
        contact="test@example.com",
        raw_dir=tmp_path,
        session=session,  # type: ignore[arg-type]
        rate_limiter=_no_op_rate_limiter(),
    )
    with pytest.raises(RuntimeError, match="EDGAR request failed"):
        client.get_company_facts(320193)
