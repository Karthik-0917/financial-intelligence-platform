"""Provider integration tests using synthetic evidence and mocked generation.

No test in this file calls Groq, Ollama, SEC, or a downloaded model.
"""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

import ai_service.generation.providers as providers
import ai_service.orchestrator as orchestrator
from ai_service.generation.providers import (
    GroqProvider,
    OllamaProvider,
    ProviderError,
)
from ai_service.orchestrator import ResearchEngine
from ai_service.retrieval.contracts import INDEX_POLICY
from core.schemas import Query, Synthesis
from core.storage import digest, sha256_bytes, write_json
from tests.financial_fixtures import (
    publish_synthetic_financials,
    synthetic_manifest,
)

FIXTURE_TEXT = "Supply disruptions may affect operations."
FIXTURE_LOCAL_MODEL = "fixture-local-model"


@pytest.fixture(autouse=True)
def block_live_groq_client(monkeypatch):
    def blocked_client(**kwargs):
        raise AssertionError("An unmocked Groq client was constructed")

    monkeypatch.setattr(providers, "Groq", blocked_client)


def fixture_chunk(
    chunk_id="fixture-high",
    text=FIXTURE_TEXT,
    score=0.9,
):
    return {
        "company": "Synthetic fixture entity",
        "ticker": "AMZN",
        "fiscal_year": 2024,
        "filing_type": "10-K",
        "filing_date": "2024-11-01",
        "period_end": "2024-09-28",
        "accession_number": "fixture-accession",
        "source_url": "https://example.invalid/fixture-document",
        "document_id": "fixture-document",
        "section": "Fixture risk section",
        "subsection": None,
        "page": None,
        "location": "fixture-block",
        "chunk_id": chunk_id,
        "text": text,
        "retrieval_score": 0.01,
        "reranker_score": score,
    }


def engine_with_fixture_retrieval(settings, chunks=None):
    records = chunks if chunks is not None else [fixture_chunk()]
    engine = ResearchEngine(settings)
    engine.store.data["corpus_version"] = "fixture-corpus"

    def retrieve(question, tickers, years):
        assert question
        assert tickers == ["AMZN"]
        assert years == [2024]
        return deepcopy(records), {"fixture": True, "groups": []}

    engine.retriever = SimpleNamespace(
        manifest={"corpus_version": "fixture-corpus"},
        retrieve=retrieve,
        encoder=object(),
        reranker=object(),
    )
    return engine


def successful_generation(self, question, evidence, calculations):
    evidence_id = evidence[0]["application_metadata"]["evidence_id"]
    return Synthesis(claims=[{"text": FIXTURE_TEXT, "citation_ids": [evidence_id]}])


def risk_question():
    return Query(question="What risks did Amazon identify in FY2024?")


def test_groq_received_and_accepted_provider_are_recorded(settings, monkeypatch):
    engine = engine_with_fixture_retrieval(settings)
    monkeypatch.setattr(GroqProvider, "generate", successful_generation)

    result = engine.query(risk_question())
    trace = result.trace["llm"]

    assert result.abstained is False
    assert result.provider == "groq"
    assert result.model == settings.groq_model
    assert trace["configured_provider"] == "groq"
    assert trace["response_provider"] == "groq"
    assert trace["response_model"] == settings.groq_model
    assert trace["provider"] == "groq"
    assert trace["model"] == settings.groq_model
    assert trace["status"] == "schema_and_citations_validated"
    assert result.trace["selected_evidence_ids"] == result.citation_ids
    assert "llm" in result.trace["latency_ms"]
    assert result.grounded is False
    assert result.grounding_status == "citations_validated_semantics_unverified"


def test_selected_and_cited_evidence_are_distinct(settings, monkeypatch):
    engine = engine_with_fixture_retrieval(
        settings,
        [
            fixture_chunk(),
            fixture_chunk("fixture-additional", "Additional source discussion.", 0.7),
        ],
    )
    monkeypatch.setattr(GroqProvider, "generate", successful_generation)

    result = engine.query(risk_question())

    assert not result.abstained
    assert len(result.trace["selected_evidence_ids"]) == 2
    assert len(result.evidence) == 2
    assert len(result.citation_ids) == 1
    assert result.trace["narrative_citation_ids"] == result.citation_ids
    assert set(result.citation_ids).issubset(result.trace["selected_evidence_ids"])


