"""Tests for the `garp data` CLI command (Phase 1)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl
import pytest
from click.testing import CliRunner

from garp import cli
from garp.config import Settings


def test_data_fails_clearly_when_contact_is_not_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GARP_SEC_CONTACT", raising=False)
    monkeypatch.chdir(tmp_path)  # no .env here, unlike the real repo root
    runner = CliRunner()
    result = runner.invoke(cli.main, ["data"])
    assert result.exit_code != 0
    assert "GARP_SEC_CONTACT" in str(result.exception)


def test_data_refreshes_ticker_map_only_when_no_tickers_or_ciks_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: dict[str, Any] = {"fundamentals": [], "prices": []}

    monkeypatch.setattr(
        cli, "load_settings", lambda: Settings(sec_contact="t@example.com", data_dir=tmp_path)
    )
    monkeypatch.setattr(cli, "EdgarClient", lambda **_kwargs: object())
    monkeypatch.setattr(
        cli,
        "build_cik_ticker_map",
        lambda _client, *, interim_dir: pl.DataFrame(
            {"cik": [1], "ticker": ["AAA"], "title": ["Test Co"]}
        ),
    )
    monkeypatch.setattr(
        cli,
        "ingest_fundamentals",
        lambda _client, cik, *, interim_dir: calls["fundamentals"].append(cik),
    )
    monkeypatch.setattr(
        cli,
        "ingest_prices",
        lambda ticker, *, interim_dir, start=None, end=None: calls["prices"].append(ticker),
    )

    runner = CliRunner()
    result = runner.invoke(cli.main, ["data"])

    assert result.exit_code == 0
    assert calls["fundamentals"] == []
    assert calls["prices"] == []
    assert "only" in result.output


def test_data_ingests_given_tickers_and_ciks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: dict[str, Any] = {"fundamentals": [], "prices": []}

    monkeypatch.setattr(
        cli, "load_settings", lambda: Settings(sec_contact="t@example.com", data_dir=tmp_path)
    )
    monkeypatch.setattr(cli, "EdgarClient", lambda **_kwargs: object())
    monkeypatch.setattr(
        cli,
        "build_cik_ticker_map",
        lambda _client, *, interim_dir: pl.DataFrame(
            {"cik": [42], "ticker": ["ZZZ"], "title": ["Test Co"]}
        ),
    )
    monkeypatch.setattr(
        cli,
        "ingest_fundamentals",
        lambda _client, cik, *, interim_dir: calls["fundamentals"].append(cik),
    )
    monkeypatch.setattr(
        cli,
        "ingest_prices",
        lambda ticker, *, interim_dir, start=None, end=None: calls["prices"].append(ticker),
    )

    runner = CliRunner()
    result = runner.invoke(cli.main, ["data", "--tickers", "zzz", "--ciks", "7"])

    assert result.exit_code == 0, result.output
    assert calls["fundamentals"] == [7, 42]  # explicit CIK, then the resolved ticker's CIK
    assert calls["prices"] == ["ZZZ"]


def test_data_warns_but_continues_when_ticker_not_in_cik_map(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: dict[str, Any] = {"fundamentals": [], "prices": []}

    monkeypatch.setattr(
        cli, "load_settings", lambda: Settings(sec_contact="t@example.com", data_dir=tmp_path)
    )
    monkeypatch.setattr(cli, "EdgarClient", lambda **_kwargs: object())
    monkeypatch.setattr(
        cli,
        "build_cik_ticker_map",
        lambda _client, *, interim_dir: pl.DataFrame(
            {"cik": [], "ticker": [], "title": []},
            schema={"cik": pl.Int64, "ticker": pl.Utf8, "title": pl.Utf8},
        ),
    )
    monkeypatch.setattr(
        cli,
        "ingest_fundamentals",
        lambda _client, cik, *, interim_dir: calls["fundamentals"].append(cik),
    )
    monkeypatch.setattr(
        cli,
        "ingest_prices",
        lambda ticker, *, interim_dir, start=None, end=None: calls["prices"].append(ticker),
    )

    runner = CliRunner()
    result = runner.invoke(cli.main, ["data", "--tickers", "UNKNOWN"])

    assert result.exit_code == 0, result.output
    assert calls["fundamentals"] == []
    assert calls["prices"] == ["UNKNOWN"]  # prices are still fetched by ticker directly
