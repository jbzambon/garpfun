"""Tests for garp.ingest.pit: the point-in-time `as_of` filter and
`latest_as_of` aggregation that every other module is supposed to build on.
"""

from __future__ import annotations

from datetime import date

import polars as pl

from garp.ingest.pit import as_of, latest_as_of


def test_as_of_excludes_rows_known_after_the_cutoff() -> None:
    df = pl.DataFrame(
        {"filed": [date(2024, 1, 1), date(2024, 2, 20), date(2024, 6, 1)], "value": [1, 2, 3]}
    )
    result = as_of(df, "filed", date(2024, 2, 19))
    assert result["value"].to_list() == [1]


def test_as_of_includes_rows_exactly_on_the_cutoff() -> None:
    df = pl.DataFrame({"filed": [date(2024, 2, 20)], "value": [1]})
    result = as_of(df, "filed", date(2024, 2, 20))
    assert result.height == 1


def test_latest_as_of_picks_most_recent_filing_per_group() -> None:
    df = pl.DataFrame(
        {
            "cik": [1, 1, 1, 2],
            "concept": ["revenue", "revenue", "revenue", "revenue"],
            "filed": [date(2024, 2, 20), date(2024, 6, 1), date(2025, 2, 15), date(2024, 3, 1)],
            "value": [100.0, 105.0, 110.0, 50.0],
        }
    )
    # As of March 2024, cik 1's amended value (filed June) isn't visible yet;
    # the Feb 2025 filing definitely isn't. Only the original filing counts.
    result = latest_as_of(
        df, date_col="filed", group_cols=["cik", "concept"], asof=date(2024, 3, 1)
    )
    cik1 = result.filter(pl.col("cik") == 1)
    assert cik1.height == 1
    assert cik1["value"][0] == 100.0

    # As of July 2024, the amendment is visible and wins.
    result_july = latest_as_of(
        df, date_col="filed", group_cols=["cik", "concept"], asof=date(2024, 7, 1)
    )
    cik1_july = result_july.filter(pl.col("cik") == 1)
    assert cik1_july.height == 1
    assert cik1_july["value"][0] == 105.0


def test_latest_as_of_returns_empty_when_nothing_is_known_yet() -> None:
    df = pl.DataFrame({"cik": [1], "filed": [date(2024, 6, 1)], "value": [1.0]})
    result = latest_as_of(df, date_col="filed", group_cols=["cik"], asof=date(2024, 1, 1))
    assert result.is_empty()
