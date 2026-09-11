"""CIK <-> ticker identity mapping.

SEC's `company_tickers.json` is the only free source of this mapping and it
is a **current snapshot**, not a point-in-time history: it tells you what
ticker a CIK has *today*, not what ticker (if any) it had on an arbitrary
past date. A CIK's ticker can change (rebrand, uplisting, post-bankruptcy
relaunch) without any free record of when the change took effect. This is a
registered limitation -- see KNOWN_BIASES.md -- not a silent assumption:
downstream code should join on CIK wherever possible and treat this table's
ticker column as "best current label," never as proof a ticker was valid on
a historical date.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl

from garp.ingest.edgar import EdgarClient
from garp.logging import get_logger

logger = get_logger(__name__)

_SCHEMA: dict[str, Any] = {"cik": pl.Int64, "ticker": pl.Utf8, "title": pl.Utf8}


def cik_ticker_map_path(interim_dir: Path) -> Path:
    return interim_dir / "cik_ticker_map.parquet"


def build_cik_ticker_map(client: EdgarClient, *, interim_dir: Path) -> pl.DataFrame:
    """Fetch and persist the current CIK<->ticker<->title mapping."""
    raw = client.get_ticker_map()
    rows = [
        {"cik": int(entry["cik_str"]), "ticker": entry["ticker"], "title": entry["title"]}
        for entry in raw.values()
    ]
    table = pl.DataFrame(rows, schema=_SCHEMA)

    path = cik_ticker_map_path(interim_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    table.write_parquet(path)

    logger.info("cik_ticker_map_ingested", rows=table.height, path=str(path))
    return table


def cik_for_ticker(table: pl.DataFrame, ticker: str) -> int | None:
    """Look up a CIK by its *current* ticker. See module docstring."""
    matches = table.filter(pl.col("ticker") == ticker.upper())
    if matches.is_empty():
        return None
    return int(matches["cik"][0])
