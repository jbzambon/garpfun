"""Price ingest: unadjusted OHLCV plus a separate corporate-actions table,
with split/dividend adjustment computed at query time -- never stored
pre-adjusted.

`yfinance` is explicitly a Phase-1 plumbing/dev-only source (SPEC.md Phase
1): it silently drops delisted tickers, which is survivorship bias baked
into the source and unacceptable for a final backtest result (see
KNOWN_BIASES.md, row 1). It's used here because it's free and sufficient to
build and test the pipeline end to end; a final backtest needs a source with
confirmed delisted-security coverage (Sharadar SEP/SFP, Tiingo, Polygon).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import yfinance as yf

from garp.ingest.pit import as_of
from garp.logging import get_logger

logger = get_logger(__name__)

_PRICE_SCHEMA: dict[str, Any] = {
    "ticker": pl.Utf8,
    "date": pl.Date,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Int64,
}

_ACTIONS_SCHEMA: dict[str, Any] = {
    "ticker": pl.Utf8,
    "ex_date": pl.Date,
    "action": pl.Utf8,  # "split" | "dividend"
    "value": pl.Float64,  # split: ratio (e.g. 2.0 for 2-for-1); dividend: cash amount/share
}


def _safe_filename(ticker: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in ticker.upper())


def prices_path(interim_dir: Path, ticker: str) -> Path:
    return interim_dir / "prices" / f"{_safe_filename(ticker)}_prices.parquet"


def actions_path(interim_dir: Path, ticker: str) -> Path:
    return interim_dir / "prices" / f"{_safe_filename(ticker)}_actions.parquet"


def fetch_price_history(
    ticker: str, *, start: date | None = None, end: date | None = None
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Fetch raw unadjusted OHLCV and a corporate-actions table for `ticker`.

    Returns `(prices, actions)`. `prices.close` is genuinely unadjusted
    (`auto_adjust=False`); splits and dividends come back as separate rows
    in `actions` rather than being baked into any price column.
    """
    logger.warning(
        "yfinance_survivorship_bias",
        ticker=ticker,
        note="yfinance silently omits delisted tickers; not acceptable for final results",
    )
    handle = yf.Ticker(ticker)
    history: Any = handle.history(start=start, end=end, auto_adjust=False, actions=True)

    if history.empty:
        logger.warning("no_price_history", ticker=ticker, start=start, end=end)
        return pl.DataFrame(schema=_PRICE_SCHEMA), pl.DataFrame(schema=_ACTIONS_SCHEMA)

    history = history.reset_index()
    date_col = "Date" if "Date" in history.columns else "Datetime"
    pdf = pl.from_pandas(history).rename({date_col: "date"})
    pdf = pdf.with_columns(pl.col("date").cast(pl.Date))

    prices = pdf.select(
        pl.lit(ticker.upper()).alias("ticker"),
        pl.col("date"),
        pl.col("Open").alias("open"),
        pl.col("High").alias("high"),
        pl.col("Low").alias("low"),
        pl.col("Close").alias("close"),
        pl.col("Volume").cast(pl.Int64).alias("volume"),
    )

    action_frames = []
    if "Dividends" in pdf.columns:
        dividends = pdf.filter(pl.col("Dividends") != 0).select(
            pl.lit(ticker.upper()).alias("ticker"),
            pl.col("date").alias("ex_date"),
            pl.lit("dividend").alias("action"),
            pl.col("Dividends").alias("value"),
        )
        action_frames.append(dividends)
    if "Stock Splits" in pdf.columns:
        splits = pdf.filter(pl.col("Stock Splits") != 0).select(
            pl.lit(ticker.upper()).alias("ticker"),
            pl.col("date").alias("ex_date"),
            pl.lit("split").alias("action"),
            pl.col("Stock Splits").alias("value"),
        )
        action_frames.append(splits)

    actions = (
        pl.concat(action_frames, how="vertical").sort("ex_date")
        if action_frames and any(not f.is_empty() for f in action_frames)
        else pl.DataFrame(schema=_ACTIONS_SCHEMA)
    )

    logger.info(
        "prices_ingested", ticker=ticker, price_rows=prices.height, action_rows=actions.height
    )
    return prices, actions


def ingest_prices(
    ticker: str, *, interim_dir: Path, start: date | None = None, end: date | None = None
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Fetch and persist `fetch_price_history`'s output as parquet."""
    prices, actions = fetch_price_history(ticker, start=start, end=end)

    p_path, a_path = prices_path(interim_dir, ticker), actions_path(interim_dir, ticker)
    p_path.parent.mkdir(parents=True, exist_ok=True)
    prices.write_parquet(p_path)
    actions.write_parquet(a_path)

    return prices, actions


def compute_adjusted_close(
    prices: pl.DataFrame, actions: pl.DataFrame, *, asof: date | None = None
) -> pl.DataFrame:
    """Compute a split/dividend-adjusted close, using only actions known as
    of `asof` (default: all actions in the table).

    This is the query-time computation SPEC.md Phase 1 requires in place of
    storing pre-adjusted prices: a split or dividend with `ex_date > asof`
    is excluded entirely, so a decision made on `asof` never reflects a
    corporate action that, as of that date, hadn't happened yet.

    Split adjustment is an exact cumulative ratio. Dividend adjustment is
    the standard approximation vendors use for a "total return" series --
    scale prices before the ex-date by `1 - dividend / prior_close` -- not
    exact reinvestment accounting.
    """
    known_actions = actions if asof is None else as_of(actions, "ex_date", asof)
    result = prices.sort("date").with_columns(pl.col("close").alias("adjusted_close"))

    splits = known_actions.filter(pl.col("action") == "split").sort("ex_date", descending=True)
    for row in splits.iter_rows(named=True):
        ex_date, ratio = row["ex_date"], row["value"]
        if not ratio:
            continue
        result = result.with_columns(
            pl.when(pl.col("date") < ex_date)
            .then(pl.col("adjusted_close") / ratio)
            .otherwise(pl.col("adjusted_close"))
            .alias("adjusted_close")
        )

    dividends = known_actions.filter(pl.col("action") == "dividend").sort(
        "ex_date", descending=True
    )
    for row in dividends.iter_rows(named=True):
        ex_date, amount = row["ex_date"], row["value"]
        if not amount:
            continue
        prior = result.filter(pl.col("date") < ex_date).sort("date").tail(1)
        if prior.is_empty():
            continue
        prior_close = prior["adjusted_close"][0]
        if not prior_close:
            continue
        factor = max(0.0, 1 - amount / prior_close)
        result = result.with_columns(
            pl.when(pl.col("date") < ex_date)
            .then(pl.col("adjusted_close") * factor)
            .otherwise(pl.col("adjusted_close"))
            .alias("adjusted_close")
        )

    return result
