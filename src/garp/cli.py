"""Command-line entry point.

Phase 0 wires up the command surface with stubs so the Makefile targets and
overall shape are in place before any strategy logic exists. Each subcommand
is filled in during its corresponding phase (see SPEC.md).
"""

from __future__ import annotations

import click

from garp.logging import configure_logging, get_logger

logger = get_logger(__name__)


@click.group()
@click.option("--verbose", is_flag=True, help="Enable debug-level logging.")
def main(*, verbose: bool) -> None:
    """GARP screener and point-in-time backtest harness."""
    configure_logging(level=10 if verbose else 20)


@main.command()
def data() -> None:
    """Fetch and cache raw data (Phase 1: ingest)."""
    raise NotImplementedError(
        "Phase 1 (data layer) is not implemented yet. See SPEC.md Phase 1: "
        "SEC EDGAR fundamentals ingest, price ingest, corporate actions."
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
