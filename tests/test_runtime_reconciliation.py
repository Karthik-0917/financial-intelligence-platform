"""Runtime reconciliation boundary tests using synthetic local artifacts."""

from copy import deepcopy

import pytest

from ai_service.financial.resolver import FactError
from ai_service.financial.store import FinancialStore
from core.storage import read_json, write_json
from tests.financial_fixtures import publish_synthetic_financials


def root(settings):
    return settings.data_dir / "processed"


def revenue_record(records):
    return next(
        record
        for record in records
        if record["ticker"] == "AAPL"
        and record["fiscal_year"] == 2024
        and record["metric"] == "revenue"
    )


def revenue_document(documents):
    return next(document for document in documents if document["observations"])


def test_matched_reconciled_fact_is_consumable(settings):
    publish_synthetic_financials(settings)

    fact = FinancialStore(settings).fact("AAPL", 2024, "revenue")

    assert fact["value"] == "100"
    assert fact["reconciliation_status"] == "matched"


@pytest.mark.parametrize(
    "filename",
    ["inline_facts.json", "reconciliation.json"],
)
def test_missing_reconciliation_artifact_rejected(settings, filename):
    publish_synthetic_financials(settings)
    (root(settings) / filename).unlink()

    with pytest.raises(FactError):
        FinancialStore(settings).fact("AAPL", 2024, "revenue")


@pytest.mark.parametrize(
    "filename",
    ["inline_facts.json", "reconciliation.json"],
)
def test_cross_version_artifact_rejected(settings, filename):
    publish_synthetic_financials(settings)
    path = root(settings) / filename
    data = read_json(path)
    data["corpus_version"] = "different-generation"
    write_json(path, data)

    with pytest.raises(FactError):
        FinancialStore(settings).fact("AAPL", 2024, "revenue")


def test_pre_reconciliation_store_rejected(settings):
    _, data = publish_synthetic_financials(settings)
    data.pop("reconciliation_policy_version")
    write_json(root(settings) / "financials.json", data)

    with pytest.raises(FactError, match="policy version"):
        FinancialStore(settings).fact("AAPL", 2024, "revenue")


def test_unverified_fact_cannot_be_published_manually(settings):
    _, data = publish_synthetic_financials(settings)
    data["facts"][0]["reconciliation_status"] = "not_performed"
    write_json(root(settings) / "financials.json", data)

    with pytest.raises(FactError, match="matched reconciliation"):
        FinancialStore(settings).fact("AAPL", 2024, "revenue")


def test_altered_inline_value_invalidates_fact(settings):
    publish_synthetic_financials(settings)
    path = root(settings) / "inline_facts.json"
    data = read_json(path)
    document = revenue_document(data["documents"])
    document["observations"][0]["normalized_value"] = "101"
    write_json(path, data)

    with pytest.raises(FactError, match="does not validate"):
        FinancialStore(settings).fact("AAPL", 2024, "revenue")


def test_hidden_only_evidence_invalidates_fact(settings):
    publish_synthetic_financials(settings)
    path = root(settings) / "inline_facts.json"
    data = read_json(path)
    revenue_document(data["documents"])["observations"][0]["hidden"] = True
    write_json(path, data)

    with pytest.raises(FactError, match="does not validate"):
        FinancialStore(settings).fact("AAPL", 2024, "revenue")


def test_altered_embedded_reconciliation_rejected(settings):
    _, data = publish_synthetic_financials(settings)
    data["facts"][0]["reconciliation"]["reason"] = "Synthetic replacement"
    write_json(root(settings) / "financials.json", data)

    with pytest.raises(FactError, match="Embedded reconciliation"):
        FinancialStore(settings).fact("AAPL", 2024, "revenue")


def test_altered_reconciliation_candidate_rejected(settings):
    publish_synthetic_financials(settings)
    path = root(settings) / "reconciliation.json"
    data = read_json(path)
    revenue_record(data["records"])["candidate_fact"]["value"] = "999"
    write_json(path, data)

    with pytest.raises(FactError, match="reconciled candidate"):
        FinancialStore(settings).fact("AAPL", 2024, "revenue")


def test_duplicate_reconciliation_record_rejected(settings):
    publish_synthetic_financials(settings)
    path = root(settings) / "reconciliation.json"
    data = read_json(path)
    data["records"].append(deepcopy(revenue_record(data["records"])))
    write_json(path, data)

    with pytest.raises(FactError, match="duplicate metric scope"):
        FinancialStore(settings).fact("AAPL", 2024, "revenue")


def test_missing_inline_document_rejected(settings):
    publish_synthetic_financials(settings)
    path = root(settings) / "inline_facts.json"
    data = read_json(path)
    data["documents"].pop()
    write_json(path, data)

    with pytest.raises(FactError, match="cover the acquired corpus"):
        FinancialStore(settings).fact("AAPL", 2024, "revenue")


def test_analytics_excludes_fact_with_invalid_inline_evidence(settings):
    publish_synthetic_financials(settings)
    path = root(settings) / "inline_facts.json"
    data = read_json(path)
    document = revenue_document(data["documents"])
    document["observations"][0]["normalized_value"] = "101"
    write_json(path, data)

    result = FinancialStore(settings).analytics()
    apple = next(
        row
        for row in result["rows"]
        if row["ticker"] == "AAPL" and row["fiscal_year"] == 2024
    )

    assert "revenue" not in apple["values"]
    assert "revenue" in apple["unavailable_metrics"]
    assert result["status"] == "available_with_gaps"
