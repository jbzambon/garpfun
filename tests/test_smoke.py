"""Phase 0 smoke tests: package imports, logging, and CLI wiring.

Strategy-logic tests (point-in-time joins, universe construction, factor
math) land in their respective phases.
"""

from __future__ import annotations

import hashlib

from click.testing import CliRunner

import garp
from garp.cli import main
from garp.logging import get_logger, hash_payload, log_fetch


def test_package_has_version() -> None:
    assert garp.__version__


def test_hash_payload_matches_sha256() -> None:
    payload = b"some raw filing bytes"
    assert hash_payload(payload) == hashlib.sha256(payload).hexdigest()


def test_hash_payload_is_deterministic() -> None:
    payload = b"identical bytes"
    assert hash_payload(payload) == hash_payload(payload)


def test_log_fetch_returns_payload_hash() -> None:
    logger = get_logger("test")
    payload = b"payload"
    digest = log_fetch(logger, source="sec_edgar", url="https://example.invalid/x", payload=payload)
    assert digest == hashlib.sha256(payload).hexdigest()


def test_cli_group_lists_all_phase_subcommands() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    for cmd in ("data", "universe", "factors", "backtest", "screen", "report"):
        assert cmd in result.output


def test_cli_unimplemented_phase_raises_with_useful_message() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["data"])
    assert result.exit_code != 0
    assert isinstance(result.exception, NotImplementedError)
    assert "Phase 1" in str(result.exception)
