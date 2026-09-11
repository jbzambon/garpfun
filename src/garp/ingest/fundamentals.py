"""Orchestrates EDGAR fetch + concept normalization into a stored,
point-in-time fundamentals panel.

One parquet file per CIK under `data/interim/fundamentals/`, long-format
(one row per concept-fact), so Phase 3's factor functions can pivot and
`as_of`-filter however they need without this layer guessing their shape in
advance.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from garp.ingest.concepts import extract_all_concepts
from garp.ingest.edgar import EdgarClient
from garp.logging import get_logger

logger = get_logger(__name__)


def fundamentals_path(interim_dir: Path, cik: int) -> Path:
    return interim_dir / "fundamentals" / f"{cik:010d}.parquet"


def ingest_fundamentals(client: EdgarClient, cik: int, *, interim_dir: Path) -> pl.DataFrame:
    """Fetch one company's XBRL facts, normalize, and persist as parquet.

    Raw JSON is cached immutably by `EdgarClient` regardless; this function
    additionally writes the *normalized* long-format table, which is
    re-derived (safe to delete and regenerate from the raw cache) rather
    than itself being a source of truth.
    """
    facts = client.get_company_facts(cik)
    entity_name = facts.get("entityName", "<unknown>")
    table = extract_all_concepts(facts, cik=cik)

    path = fundamentals_path(interim_dir, cik)
    path.parent.mkdir(parents=True, exist_ok=True)
    table.write_parquet(path)

    concepts_found = table["concept"].unique().to_list() if not table.is_empty() else []
    logger.info(
        "fundamentals_ingested",
        cik=cik,
        entity_name=entity_name,
        rows=table.height,
        concepts_found=sorted(concepts_found),
        path=str(path),
    )
    return table
