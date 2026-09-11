"""XBRL tag normalization: turn SEC EDGAR's tag chaos into a small, stable
set of canonical concepts.

Companies tag the same economic fact differently -- `Revenues` one year,
`RevenueFromContractWithCustomerExcludingAssessedTax` the next, after ASC 606
adoption changed the "standard" tag mid-history for half of corporate
America. SPEC.md Phase 1 requires an explicit fallback chain per concept and
logging of unmapped cases rather than silently filling nulls; that's what
this module does.

The point-in-time key for every extracted fact is `filed` (the date SEC
received the filing), never `start`/`end` (the fiscal period the fact
describes). A 10-K/A amendment is just a later, independent row with its own
`filed` date -- nothing special has to happen for amendments to be handled
correctly, *provided every downstream consumer joins on `filed` via
garp.ingest.pit.as_of and never on `end`*. That invariant is exactly what
tests/test_concepts.py checks.

Some concepts below (notably TOTAL_DEBT) have no single canonical us-gaap
tag industry-wide; the chains here are a best-effort single-tag fallback,
not a compound derivation. Computing e.g. total debt as a sum of current +
noncurrent components is Phase 3's job (factor computation), not this
module's -- this module's job stops at "here is what was actually filed,
under which tag, and when."
"""

from __future__ import annotations

from datetime import date
from typing import Any, NamedTuple

import polars as pl

from garp.logging import get_logger

logger = get_logger(__name__)


class ConceptTag(NamedTuple):
    taxonomy: str
    tag: str


# Canonical concept name -> ordered fallback chain of (taxonomy, tag).
# The first tag in the chain with any reported facts wins for a given
# company; which tag that was is preserved in the output's `tag` column so
# nothing is hidden.
CONCEPT_TAGS: dict[str, list[ConceptTag]] = {
    "revenue": [
        ConceptTag("us-gaap", "Revenues"),
        ConceptTag("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
        ConceptTag("us-gaap", "RevenueFromContractWithCustomerIncludingAssessedTax"),
        ConceptTag("us-gaap", "SalesRevenueNet"),
        ConceptTag("us-gaap", "SalesRevenueGoodsNet"),
    ],
    "net_income": [
        ConceptTag("us-gaap", "NetIncomeLoss"),
        ConceptTag("us-gaap", "ProfitLoss"),
    ],
    "diluted_eps": [
        ConceptTag("us-gaap", "EarningsPerShareDiluted"),
        ConceptTag("us-gaap", "EarningsPerShareBasicAndDiluted"),
    ],
    "shares_outstanding": [
        ConceptTag("dei", "EntityCommonStockSharesOutstanding"),
        ConceptTag("us-gaap", "CommonStockSharesOutstanding"),
    ],
    "total_assets": [
        ConceptTag("us-gaap", "Assets"),
    ],
    "total_liabilities": [
        ConceptTag("us-gaap", "Liabilities"),
    ],
    "total_debt": [
        ConceptTag("us-gaap", "DebtLongtermAndShorttermCombinedAmount"),
        ConceptTag("us-gaap", "LongTermDebtNoncurrent"),
        ConceptTag("us-gaap", "LongTermDebt"),
    ],
    "cash_and_equivalents": [
        ConceptTag("us-gaap", "CashAndCashEquivalentsAtCarryingValue"),
        ConceptTag("us-gaap", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
    ],
    "operating_cash_flow": [
        ConceptTag("us-gaap", "NetCashProvidedByUsedInOperatingActivities"),
        ConceptTag("us-gaap", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"),
    ],
    "capex": [
        ConceptTag("us-gaap", "PaymentsToAcquirePropertyPlantAndEquipment"),
        ConceptTag("us-gaap", "PaymentsToAcquireProductiveAssets"),
    ],
    "shareholders_equity": [
        ConceptTag("us-gaap", "StockholdersEquity"),
        ConceptTag(
            "us-gaap", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"
        ),
    ],
}

_SCHEMA: dict[str, Any] = {
    "cik": pl.Int64,
    "concept": pl.Utf8,
    "taxonomy": pl.Utf8,
    "tag": pl.Utf8,
    "unit": pl.Utf8,
    "value": pl.Float64,
    "fiscal_year": pl.Int64,
    "fiscal_period": pl.Utf8,
    "period_start": pl.Date,
    "period_end": pl.Date,
    "filed": pl.Date,
    "form": pl.Utf8,
    "accession_number": pl.Utf8,
    "frame": pl.Utf8,
}


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def _facts_for_tag(facts: dict[str, Any], taxonomy: str, tag: str) -> dict[str, Any] | None:
    taxonomy_facts = facts.get("facts", {}).get(taxonomy)
    if not taxonomy_facts:
        return None
    tag_facts: dict[str, Any] | None = taxonomy_facts.get(tag)
    return tag_facts


def extract_concept(facts: dict[str, Any], concept: str, *, cik: int) -> pl.DataFrame:
    """Extract every reported datapoint for one canonical concept.

    Walks `CONCEPT_TAGS[concept]` in order and uses the *first* tag that has
    any reported units for this company -- it does not merge facts across
    multiple tags, since a company that reports under two different tags in
    different years is exactly the kind of tag-migration case that needs a
    single, traceable source per row (recorded in `tag`).

    Returns an empty (but correctly-schema'd) DataFrame and logs a warning
    if none of the chain's tags have any data, rather than silently
    returning nulls -- per SPEC.md Phase 1.
    """
    if concept not in CONCEPT_TAGS:
        raise KeyError(f"Unknown concept {concept!r}; add it to CONCEPT_TAGS first.")

    for taxonomy, tag in CONCEPT_TAGS[concept]:
        tag_facts = _facts_for_tag(facts, taxonomy, tag)
        if not tag_facts:
            continue
        units = tag_facts.get("units", {})
        rows: list[dict[str, Any]] = []
        for unit, entries in units.items():
            for entry in entries:
                rows.append(
                    {
                        "cik": cik,
                        "concept": concept,
                        "taxonomy": taxonomy,
                        "tag": tag,
                        "unit": unit,
                        "value": float(entry["val"]),
                        "fiscal_year": entry.get("fy"),
                        "fiscal_period": entry.get("fp"),
                        "period_start": _parse_date(entry.get("start")),
                        "period_end": _parse_date(entry.get("end")),
                        "filed": _parse_date(entry.get("filed")),
                        "form": entry.get("form"),
                        "accession_number": entry.get("accn"),
                        "frame": entry.get("frame"),
                    }
                )
        if rows:
            return pl.DataFrame(rows, schema=_SCHEMA)

    tried = [f"{taxonomy}:{tag}" for taxonomy, tag in CONCEPT_TAGS[concept]]
    logger.warning("concept_unmapped", cik=cik, concept=concept, tried_tags=tried)
    return pl.DataFrame(schema=_SCHEMA)


def extract_all_concepts(facts: dict[str, Any], *, cik: int) -> pl.DataFrame:
    """Extract every canonical concept in `CONCEPT_TAGS` for one company."""
    frames = [extract_concept(facts, concept, cik=cik) for concept in CONCEPT_TAGS]
    non_empty = [f for f in frames if not f.is_empty()]
    if not non_empty:
        return pl.DataFrame(schema=_SCHEMA)
    return pl.concat(non_empty, how="vertical")
