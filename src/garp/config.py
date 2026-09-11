"""Runtime configuration.

Values that are secrets, contact-identifying, or environment-specific live
here and are read from the environment (optionally via a local `.env`, which
is gitignored) -- never hardcoded, and never given a default that would leak
a real person's contact info into committed source.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_MIN_REQUEST_INTERVAL_SECONDS = 0.11  # ~9 req/s, under SEC's 10 req/s cap


class MissingSecContactError(RuntimeError):
    """Raised when no SEC EDGAR contact identifier is configured.

    SEC's fair-access policy for EDGAR (https://www.sec.gov/os/webmaster-faq#developers)
    requires every automated client to identify itself with a real contact
    (name and/or email) in the request User-Agent, and will rate-limit or
    block clients that don't. This is not optional plumbing -- refusing to
    silently substitute a fake value is the point.
    """

    def __init__(self) -> None:
        super().__init__(
            "GARP_SEC_CONTACT is not set. SEC EDGAR requires every API client "
            "to identify itself with a real contact (name and/or email) -- see "
            "https://www.sec.gov/os/webmaster-faq#developers. Set it in a local "
            "`.env` (see .env.example; .env is gitignored and never committed), "
            "e.g. GARP_SEC_CONTACT='Your Name your@email.example'."
        )


def _load_dotenv_if_present(path: Path) -> None:
    """Minimal `.env` loader: KEY=VALUE lines, no external dependency.

    Existing environment variables always win -- this only fills gaps, so a
    real deployment env can override a stray local `.env` value.
    """
    if not path.is_file():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    """Process-wide configuration, resolved once at startup."""

    sec_contact: str
    min_request_interval_seconds: float = _DEFAULT_MIN_REQUEST_INTERVAL_SECONDS
    data_dir: Path = Path("data")

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def interim_dir(self) -> Path:
        return self.data_dir / "interim"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"


def load_settings(*, repo_root: Path | None = None) -> Settings:
    """Resolve `Settings` from the environment (loading `.env` if present).

    Raises `MissingSecContactError` if no contact is configured -- callers
    that need EDGAR access should let this propagate rather than catching it,
    per SPEC.md: "if a data source can't support a principle above, say so
    explicitly."
    """
    root = repo_root or Path.cwd()
    _load_dotenv_if_present(root / ".env")

    contact = os.environ.get("GARP_SEC_CONTACT", "").strip()
    if not contact:
        raise MissingSecContactError

    interval_raw = os.environ.get("GARP_SEC_MIN_REQUEST_INTERVAL_SECONDS")
    min_interval = float(interval_raw) if interval_raw else _DEFAULT_MIN_REQUEST_INTERVAL_SECONDS

    data_dir = Path(os.environ.get("GARP_DATA_DIR", "data"))

    return Settings(
        sec_contact=contact,
        min_request_interval_seconds=min_interval,
        data_dir=data_dir,
    )