def test_ollama_fallback_is_recorded(settings, monkeypatch):
    settings.enable_llm_fallback = True
    settings.ollama_model = FIXTURE_LOCAL_MODEL
    engine = engine_with_fixture_retrieval(settings)

    def hosted_failure(self, question, evidence, calculations):
        raise ProviderError(
            "timeout",
            provider="groq",
            model=self.model,
            attempts=3,
        )

    monkeypatch.setattr(GroqProvider, "generate", hosted_failure)
    monkeypatch.setattr(OllamaProvider, "generate", successful_generation)

    result = engine.query(risk_question())

    assert not result.abstained
    assert result.provider == "ollama"
    assert result.model == FIXTURE_LOCAL_MODEL
    assert result.fallback_used
    assert result.fallback["original_provider"] == "groq"
    assert result.fallback["failure_category"] == "timeout"
    assert result.trace["llm"]["response_provider"] == "ollama"
    assert result.trace["llm"]["provider"] == "ollama"
    assert result.trace["llm"]["fallback"] == result.fallback


def test_failed_attempt_is_not_a_provider_response(settings, monkeypatch):
    engine = engine_with_fixture_retrieval(settings)

    def hosted_failure(self, question, evidence, calculations):
        raise ProviderError(
            "authentication",
            provider="groq",
            model=self.model,
            attempts=1,
        )

    monkeypatch.setattr(GroqProvider, "generate", hosted_failure)
    result = engine.query(risk_question())

    assert result.abstained
    assert result.provider is None
    assert result.model is None
    assert result.abstention_reason == "authentication"
    assert result.trace["llm"]["response_provider"] is None
    assert result.trace["llm"]["attempted_provider"] == "groq"
    assert result.trace["llm"]["failure_category"] == "authentication"
    assert result.trace["llm"]["attempts"] == 1
    assert result.trace["llm"]["status"] == "failed"


def test_both_failed_providers_remain_visible(settings, monkeypatch):
    settings.enable_llm_fallback = True
    settings.ollama_model = FIXTURE_LOCAL_MODEL
    engine = engine_with_fixture_retrieval(settings)

    def hosted_failure(self, question, evidence, calculations):
        raise ProviderError("rate_limit", provider="groq", model=self.model, attempts=3)

    def local_failure(self, question, evidence, calculations):
        raise ProviderError(
            "provider_unavailable", provider="ollama", model=self.model, attempts=2
        )

    monkeypatch.setattr(GroqProvider, "generate", hosted_failure)
    monkeypatch.setattr(OllamaProvider, "generate", local_failure)

    result = engine.query(risk_question())

    assert result.abstained
    assert result.provider is None
    assert result.model is None
    assert result.fallback_used
    assert result.abstention_reason == "primary_and_fallback_failed"
    assert result.fallback["failure_category"] == "rate_limit"
    assert result.fallback["fallback_failure_category"] == "provider_unavailable"
    assert result.trace["llm"]["attempted_provider"] == "ollama"
    assert result.trace["llm"]["response_provider"] is None


def test_unknown_citation_rejects_received_response(settings, monkeypatch):
    engine = engine_with_fixture_retrieval(settings)

    def unknown_citation(self, question, evidence, calculations):
        return Synthesis(
            claims=[{"text": FIXTURE_TEXT, "citation_ids": ["UNKNOWN_FIXTURE_ID"]}]
        )

    monkeypatch.setattr(GroqProvider, "generate", unknown_citation)
    result = engine.query(risk_question())

    assert result.abstained
    assert "citation" in result.abstention_reason.lower()
    assert result.provider is None
    assert result.model is None
    assert result.trace["llm"]["response_provider"] == "groq"
    assert result.trace["llm"]["provider"] is None
    assert result.trace["llm"]["status"] == "response_rejected"
    assert result.trace["validation"] == "abstained"


