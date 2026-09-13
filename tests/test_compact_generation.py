"""Offline tests for compact context and rejected-provider trace reporting."""

import json
from copy import deepcopy
from types import SimpleNamespace

from ai_service.generation.context import (
    build_messages,
    prepare_context,
)
from ai_service.orchestrator import ResearchEngine
from core.schemas import Query, Synthesis


def evidence():
    return {
        "evidence_id": "EVIDENCE_fixture_001",
        "ticker": "AAPL",
        "fiscal_year": 2024,
        "text": "A synthetic source discussion.",
        "section": "Untrusted source heading",
        "chunk_id": "synthetic-chunk",
        "reranker_score": 0.8,
        "reconciliation": {
            "large_audit_payload": "audit detail " * 1000,
        },
        "source_url": "https://example.invalid/synthetic",
    }


def test_full_audit_payload_is_not_sent_to_provider(settings):
    record = evidence()
    original = deepcopy(record)
    registry = {record["evidence_id"]: record}

    context, selected, trace = prepare_context(
        settings,
        "Describe Apple's filing discussion in FY2024.",
        registry,
        [],
    )

    assert selected[record["evidence_id"]] == original
    assert record == original
    assert "reconciliation" not in context[0]["application_metadata"]
    assert "source_url" not in context[0]["application_metadata"]
    assert context[0]["untrusted_document_text"] == record["text"]
    assert context[0]["untrusted_document_metadata"]["section"] == (
        "Untrusted source heading"
    )
    assert trace["projection_policy"] == "compact-financial-context-v1"


def test_calculation_projection_preserves_values_and_roles():
    calculation = {
        "metric": "free_cash_flow",
        "value": "50",
        "unit": "USD",
        "formula": "operating cash flow - capital expenditure",
        "inputs": [
            {
                "fact_id": "synthetic-ocf",
                "ticker": "AAPL",
                "fiscal_year": 2024,
                "metric": "operating_cash_flow",
                "value": "60",
                "unit": "USD",
                "reconciliation": {"large": "audit " * 1000},
            },
            {
                "fact_id": "synthetic-capex",
                "ticker": "AAPL",
                "fiscal_year": 2024,
                "metric": "capex",
                "value": "10",
                "unit": "USD",
                "reconciliation": {"large": "audit " * 1000},
            },
        ],
    }
    original = deepcopy(calculation)
    messages = build_messages("Explain the supplied result.", [], [calculation])
    envelope = json.loads(messages[1]["content"])
    projected = envelope["deterministic_calculations"][0]

    assert projected["value"] == "50"
    assert [item["value"] for item in projected["inputs"]] == ["60", "10"]
    assert [item["metric"] for item in projected["inputs"]] == [
        "operating_cash_flow",
        "capex",
    ]
    assert all("reconciliation" not in item for item in projected["inputs"])
    assert calculation == original


def test_rejected_generation_does_not_claim_accepted_provider(
    settings,
    monkeypatch,
):
    import ai_service.orchestrator as module

    engine = ResearchEngine(settings)
    engine.store.data["corpus_version"] = "synthetic-version"
    engine.retriever = SimpleNamespace(
        manifest={"corpus_version": "synthetic-version"},
        retrieve=lambda *args: (
            [
                {
                    "ticker": "AMZN",
                    "fiscal_year": 2024,
                    "text": "Synthetic supply-chain risks.",
                }
            ],
            {},
        ),
    )

    monkeypatch.setattr(
        module,
        "synthesize",
        lambda *args: (
            Synthesis(
                claims=[
                    {
                        "text": "Supply-chain risks are discussed.",
                        "citation_ids": ["unknown-evidence"],
                    }
                ]
            ),
            {
                "provider": "groq",
                "model": "synthetic-model",
                "fallback_used": False,
                "fallback": None,
            },
        ),
    )

    result = engine.query(Query(question="What risks did Amazon identify in FY2024?"))

    assert result.abstained
    assert result.provider is None
    assert result.model is None
    assert result.key_findings == []
    assert result.trace["llm"]["response_provider"] == "groq"
    assert result.trace["llm"]["response_model"] == "synthetic-model"
    assert result.trace["llm"]["status"] == "response_rejected"
    assert result.trace["llm"]["provider"] is None
