"""Synthetic reconciliation tests. No external services or real values."""

from copy import deepcopy

import pytest

from ai_service.financial.reconciliation import reconcile
from ai_service.financial.resolver import FactError
from core.storage import sha256_bytes
from ingestion.pipeline import resolve_report
from tests.financial_fixtures import synthetic_manifest


def candidate():
    return {
        "document_id": "synthetic-document",
        "accession_number": "synthetic-accession",
        "ticker": "AAPL",
        "cik": "0000320193",
        "fiscal_year": 2024,
        "metric": "revenue",
        "taxonomy": "us-gaap",
        "concept": "Revenues",
        "unit": "USD",
        "kind": "duration",
        "value": "100",
        "period_start": "2024-01-01",
        "period_end": "2024-12-31",
        "content_sha256": sha256_bytes(b"synthetic filing"),
        "source": "https://example.invalid/synthetic-companyfacts",
        "source_url": "https://example.invalid/synthetic-filing",
        "original_fact": {"val": 100},
    }


def observation(value="100", hidden=False):
    return {
        "concept": "us-gaap:Revenues",
        "status": "parsed",
        "normalized_value": value,
        "unit": "USD",
        "hidden": hidden,
        "location": "html-element-10",
        "page": None,
        "context": {
            "cik": "0000320193",
            "kind": "duration",
            "period_start": "2024-01-01",
            "period_end": "2024-12-31",
            "dimensions": [],
            "has_segment_or_scenario": False,
        },
    }


def inline(*observations):
    return {
        "document_id": "synthetic-document",
        "content_sha256": sha256_bytes(b"synthetic filing"),
        "observations": list(observations),
    }


def test_exact_visible_match():
    result = reconcile(candidate(), inline(observation("100.0")))

    assert result["status"] == "matched"
    assert result["companyfacts_value"] == "100"
    assert result["filing_observations"][0]["normalized_value"] == "100.0"


def test_difference_preserves_both_values():
    result = reconcile(candidate(), inline(observation("101")))

    assert result["status"] == "conflict"
    assert result["companyfacts_value"] == "100"
    assert result["filing_observations"][0]["normalized_value"] == "101"


def test_conflicting_duplicate_observation_cannot_be_ignored():
    result = reconcile(
        candidate(),
        inline(observation("100"), observation("101")),
    )

    assert result["status"] == "conflict"
    assert len(result["filing_observations"]) == 2


def test_hidden_only_is_not_a_visible_match():
    result = reconcile(candidate(), inline(observation(hidden=True)))

    assert result["status"] == "not_verified"
    assert "hidden" in result["reason"]


def test_hidden_disagreement_blocks_visible_match():
    result = reconcile(
        candidate(),
        inline(observation("100"), observation("101", hidden=True)),
    )

    assert result["status"] == "conflict"


@pytest.mark.parametrize(
    "change",
    [
        {"cik": "0000789019"},
        {"period_end": "2023-12-31"},
        {"period_start": "2024-10-01"},
        {"dimensions": [{"dimension": "synthetic-segment"}]},
        {"has_segment_or_scenario": True},
    ],
)
def test_wrong_scope_cannot_validate_candidate(change):
    item = observation()
    item["context"].update(change)

    assert reconcile(candidate(), inline(item))["status"] == "not_verified"


def test_unresolved_same_concept_blocks_automatic_acceptance():
    unresolved = {
        "concept": "us-gaap:Revenues",
        "status": "unresolved",
        "raw_text": "unsupported numeric presentation",
    }
    result = reconcile(candidate(), inline(observation(), unresolved))

    assert result["status"] == "not_verified"
    assert len(result["blocking_observations"]) == 1


def test_checksum_mismatch_rejected():
    data = inline(observation())
    data["content_sha256"] = sha256_bytes(b"another document")

    with pytest.raises(FactError):
        reconcile(candidate(), data)


def test_reconciliation_does_not_mutate_inputs():
    fact = candidate()
    data = inline(observation())
    original_fact = deepcopy(fact)
    original_data = deepcopy(data)

    result = reconcile(fact, data)
    result["filing_observations"][0]["normalized_value"] = "999"

    assert fact == original_fact
    assert data == original_data


def test_pipeline_resolution_excludes_disputed_candidate():
    report = next(
        item
        for item in synthetic_manifest()
        if item["ticker"] == "AAPL" and item["fiscal_year"] == 2024
    )
    companyfacts = {
        "cik": 320193,
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "val": 100,
                                "start": "2024-01-01",
                                "end": "2024-12-31",
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "accn": report["accession_number"],
                            }
                        ]
                    }
                }
            }
        },
    }
    data = {
        "document_id": report["document_id"],
        "content_sha256": report["content_sha256"],
        "observations": [observation("101")],
    }

    accepted, issues, records, resolved_count = resolve_report(
        companyfacts,
        report,
        data,
    )

    assert accepted == []
    assert resolved_count == 1
    assert any(
        issue.get("metric") == "revenue" and issue.get("status") == "conflict"
        for issue in issues
    )

    revenue = next(record for record in records if record["metric"] == "revenue")

    assert revenue["candidate_fact"]["value"] == "100"
    assert revenue["filing_observations"][0]["normalized_value"] == "101"


def test_pipeline_resolution_accepts_only_matched_candidate():
    report = next(
        item
        for item in synthetic_manifest()
        if item["ticker"] == "AAPL" and item["fiscal_year"] == 2024
    )
    companyfacts = {
        "cik": 320193,
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "val": 100,
                                "start": "2024-01-01",
                                "end": "2024-12-31",
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "accn": report["accession_number"],
                            }
                        ]
                    }
                }
            }
        },
    }
    data = {
        "document_id": report["document_id"],
        "content_sha256": report["content_sha256"],
        "observations": [observation()],
    }

    accepted, issues, records, resolved_count = resolve_report(
        companyfacts,
        report,
        data,
    )

    assert resolved_count == 1
    assert len(accepted) == 1
    assert accepted[0]["metric"] == "revenue"
    assert accepted[0]["reconciliation_status"] == "matched"
    assert issues
    assert any(record["status"] == "matched" for record in records)
