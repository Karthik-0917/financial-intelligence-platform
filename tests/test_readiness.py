"""Local readiness tests with synthetic artifacts; no provider calls."""

from types import SimpleNamespace

from ai_service.financial.store import FinancialStore
from ai_service.readiness import build_status, provider_configuration
from core.storage import read_json, write_json
from tests.financial_fixtures import publish_synthetic_financials


def engine(settings):
    return SimpleNamespace(
        store=FinancialStore(settings),
        retriever=None,
    )


def test_empty_workspace_is_not_ready(settings):
    status = build_status(settings, engine(settings))

    assert status["validated_report_count"] == 0
    assert status["expected_report_count"] == 9
    assert status["financial_fact_count"] == 0
    assert status["financial_store_ready"] is False
    assert status["rag_ready"] is False
    assert status["last_ingestion"]["status"] == "not_run"


def test_key_presence_does_not_claim_authentication(settings):
    from pydantic import SecretStr

    settings.groq_api_key = SecretStr("synthetic-test-value-not-a-real-key")
    configuration = provider_configuration(settings)

    assert configuration["api_key_configured"] is True
    assert configuration["provider_authentication"] == "not_checked"
    assert configuration["provider_reachable"] is None
    assert configuration["structured_output_capability"] == "not_verified"
    assert "synthetic-test-value" not in str(configuration)


def test_invalid_provider_url_is_reported_without_request(settings):
    settings.groq_base_url = "http://example.invalid/insecure"

    configuration = provider_configuration(settings)

    assert configuration["provider_configured"] is False
    assert configuration["primary_configuration_complete"] is False
    assert configuration["provider_configuration_error"] == (
        "invalid_provider_configuration"
    )


def test_partial_financial_coverage_is_explicit(settings):
    publish_synthetic_financials(settings)

    status = build_status(settings, engine(settings))

    assert status["corpus_valid"] is True
    assert status["validated_report_count"] == 9
    assert status["financial_validated_fact_count"] == 1
    assert status["financial_store_ready"] is True
    assert status["financial_coverage_complete"] is False
    assert status["financial"]["status"] == "available_with_gaps"
    assert status["rag_ready"] is False


def test_invalid_fact_is_not_counted_as_validated(settings):
    _, data = publish_synthetic_financials(settings)
    data["facts"][0]["value"] = "999"
    write_json(settings.data_dir / "processed/financials.json", data)

    status = build_status(settings, engine(settings))

    assert status["financial_fact_count"] == 1
    assert status["financial_validated_fact_count"] == 0
    assert status["financial"]["invalid_fact_count"] == 1
    assert status["financial_store_ready"] is False


def test_corrupt_financial_file_is_reported(settings):
    path = settings.data_dir / "processed/financials.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{invalid", encoding="utf-8")

    status = build_status(settings, engine(settings))

    assert status["financial_store_ready"] is False
    assert status["financial_store_error"] == "financial_artifacts_unreadable"


def test_latest_failed_run_does_not_erase_published_corpus(settings):
    publish_synthetic_financials(settings)
    write_json(
        settings.data_dir / "processed/ingestion_run.json",
        {
            "run_id": "synthetic-failed-run",
            "status": "acquisition_incomplete",
            "publication": "not_started",
            "index": "not_requested",
            "slots": [
                {
                    "ticker": "AAPL",
                    "fiscal_year": 2024,
                    "status": "failed",
                    "stages": {"metadata": "failed"},
                    "error_category": "SyntheticTransportError",
                }
            ],
        },
    )

    status = build_status(settings, engine(settings))

    assert status["validated_report_count"] == 9
    assert status["last_ingestion"]["status"] == "acquisition_incomplete"
    assert status["last_ingestion"]["publication"] == "not_started"
    assert status["last_ingestion"]["matches_published_corpus"] is None


def test_index_file_presence_does_not_imply_readiness(settings):
    settings.index_dir.mkdir(parents=True, exist_ok=True)
    for name in ("dense.faiss", "chunks.json", "bm25.json"):
        (settings.index_dir / name).write_bytes(b"synthetic placeholder")

    write_json(
        settings.index_dir / "manifest.json",
        {"index_version": 1},
    )

    status = build_status(settings, engine(settings))

    assert status["index_artifacts_present"] is True
    assert status["index_ready"] is False
    assert status["retrieval_models_loaded"] is False


def test_loaded_store_snapshot_must_match_published_corpus(settings):
    publish_synthetic_financials(settings)
    loaded = engine(settings)
    path = settings.data_dir / "processed/corpus_manifest.json"
    manifest = read_json(path)
    manifest[0]["content_sha256"] = "a" * 64
    write_json(path, manifest)

    status = build_status(settings, loaded)

    assert status["store_snapshot_matches_published_corpus"] is False
    assert status["financial_store_ready"] is False
    assert status["rag_ready"] is False
