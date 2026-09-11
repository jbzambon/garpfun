"""The single highest-leverage function in this codebase.

SPEC.md principle #1: a decision made on date `T` may only use information
that was publicly available on or before `T`. Every module that joins data
against a decision date -- fundamentals, prices, universe membership,
factors -- should filter through `as_of` (or a bespoke variant that composes
with it) rather than re-implementing this comparison inline, so the one
place this could go wrong stays reviewable and tested in one place.
"""

from __future__ import annotations

from datetime import date

import polars as pl


def as_of(df: pl.DataFrame, date_col: str, asof: date) -> pl.DataFrame:
    """Return only rows whose `date_col` is known on or before `asof`.

    `date_col` should be the date something became *public* (a filing date,
    a corporate-action ex-date) -- never a period-end date, which is exactly
    the mistake principle #1 exists to prevent.
    """
    return df.filter(pl.col(date_col) <= asof)


def latest_as_of(
    df: pl.DataFrame,
    *,
    date_col: str,
    group_cols: list[str],
    asof: date,
) -> pl.DataFrame:
    """The most-recently-known row per group, as of `asof`.

    E.g. the latest filed value per (cik, concept) as of a rebalance date --
    later amendments only take effect once *they* are filed, which falls out
    naturally here because filtering happens on `date_col` before taking the
    max.
    """
    filtered = as_of(df, date_col, asof)
    if filtered.is_empty():
        return filtered
    latest_dates = filtered.group_by(group_cols).agg(pl.col(date_col).max().alias(date_col))
    return filtered.join(latest_dates, on=[*group_cols, date_col], how="inner")
