"""Command-line entry point.

Phase 0 wired up the command surface with stubs so the Makefile targets and
overall shape were in place before any strategy logic existed. Each
subcommand is filled in during its corresponding phase (see SPEC.md); `data`
(Phase 1) is now live, the rest are still stubs.
"""

from __future__ import annotations

from datetime import date

import click

from garp.config import load_settings
from garp.ingest.edgar import EdgarClient
from garp.ingest.fundamentals import ingest_fundamentals
from garp.ingest.prices import ingest_prices
from garp.ingest.tickers import build_cik_ticker_map, cik_for_ticker
from garp.logging import configure_logging, get_logger

logger = get_logger(__name__)


@click.group()
@click.option("--verbose", is_flag=True, help="Enable debug-level logging.")
def main(*, verbose: bool) -> None:
    """GARP screener and point-in-time backtest harness."""
    configure_logging(level=10 if verbose else 20)


@main.command()
@click.option("--tickers", default="", help="Comma-separated tickers (fundamentals + prices).")
@click.option("--ciks", default="", help="Comma-separated CIKs (fundamentals only).")
@click.option("--start", "start_str", default=None, help="Price history start date (YYYY-MM-DD).")
@click.option(
    "--end", "end_str", default=None, help="Price history end date (YYYY-MM-DD, default: today)."
)
def data(*, tickers: str, ciks: str, start_str: str | None, end_str: str | None) -> None:
    """Fetch and cache raw data (Phase 1: ingest).

    Always refreshes the CIK<->ticker map (see garp.ingest.tickers). With no
    --tickers/--ciks given, that refresh is all that happens -- Phase 2
    (universe construction) is what will drive this at scale; for now this
    is aimed at ingesting a specific, small set of names to develop against.

    Without --start, yfinance defaults to a short recent window, which is
    fine for a quick plumbing check but not for developing point-in-time
    joins against -- pass --start (e.g. --start 2015-01-01) for that.
    """
    settings = load_settings()
    client = EdgarClient(
        contact=settings.sec_contact,
        raw_dir=settings.raw_dir,
        min_request_interval_seconds=settings.min_request_interval_seconds,
    )

    ticker_map = build_cik_ticker_map(client, interim_dir=settings.interim_dir)

    cik_list = [int(c.strip()) for c in ciks.split(",") if c.strip()]
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    start = date.fromisoformat(start_str) if start_str else None
    end = date.fromisoformat(end_str) if end_str else None

    for cik in cik_list:
        ingest_fundamentals(client, cik, interim_dir=settings.interim_dir)

    for ticker in ticker_list:
        resolved_cik = cik_for_ticker(ticker_map, ticker)
        if resolved_cik is None:
            logger.warning("ticker_not_found_in_cik_map", ticker=ticker)
        else:
            ingest_fundamentals(client, resolved_cik, interim_dir=settings.interim_dir)
        ingest_prices(ticker, interim_dir=settings.interim_dir, start=start, end=end)

    if not cik_list and not ticker_list:
        click.echo(
            "No --tickers/--ciks given; refreshed the CIK<->ticker map only. "
            "Example: garp data --tickers SMCI,PLXS --start 2015-01-01"
        )


@main.command()
def universe() -> None:
    """Build the point-in-time universe panel (Phase 2)."""
    raise NotImplementedError(
        "Phase 2 (universe construction) is not implemented yet. See SPEC.md Phase 2."
    )


@main.command()
def factors() -> None:
    """Compute factor scores over the universe panel (Phase 3)."""
    raise NotImplementedError(
        "Phase 3 (factor computation) is not implemented yet. See SPEC.md Phase 3."
    )


@main.command()
def backtest() -> None:
    """Run the walk-forward backtest (Phase 4)."""
    raise NotImplementedError(
        "Phase 4 (backtest harness) is not implemented yet. See SPEC.md Phase 4."
    )


@main.command()
@click.option("--asof", default="today", show_default=True, help="As-of date for the live screen.")
def screen(*, asof: str) -> None:
    """Produce a ranked live candidate list (Phase 5)."""
    raise NotImplementedError(
        "Phase 5 (live screen) is not implemented yet. See SPEC.md Phase 5. "
        f"Requested asof={asof!r}."
    )


@main.command()
def report() -> None:
    """Render the HTML/markdown report with the bias register attached (Phase 5)."""
    raise NotImplementedError("Phase 5 (report) is not implemented yet. See SPEC.md Phase 5.")


if __name__ == "__main__":
    main()
