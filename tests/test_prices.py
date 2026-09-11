"""Tests for garp.ingest.prices.compute_adjusted_close: the query-time
split/dividend adjustment that replaces storing pre-adjusted prices (SPEC.md
Phase 1, and KNOWN_BIASES.md's "pre-adjusted price series" row).
"""

from __future__ import annotations

from datetime import date

import polars as pl

from garp.ingest.prices import compute_adjusted_close


def _prices(rows: list[tuple[date, float]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ticker": ["TEST"] * len(rows),
            "date": [r[0] for r in rows],
            "open": [r[1] for r in rows],
            "high": [r[1] for r in rows],
            "low": [r[1] for r in rows],
            "close": [r[1] for r in rows],
            "volume": [1000] * len(rows),
        }
    )


def test_split_adjusts_prices_before_the_ex_date_only() -> None:
    prices = _prices(
        [(date(2024, 1, 1), 100.0), (date(2024, 1, 2), 101.0), (date(2024, 1, 3), 52.0)]
    )
    # 2-for-1 split effective 2024-01-03: pre-split prices halve.
    actions = pl.DataFrame(
        {"ticker": ["TEST"], "ex_date": [date(2024, 1, 3)], "action": ["split"], "value": [2.0]}
    )
    result = compute_adjusted_close(prices, actions).sort("date")
    assert result["adjusted_close"].to_list() == [50.0, 50.5, 52.0]


def test_split_after_asof_is_not_applied_even_to_earlier_prices() -> None:
    """The point-in-time contract: a split that hasn't happened yet as of
    the decision date must not leak into the adjusted series at all, even
    for prices dated before the split.
    """
    prices = _prices([(date(2024, 1, 1), 100.0), (date(2024, 1, 2), 101.0)])
    actions = pl.DataFrame(
        {"ticker": ["TEST"], "ex_date": [date(2024, 6, 1)], "action": ["split"], "value": [2.0]}
    )
    result = compute_adjusted_close(prices, actions, asof=date(2024, 1, 15)).sort("date")
    assert result["adjusted_close"].to_list() == [100.0, 101.0]


def test_split_before_asof_is_applied() -> None:
    prices = _prices([(date(2024, 1, 1), 100.0), (date(2024, 6, 2), 52.0)])
    actions = pl.DataFrame(
        {"ticker": ["TEST"], "ex_date": [date(2024, 6, 1)], "action": ["split"], "value": [2.0]}
    )
    result = compute_adjusted_close(prices, actions, asof=date(2024, 7, 1)).sort("date")
    assert result["adjusted_close"].to_list() == [50.0, 52.0]


def test_no_actions_leaves_close_unchanged() -> None:
    prices = _prices([(date(2024, 1, 1), 100.0)])
    actions = pl.DataFrame(
        schema={"ticker": pl.Utf8, "ex_date": pl.Date, "action": pl.Utf8, "value": pl.Float64}
    )
    result = compute_adjusted_close(prices, actions)
    assert result["adjusted_close"].to_list() == [100.0]


def test_dividend_scales_down_prices_before_ex_date() -> None:
    prices = _prices([(date(2024, 1, 1), 100.0), (date(2024, 1, 2), 99.0)])
    actions = pl.DataFrame(
        {"ticker": ["TEST"], "ex_date": [date(2024, 1, 2)], "action": ["dividend"], "value": [1.0]}
    )
    result = compute_adjusted_close(prices, actions).sort("date")
    # Prior close (2024-01-01) is 100.0; factor = 1 - 1.0/100.0 = 0.99.
    assert result["adjusted_close"][0] == 99.0
    assert result["adjusted_close"][1] == 99.0  # on/after ex-date: unchanged