def test_removed_evidence_cannot_be_cited(settings, monkeypatch):
    high = fixture_chunk()
    low = fixture_chunk(
        "fixture-low",
        "Optional lower ranked supporting disclosure.",
        0.1,
    )
    settings.context_char_budget = len(high["text"])
    engine = engine_with_fixture_retrieval(settings, [high, low])
    registered = {}
    original_register = engine.registry.register

    def capture_registry(request_id, records):
        registry = original_register(request_id, records)
        registered.update(registry)
        return registry

    monkeypatch.setattr(engine.registry, "register", capture_registry)

    def cite_removed(self, question, evidence, calculations):
        supplied_ids = {
            item["application_metadata"]["evidence_id"] for item in evidence
        }
        removed_id = next(
            identifier
            for identifier, record in registered.items()
            if record["chunk_id"] == "fixture-low"
        )
        assert removed_id not in supplied_ids
        return Synthesis(claims=[{"text": FIXTURE_TEXT, "citation_ids": [removed_id]}])

    monkeypatch.setattr(GroqProvider, "generate", cite_removed)
    result = engine.query(risk_question())
    removed = result.trace["context"]["removed_evidence_ids"]

    assert result.abstained
    assert len(removed) == 1
    assert engine.registry.get(removed[0]) is not None
    assert removed[0] not in {record["evidence_id"] for record in result.evidence}
    assert result.trace["llm"]["status"] == "response_rejected"


def test_numeric_model_claim_is_rejected(settings, monkeypatch):
    engine = engine_with_fixture_retrieval(settings)

    def numeric_claim(self, question, evidence, calculations):
        identifier = evidence[0]["application_metadata"]["evidence_id"]
        return Synthesis(
            claims=[
                {
                    "text": "Revenue increased by 12%.",
                    "citation_ids": [identifier],
                }
            ]
        )

    monkeypatch.setattr(GroqProvider, "generate", numeric_claim)
    result = engine.query(risk_question())

    assert result.abstained
    assert "numeric claims" in result.abstention_reason
    assert result.provider is None
    assert result.trace["llm"]["status"] == "response_rejected"


def test_structured_query_does_not_invoke_generation(settings, monkeypatch):
    publish_synthetic_financials(settings)

    def unexpected_generation(*args, **kwargs):
        raise AssertionError("Structured research must not call an LLM")

    monkeypatch.setattr(orchestrator, "synthesize", unexpected_generation)
    result = ResearchEngine(settings).query(
        Query(question="What was Apple's revenue in FY2024?")
    )

    assert not result.abstained
    assert result.grounded
    assert result.provider is None
    assert result.trace["llm"]["status"] == "not_invoked"
    assert "llm" not in result.trace["latency_ms"]
    assert result.trace["financial_validation"]["status"] == "validated"


@pytest.mark.parametrize(
    "question",
    [
        "What was Apple's revenue in FY2030?",
        "What was Tesla's revenue in FY2024?",
        "What will Apple's stock price be in 2027?",
    ],
)
def test_unsupported_questions_do_not_invoke_provider(settings, monkeypatch, question):
    def unexpected_generation(*args, **kwargs):
        raise AssertionError("Unsupported questions must not call an LLM")

    monkeypatch.setattr(orchestrator, "synthesize", unexpected_generation)
    result = ResearchEngine(settings).query(Query(question=question))

    assert result.abstained
    assert result.provider is None
    assert result.trace["llm"]["status"] == "not_invoked"


def test_health_and_status_do_not_call_provider_or_expose_key(settings, monkeypatch):
    import ai_service.main as module

    fixture_key = "fixture-status-key-not-a-real-credential"
    settings.groq_api_key = SecretStr(fixture_key)
    monkeypatch.setattr(module, "settings", settings)

    with TestClient(module.app) as client:
        health_response = client.get("/internal/health")
        status_response = client.get("/internal/status")

    for response in (health_response, status_response):
        assert response.status_code == 200
        payload = response.json()
        assert payload["provider"] == "groq"
        assert payload["model"] == settings.groq_model
        assert payload["api_key_configured"] is True
        assert payload["provider_reachable"] is None
        assert payload["provider_reachability"] == "not_checked"
        assert payload["provider_authentication"] == "not_checked"
        assert fixture_key not in response.text

    status = status_response.json()
    assert status["index_ready"] is False
    assert status["rag_ready"] is False
    assert status["financial_store_ready"] is False
    assert "GROQ_API_KEY" not in status_response.text


