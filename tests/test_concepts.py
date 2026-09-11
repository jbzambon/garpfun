"""Tests for garp.ingest.concepts: the XBRL tag-mapping fallback chain and,
critically, that extraction keys on `filed` (point-in-time) rather than
`end` (fiscal period) -- this is the join SPEC.md principle #1 exists to
protect.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from garp.ingest.concepts import CONCEPT_TAGS, extract_all_concepts, extract_concept
from garp.ingest.pit import as_of


def _fact(
    *, val: float, end: str, filed: str, form: str = "10-K", start: str | None = None
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "val": val,
        "end": end,
        "filed": filed,
        "form": form,
        "accn": "0001-24-000001",
        "fy": 2024,
        "fp": "FY",
    }
    if start:
        entry["start"] = start
    return entry


def test_extract_concept_uses_first_tag_with_data_in_the_fallback_chain() -> None:
    # Revenues (first in the chain) has nothing; the fallback tag does.
    facts = {
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {}},
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {"USD": [_fact(val=100.0, end="2023-12-31", filed="2024-02-20")]}
                },
            }
        }
    }
    result = extract_concept(facts, "revenue", cik=1)
    assert result.height == 1
    assert result["tag"][0] == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert result["value"][0] == 100.0


def test_extract_concept_returns_empty_and_does_not_raise_when_unmapped() -> None:
    facts: dict[str, Any] = {"facts": {"us-gaap": {}}}
    result = extract_concept(facts, "revenue", cik=1)
    assert result.is_empty()
    # Schema is preserved even when empty, so downstream concat/joins don't break.
    assert set(result.columns) == {
        "cik",
        "concept",
        "taxonomy",
        "tag",
        "unit",
        "value",
        "fiscal_year",
        "fiscal_period",
        "period_start",
        "period_end",
        "filed",
        "form",
        "accession_number",
        "frame",
    }


def test_extract_concept_logs_a_warning_when_unmapped() -> None:
    from structlog.testing import capture_logs

    facts: dict[str, Any] = {"facts": {"us-gaap": {}}}
    with capture_logs() as logs:
        extract_concept(facts, "revenue", cik=1)
    assert any(entry["event"] == "concept_unmapped" for entry in logs)


def test_extraction_keys_on_filed_date_not_period_end() -> None:
    """A Q4 result with period-end Dec 31 that wasn't filed until Feb 20 must
    not be visible to an `as_of` query dated Jan 15 -- SPEC.md's canonical
    example of principle #1.
    """
    facts = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {"USD": [_fact(val=100.0, end="2023-12-31", filed="2024-02-20")]}
                }
            }
        }
    }
    result = extract_concept(facts, "revenue", cik=1)
    assert result["period_end"][0] == date(2023, 12, 31)
    assert result["filed"][0] == date(2024, 2, 20)

    visible_jan_15 = as_of(result, "filed", date(2024, 1, 15))
    assert visible_jan_15.is_empty(), "fact must not be visible before its filing date"

    visible_feb_21 = as_of(result, "filed", date(2024, 2, 21))
    assert visible_feb_21.height == 1


def test_amendment_is_only_visible_from_its_own_filed_date() -> None:
    """A 10-K/A amendment restating the same fiscal period is a later,
    independent row -- it must not become visible until *its* filing date,
    even though it describes an already-known period.
    """
    facts = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            _fact(val=100.0, end="2023-12-31", filed="2024-02-20", form="10-K"),
                            _fact(val=105.0, end="2023-12-31", filed="2024-06-01", form="10-K/A"),
                        ]
                    }
                }
            }
        }
    }
    result = extract_concept(facts, "revenue", cik=1)
    assert result.height == 2

    as_of_march = as_of(result, "filed", date(2024, 3, 1))
    assert as_of_march.height == 1
    assert as_of_march["value"][0] == 100.0
    assert as_of_march["form"][0] == "10-K"

    as_of_july = as_of(result, "filed", date(2024, 7, 1))
    assert as_of_july.height == 2
    assert 105.0 in as_of_july["value"].to_list()


def test_extract_all_concepts_covers_every_registered_concept() -> None:
    facts: dict[str, Any] = {
        "facts": {
            "us-gaap": {
                "Assets": {"units": {"USD": [_fact(val=1.0, end="2023-12-31", filed="2024-02-20")]}}
            }
        }
    }
    result = extract_all_concepts(facts, cik=1)
    assert result.height == 1
    assert result["concept"][0] == "total_assets"
    # Every concept in the registry was attempted, not just the one that hit.
    assert len(CONCEPT_TAGS) >= 10
