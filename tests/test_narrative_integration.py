"""Mocked orchestration regressions, not Groq or Windows runtime proof."""

from types import SimpleNamespace

import pytest

import ai_service.orchestrator as module
from ai_service.orchestrator import ResearchEngine
from core.schemas import Query, Synthesis
from tests.financial_fixtures import publish_synthetic_financials

QUESTION = (
    "What supply chain risks did Apple disclose in its 2024 10-K? "
    "Explain using filing evidence"
)


def setup_engine(settings, monkeypatch, text, unknown=False):
    engine = ResearchEngine(settings)
    engine.store.data["corpus_version"] = "synthetic-test-version"

    def retrieve(question, tickers, years):
        assert question == QUESTION
        assert tickers == ["AAPL"]
        assert years == [2024]
        return [
            {
                "ticker": "AAPL",
                "fiscal_year": 2024,
                "filing_type": "10-K",
                "text": "Synthetic test passage about supplier distress, not a real filing.",
                "source_url": "https://example.invalid/synthetic",
            }
        ], {}

    engine.retriever = SimpleNamespace(
        manifest={"corpus_version": "synthetic-test-version"},
        retrieve=retrieve,
    )

    def generate(settings, question, evidence, calculations):
        identifier = evidence[0]["application_metadata"]["evidence_id"]
        return Synthesis(
            claims=[
                {
                    "text": text,
                    "citation_ids": ["unknown" if unknown else identifier],
                }
            ]
        ), {
            "provider": "groq",
            "model": settings.groq_model,
            "fallback_used": False,
            "fallback": None,
        }

    monkeypatch.setattr(module, "synthesize", generate)
    return engine


def test_apple_reference_narrative_accepted_with_mocked_generation(
    settings, monkeypatch
):
    text = "Apple's 2024 10-K discusses supplier distress as a supply-chain risk."
    engine = setup_engine(settings, monkeypatch, text)
    result = engine.query(Query(question=QUESTION, tickers=[], years=[]))
    assert not result.abstained
    assert result.question_type == "RISK"
    assert result.answer == text
    assert len(result.citation_ids) == 1
    assert len(result.evidence) == 1
    assert result.citation_ids[0] == result.evidence[0]["evidence_id"]
    assert result.provider == "groq"
    assert result.model == settings.groq_model
    assert not result.fallback_used
    assert not result.grounded
    assert result.grounding_status == "citations_validated_semantics_unverified"
    assert engine.registry.get(result.citation_ids[0]) == result.evidence[0]


@pytest.mark.parametrize(
    "text",
    [
        "Revenue increased by 12%.",
        "Revenue increased by twelve percent.",
        "Assets doubled.",
        "Net income declined by half.",
        "Revenue grew three times.",
        "See HTTP://example.com.",
    ],
)
def test_rejected_prose_preserves_received_provider_trace(settings, monkeypatch, text):
    engine = setup_engine(settings, monkeypatch, text)
    result = engine.query(Query(question=QUESTION))
    assert result.abstained
    assert result.provider is None
    assert result.model is None
    assert result.citation_ids == []
    assert result.key_findings == []
    assert len(result.evidence) == 1
    assert result.trace["llm"]["response_provider"] == "groq"
    assert result.trace["llm"]["status"] == "response_rejected"
    assert (
        result.trace["llm"]["failure_category"]
        == "application_output_validation_failed"
    )


def test_unknown_citation_is_still_rejected(settings, monkeypatch):
    engine = setup_engine(
        settings, monkeypatch, "Suppliers may face distress.", unknown=True
    )
    result = engine.query(Query(question=QUESTION))
    assert result.abstained
    assert "citation" in result.abstention_reason.lower()


def test_authoritative_financial_output_does_not_enter_narrative_validator(
    settings, monkeypatch
):
    publish_synthetic_financials(settings)

    def unexpected(*args, **kwargs):
        raise AssertionError(
            "Structured output must not use narrative generation/validation"
        )

    monkeypatch.setattr(module, "synthesize", unexpected)
    monkeypatch.setattr(module, "validate_narrative", unexpected)
    result = ResearchEngine(settings).query(
        Query(question="What was Apple's revenue in FY2024?")
    )
    assert not result.abstained
    assert result.grounded
    assert result.facts[0]["value"] == "100"
    assert "$100.00" in result.answer
    assert result.provider is None
