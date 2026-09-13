from copy import deepcopy

import pytest

from ai_service.financial.resolver import FactError
from ai_service.financial.store import FinancialStore
from core.storage import digest, write_json
from ingestion.validate import validate_manifest
from tests.financial_fixtures import (
    publish_synthetic_financials,
    synthetic_manifest,
)


def test_complete_synthetic_manifest_is_valid():
    validate_manifest(synthetic_manifest())


@pytest.mark.parametrize(
    "change",
    [
        {"cik": "0000789019"},
        {"company": "Unrelated company"},
        {"source_url": "https://example.invalid/filing"},
        {"content_sha256": "not-a-hash"},
        {"pipeline_version": "legacy"},
        {"status": "pending"},
        {"filing_type": "10-K/A"},
        {"primary_document": "../unsafe.htm"},
        {"block_count": 0},
    ],
)
def test_invalid_manifest_provenance_rejected(change):
    manifest = synthetic_manifest()
    manifest[0].update(change)

    with pytest.raises(ValueError):
        validate_manifest(manifest)


def test_manifest_identity_mismatch_rejected():
    manifest = synthetic_manifest()
    manifest[0]["identity"]["amendment"] = True

    with pytest.raises(ValueError):
        validate_manifest(manifest)


def test_versioned_fact_is_consumable(settings):
    publish_synthetic_financials(settings)

    result = FinancialStore(settings).fact("AAPL", 2024, "revenue")

    assert result["value"] == "100"


def test_unversioned_populated_store_rejected(settings):
    _, data = publish_synthetic_financials(settings)
    del data["corpus_version"]
    write_json(settings.data_dir / "processed/financials.json", data)

    with pytest.raises(FactError, match="provenance"):
        FinancialStore(settings).fact("AAPL", 2024, "revenue")


def test_manifest_version_mismatch_rejected(settings):
    _, data = publish_synthetic_financials(settings)
    data["corpus_version"] = "different"
    write_json(settings.data_dir / "processed/financials.json", data)

    with pytest.raises(FactError, match="disagree"):
        FinancialStore(settings).fact("AAPL", 2024, "revenue")


@pytest.mark.parametrize(
    "change",
    [
        {"value": "999"},
        {"value": "NaN"},
        {"original_value": "999"},
        {"unit": "shares"},
        {"cik": "0000789019"},
        {"accession_number": "0000000000-24-999999"},
        {"source_url": "https://example.invalid/filing"},
        {"period_start": "2024-10-01"},
        {"reconciliation_status": "conflict"},
    ],
)
def test_tampered_or_disputed_fact_rejected(settings, change):
    _, data = publish_synthetic_financials(settings)
    data["facts"][0].update(change)
    write_json(settings.data_dir / "processed/financials.json", data)

    with pytest.raises(FactError):
        FinancialStore(settings).fact("AAPL", 2024, "revenue")


def test_duplicate_fact_rejected(settings):
    _, data = publish_synthetic_financials(settings)
    data["facts"].append(deepcopy(data["facts"][0]))
    write_json(settings.data_dir / "processed/financials.json", data)

    with pytest.raises(FactError, match="ambiguous"):
        FinancialStore(settings).fact("AAPL", 2024, "revenue")


def test_explicit_source_issue_blocks_fact(settings):
    _, data = publish_synthetic_financials(settings)
    data["issues"].append(
        {
            "ticker": "AAPL",
            "fiscal_year": 2024,
            "metric": "revenue",
            "reason": "Synthetic unresolved source discrepancy",
        }
    )
    write_json(settings.data_dir / "processed/financials.json", data)

    with pytest.raises(FactError, match="Unresolved source issue"):
        FinancialStore(settings).fact("AAPL", 2024, "revenue")


def test_cross_company_request_cannot_reuse_fact(settings):
    publish_synthetic_financials(settings)

    with pytest.raises(FactError, match="Missing or ambiguous"):
        FinancialStore(settings).fact("MSFT", 2024, "revenue")


def test_empty_workspace_is_not_zero_financial_data(settings):
    result = FinancialStore(settings).analytics()

    assert result["status"] == "not_initialized"
    assert result["rows"] == []
    assert result["corpus_version"] is None


def test_analytics_reports_missing_metrics(settings):
    publish_synthetic_financials(settings)

    result = FinancialStore(settings).analytics()
    apple = next(
        row
        for row in result["rows"]
        if row["ticker"] == "AAPL" and row["fiscal_year"] == 2024
    )

    assert apple["values"]["revenue"] == "100"
    assert "operating_income" in apple["unavailable_metrics"]
    assert "operating_margin" not in apple["values"]
    assert result["status"] == "available_with_gaps"


def test_corrupt_store_does_not_crash_construction(settings):
    path = settings.data_dir / "processed/financials.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{invalid", encoding="utf-8")

    store = FinancialStore(settings)

    with pytest.raises(FactError, match="unreadable"):
        store.analytics()


def test_rehashed_invalid_manifest_still_rejected(settings):
    manifest, data = publish_synthetic_financials(settings)
    manifest[0]["cik"] = "0000789019"
    data["corpus_version"] = digest(manifest)
    write_json(settings.data_dir / "processed/corpus_manifest.json", manifest)
    write_json(settings.data_dir / "processed/financials.json", data)

    with pytest.raises(FactError):
        FinancialStore(settings).fact("AAPL", 2024, "revenue")
