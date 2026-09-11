"""Tests for garp.ingest.tickers: the CIK<->ticker mapping table."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from garp.ingest.tickers import build_cik_ticker_map, cik_for_ticker


class _FakeClient:
    def get_ticker_map(self) -> dict[str, Any]:
        return {
            "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
            "1": {"cik_str": 1341439, "ticker": "ORCL", "title": "Oracle Corp"},
        }


def test_build_cik_ticker_map_persists_and_returns_table(tmp_path: Path) -> None:
    table = build_cik_ticker_map(_FakeClient(), interim_dir=tmp_path)  # type: ignore[arg-type]
    assert table.height == 2
    assert set(table["ticker"]) == {"AAPL", "ORCL"}
    assert (tmp_path / "cik_ticker_map.parquet").is_file()


def test_cik_for_ticker_is_case_insensitive(tmp_path: Path) -> None:
    table = build_cik_ticker_map(_FakeClient(), interim_dir=tmp_path)  # type: ignore[arg-type]
    assert cik_for_ticker(table, "aapl") == 320193
    assert cik_for_ticker(table, "AAPL") == 320193


def test_cik_for_ticker_returns_none_when_not_found(tmp_path: Path) -> None:
    table = build_cik_ticker_map(_FakeClient(), interim_dir=tmp_path)  # type: ignore[arg-type]
    assert cik_for_ticker(table, "NOPE") is None
