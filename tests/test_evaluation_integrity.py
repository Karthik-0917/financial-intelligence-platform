"""Offline evaluation regression tests using synthetic financial artifacts."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from ai_service.financial.store import FinancialStore
from ai_service.orchestrator import ResearchEngine
from core.schemas import Query
from evaluation.metrics import (
    CALCULATION_REFERENCE_FIELDS,
    FACT_REFERENCE_FIELDS,
    citation_id_validity,
    project_reference,
    ranked_trace_ids,
    structured_correctness,
)
from evaluation.prepare import prepare_references
from evaluation.run import evaluate
from tests.financial_fixtures import publish_synthetic_financials


def questions():
    return [
        {
            "id": "synthetic-fact",
            "question": "What was Apple's revenue in FY2024?",
            "question_type": "FACT",
            "expected_evidence": [],
        },
        {
            "id": "synthetic-unsupported",
            "question": "What was Tesla's revenue in FY2024?",
            "question_type": "UNSUPPORTED",
            "expected_evidence": [],
        },
        {
            "id": "synthetic-narrative",
            "question": "What risks did Amazon identify in FY2024?",
            "question_type": "RISK",
            "expected_evidence": [],
        },
    ]


def test_preparation_is_nonmutating_and_corpus_bound(settings):
    publish_synthetic_financials(settings)
    source = questions()
    before = deepcopy(source)
    store = FinancialStore(settings)

    prepared = prepare_references(source, store)

    assert source == before
    assert all(
        item["corpus_version"] == store.data["corpus_version"] for item in prepared
    )
    assert prepared[0]["annotation_status"] == "store_derived_reference"
    assert prepared[0]["expected_answer"]["facts"][0]["value"] == "100"
    assert prepared[2]["expected_answer"] is None
    assert prepared[2]["expected_evidence"] == []


def test_extra_actual_fact_is_not_accepted(settings):
    publish_synthetic_financials(settings)
    response = ResearchEngine(settings).query(
        Query(question="What was Apple's revenue in FY2024?")
    )
    expected = {
        "facts": [
            project_reference(fact, FACT_REFERENCE_FIELDS) for fact in response.facts
        ],
        "calculations": [
            project_reference(calculation, CALCULATION_REFERENCE_FIELDS)
            for calculation in response.calculations
        ],
    }

    assert structured_correctness(response, expected) is True

    response.facts.append(deepcopy(response.facts[0]))

    assert structured_correctness(response, expected) is False


def test_empty_expected_answer_is_ungraded():
    response = SimpleNamespace(abstained=False, facts=[], calculations=[])

    assert structured_correctness(response, {}) is None


def test_nonabstained_answer_without_citations_fails():
    response = SimpleNamespace(
        abstained=False,
        evidence=[],
        citation_ids=[],
        key_findings=[],
    )

    assert citation_id_validity(response) is False


def test_group_rankings_are_interleaved_without_reretrieval():
    trace = {
        "reranked": [
            [{"chunk_id": "a1"}, {"chunk_id": "a2"}],
            [{"chunk_id": "b1"}, {"chunk_id": "b2"}],
        ]
    }

    assert ranked_trace_ids(trace) == ["a1", "b1", "a2", "b2"]
    assert ranked_trace_ids({}) is None


def test_default_evaluation_skips_narrative(settings):
    publish_synthetic_financials(settings)
    store = FinancialStore(settings)
    dataset = prepare_references(questions(), store)

    result = evaluate(dataset, settings)

    assert result["status"] == "completed"
    assert result["record_status_counts"]["executed"] == 2
    assert result["record_status_counts"]["skipped_llm_disabled"] == 1
    assert result["metrics"]["structured_regression_correctness"] == 1
    assert result["metrics"]["unsupported_abstention_correctness"] == 1
    assert result["metrics"]["semantic_groundedness"] is None
    assert result["metrics"]["retrieval"] is None
    assert result["llm"]["received_responses"] == []
    assert result["llm"]["accepted_responses"] == []


def test_wrong_corpus_version_rejected(settings):
    publish_synthetic_financials(settings)
    dataset = prepare_references(questions(), FinancialStore(settings))
    dataset[0]["corpus_version"] = "different"

    with pytest.raises(ValueError, match="corpus versions disagree"):
        evaluate(dataset, settings)


def test_no_reviewed_retrieval_labels_does_not_invent_metrics(settings):
    publish_synthetic_financials(settings)
    dataset = prepare_references(questions(), FinancialStore(settings))

    result = evaluate(dataset, settings, retrieval_only=True)

    assert result["status"] == "not_yet_evaluated"
    assert result["metrics"]["retrieval"] is None
    assert result["denominators"]["retrieval_requests_attempted"] == 0
    assert result["record_status_counts"][
        "skipped_no_reviewed_retrieval_labels"
    ] == len(dataset)


def test_human_reviewed_wrong_corpus_is_not_silently_reused(settings):
    publish_synthetic_financials(settings)
    source = questions()
    source[0]["annotation_status"] = "human_reviewed"
    source[0]["corpus_version"] = "old-corpus"

    with pytest.raises(ValueError, match="different corpus"):
        prepare_references(source, FinancialStore(settings))