def test_ollama_status_does_not_claim_reachability(settings, monkeypatch):
    import ai_service.main as module

    settings.llm_provider = "ollama"
    settings.ollama_model = FIXTURE_LOCAL_MODEL
    monkeypatch.setattr(module, "settings", settings)

    with TestClient(module.app) as client:
        response = client.get("/internal/status")

    payload = response.json()
    assert response.status_code == 200
    assert payload["provider"] == "ollama"
    assert payload["model"] == FIXTURE_LOCAL_MODEL
    assert payload["api_key_configured"] is None
    assert payload["primary_credentials_configured"] is True
    assert payload["provider_reachable"] is None


def test_compatible_metadata_and_file_presence_do_not_imply_loaded_rag(
    settings, monkeypatch
):
    import ai_service.main as module

    sources = synthetic_manifest()
    marker = b"synthetic-presence-marker-not-a-faiss-index"
    manifest = {
        **INDEX_POLICY,
        "embedding_model": settings.embedding_model,
        "reranker_model": settings.reranker_model,
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "corpus_version": digest(sources),
        "sources": sources,
        "document_count": len(sources),
        "chunk_count": len(sources),
        "embedding_dimension": 2,
        "chunks_sha256": digest([]),
        "bm25_sha256": digest({}),
        "faiss_sha256": sha256_bytes(marker),
    }

    write_json(
        settings.data_dir / "processed/corpus_manifest.json",
        sources,
    )
    write_json(settings.index_dir / "manifest.json", manifest)
    write_json(settings.index_dir / "chunks.json", [])
    write_json(settings.index_dir / "bm25.json", {})
    (settings.index_dir / "dense.faiss").write_bytes(marker)
    monkeypatch.setattr(module, "settings", settings)

    with TestClient(module.app) as client:
        response = client.get("/internal/status")

    payload = response.json()
    assert response.status_code == 200
    assert payload["index_present"] is True
    assert payload["configuration_compatible"] is True
    assert payload["index_artifacts_present"] is True
    assert payload["index_loaded"] is False
    assert payload["index_ready"] is False
    assert payload["index_integrity"] == "not_loaded"
    assert payload["retrieval_models_loaded"] is False
    assert payload["rag_ready"] is False


def test_legacy_manifest_is_not_configuration_compatible(settings, monkeypatch):
    import ai_service.main as module

    write_json(
        settings.index_dir / "manifest.json",
        {
            "embedding_model": settings.embedding_model,
            "reranker_model": settings.reranker_model,
            "chunk_size": settings.chunk_size,
            "chunk_overlap": settings.chunk_overlap,
        },
    )
    monkeypatch.setattr(module, "settings", settings)

    with TestClient(module.app) as client:
        response = client.get("/internal/status")

    assert response.json()["configuration_compatible"] is False
    assert response.json()["index_ready"] is False


def test_corrupt_manifest_produces_safe_status(settings, monkeypatch):
    import ai_service.main as module

    settings.index_dir.mkdir(parents=True, exist_ok=True)
    (settings.index_dir / "manifest.json").write_text(
        "not valid JSON",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "settings", settings)

    with TestClient(module.app) as client:
        response = client.get("/internal/status")

    payload = response.json()
    assert response.status_code == 200
    assert payload["index_error"] == "index_manifest_unreadable"
    assert payload["index_ready"] is False
    assert payload["rag_ready"] is False


def test_public_status_preserves_internal_metadata(settings, monkeypatch):
    import ai_service.main as internal_module
    import backend.app.main as backend_module

    monkeypatch.setattr(internal_module, "settings", settings)

    with TestClient(internal_module.app) as client:
        expected = client.get("/internal/status").json()

    async def fake_internal(path, body=None):
        assert path == "/internal/status"
        assert body is None
        return expected

    monkeypatch.setattr(backend_module, "settings", settings)
    monkeypatch.setattr(backend_module, "internal", fake_internal)

    with TestClient(backend_module.app) as client:
        response = client.get("/api/system/status")

    assert response.status_code == 200
    assert response.json() == expected
    assert response.json()["provider_reachable"] is None
