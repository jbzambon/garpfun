"""SEC EDGAR client: rate-limited, cached, point-in-time-friendly fetches.

Three endpoints matter for this project:

- `company_tickers.json` -- the *current* ticker <-> CIK <-> name mapping.
  This is a present-day snapshot, not a point-in-time history (see
  KNOWN_BIASES.md); it's the identity join Phase 2 needs, not a source of
  historical ticker validity ranges.
- `submissions/CIK##########.json` -- filing history and metadata (form
  type, filing date, accession number) plus former company names.
- `api/xbrl/companyfacts/CIK##########.json` -- the full XBRL fact set for
  a company, across all tags and all filings. Every fact carries its own
  `filed` date, which is exactly the point-in-time key SPEC.md principle #1
  requires (see garp.ingest.concepts).

Identity is CIK, never ticker (SPEC.md Phase 1: "tickers get reused and
reassigned").
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import requests

from garp.ingest.raw_store import CachedResponse, store
from garp.logging import get_logger

logger = get_logger(__name__)

_BASE_SUBMISSIONS_URL = "https://data.sec.gov/submissions"
_BASE_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts"
_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_MAX_RETRIES = 5


def format_cik(cik: int | str) -> str:
    """Zero-pad a CIK to SEC's canonical 10-digit `CIK##########` form."""
    digits = str(cik).strip().removeprefix("CIK").lstrip("0")
    if not digits.isdigit() and digits != "":
        raise ValueError(f"CIK must be numeric, got {cik!r}")
    return f"CIK{int(digits or 0):010d}"


class RateLimiter:
    """Enforces a minimum interval between calls to `.wait()`.

    Clock and sleep are injectable so tests can assert the enforced spacing
    without real wall-clock delay (SPEC.md principle #5: deterministic).
    """

    def __init__(
        self,
        min_interval_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._min_interval = min_interval_seconds
        self._clock = clock
        self._sleep = sleep
        self._last_call: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self._last_call is not None:
            elapsed = now - self._last_call
            remaining = self._min_interval - elapsed
            if remaining > 0:
                self._sleep(remaining)
                now = self._clock()
        self._last_call = now


class EdgarClient:
    """Rate-limited, disk-cached client for the SEC EDGAR APIs above."""

    def __init__(
        self,
        *,
        contact: str,
        raw_dir: Path,
        min_request_interval_seconds: float = 0.11,
        session: requests.Session | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self._contact = contact
        self._raw_dir = raw_dir
        self._session = session or requests.Session()
        self._rate_limiter = rate_limiter or RateLimiter(min_request_interval_seconds)

    def _headers(self) -> dict[str, str]:
        # SEC's documented convention is "<company/app name> <contact>";
        # see https://www.sec.gov/os/webmaster-faq#developers.
        return {"User-Agent": f"garp-research ({self._contact})"}

    def _get_bytes(self, url: str, *, source: str) -> CachedResponse:
        digest_suffix = ".json" if url.endswith(".json") else ""
        last_error: Exception | None = None
        for attempt in range(1, _MAX_RETRIES + 1):
            self._rate_limiter.wait()
            try:
                response = self._session.get(url, headers=self._headers(), timeout=30)
            except requests.RequestException as exc:  # network-level failure
                last_error = exc
                logger.warning("edgar_request_error", url=url, attempt=attempt, error=str(exc))
                continue

            if response.status_code == 200:
                return store(
                    raw_dir=self._raw_dir,
                    source=source,
                    url=url,
                    payload=response.content,
                    suffix=digest_suffix,
                    extra={"status_code": response.status_code},
                )

            last_error = RuntimeError(f"HTTP {response.status_code} from {url}")
            if response.status_code in _RETRYABLE_STATUS_CODES and attempt < _MAX_RETRIES:
                backoff = min(2**attempt * 0.5, 30.0)
                logger.warning(
                    "edgar_retryable_status",
                    url=url,
                    status_code=response.status_code,
                    attempt=attempt,
                    backoff_seconds=backoff,
                )
                time.sleep(backoff)
                continue

            # Non-retryable status (e.g. 404), or retries exhausted: stop
            # immediately rather than burning the remaining attempts.
            break

        raise RuntimeError(
            f"EDGAR request failed after {_MAX_RETRIES} attempts: {url}"
        ) from last_error

    def get_ticker_map(self) -> dict[str, Any]:
        """Fetch the *current* ticker <-> CIK <-> title mapping.

        Not point-in-time -- see module docstring and KNOWN_BIASES.md.
        """
        cached = self._get_bytes(_TICKERS_URL, source="edgar_tickers")
        return _load_json(cached.payload)

    def get_submissions(self, cik: int | str) -> dict[str, Any]:
        """Fetch filing history/metadata for one company."""
        url = f"{_BASE_SUBMISSIONS_URL}/{format_cik(cik)}.json"
        cached = self._get_bytes(url, source="edgar_submissions")
        return _load_json(cached.payload)

    def get_company_facts(self, cik: int | str) -> dict[str, Any]:
        """Fetch the full XBRL fact set for one company."""
        url = f"{_BASE_COMPANYFACTS_URL}/{format_cik(cik)}.json"
        cached = self._get_bytes(url, source="edgar_companyfacts")
        return _load_json(cached.payload)


def _load_json(payload: bytes) -> dict[str, Any]:
    result: dict[str, Any] = json.loads(payload)
    return result
