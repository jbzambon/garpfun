"""Tests for garp.config: the SEC contact requirement must fail loudly, and
a local `.env` must never override an already-set real environment variable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from garp.config import MissingSecContactError, load_settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("GARP_SEC_CONTACT", "GARP_SEC_MIN_REQUEST_INTERVAL_SECONDS", "GARP_DATA_DIR"):
        monkeypatch.delenv(key, raising=False)


def test_missing_contact_raises_with_actionable_message(tmp_path: Path) -> None:
    with pytest.raises(MissingSecContactError, match="GARP_SEC_CONTACT"):
        load_settings(repo_root=tmp_path)


def test_contact_from_environment_is_used(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GARP_SEC_CONTACT", "Jane Doe jane@example.com")
    settings = load_settings(repo_root=tmp_path)
    assert settings.sec_contact == "Jane Doe jane@example.com"


def test_dotenv_file_is_loaded_when_env_var_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text('GARP_SEC_CONTACT="From Dotenv dotenv@example.com"\n')
    settings = load_settings(repo_root=tmp_path)
    assert settings.sec_contact == "From Dotenv dotenv@example.com"


def test_real_environment_wins_over_dotenv_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GARP_SEC_CONTACT", "Real Env real@example.com")
    (tmp_path / ".env").write_text("GARP_SEC_CONTACT=From Dotenv dotenv@example.com\n")
    settings = load_settings(repo_root=tmp_path)
    assert settings.sec_contact == "Real Env real@example.com"


def test_default_paths_and_rate_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GARP_SEC_CONTACT", "test@example.com")
    settings = load_settings(repo_root=tmp_path)
    assert settings.raw_dir == Path("data/raw")
    assert settings.interim_dir == Path("data/interim")
    assert settings.min_request_interval_seconds == pytest.approx(0.11)
