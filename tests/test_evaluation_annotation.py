"""Synthetic annotation workflow tests; no real retrieval or human review."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from core.storage import digest
from evaluation.annotate import (
    REVIEW_SCOPE,
    apply_annotations,
    build_packet,
)


def dataset():
    return [
        {
            "id": "synthetic-risk",
            "question": "What risks did Apple identify in FY2024?",
            "question_type": "RISK",
            "corpus_version": "synthetic-corpus",
            "expected_answer": None,
            "expected_evidence": [],
        }
    ]


def chunk(identifier, text, ticker="AAPL"):
    return {
        "chunk_id": identifier,
        "document_id": f"synthetic-{ticker}",
        "ticker": ticker,
        "fiscal_year": 2024,
        "section": "Synthetic risk section",
        "subsection": None,
        "location": f"synthetic-location-{identifier}",
        "source_url": "https://example.invalid/synthetic-source",
        "text": text,
    }


def retriever():
    chunks = [
        chunk("synthetic-a", "Synthetic supply risk."),
        chunk("synthetic-b", "Synthetic unrelated discussion."),
        chunk("synthetic-c", "Synthetic additional relevant passage."),
        chunk("synthetic-other-company", "Different entity.", "MSFT"),
    ]
    return SimpleNamespace(
        manifest={
            "corpus_version": "synthetic-corpus",
            "index_version": 2,
        },
        chunks=chunks,
        retrieve=lambda *args: (
            chunks[:2],
            {
                "reranked": [
                    [
                        {"chunk_id": "synthetic-a"},
                        {"chunk_id": "synthetic-b"},
                    ]
                ]
            },
        ),
    )


def reviewed_packet():
    source = dataset()
    index = retriever()
    packet = build_packet(source, index, "synthetic-corpus")
    question = packet["questions"][0]
    question["review_complete"] = True
    question["review_scope"] = REVIEW_SCOPE
    question["review_reference"] = "synthetic-unit-test-review"
    question["candidates"][0]["relevant"] = True
    question["candidates"][1]["relevant"] = False
    return source, index, packet


def test_export_uses_actual_supplied_chunk_ids_without_labels():
    source = dataset()
    index = retriever()
    packet = build_packet(source, index, "synthetic-corpus")
    question = packet["questions"][0]

    assert packet["index_signature"] == digest(index.manifest)
    assert packet["dataset_signature"] == digest(source)
    assert question["scope_chunk_count"] == 3
    assert [item["chunk_id"] for item in question["candidates"]] == [
        "synthetic-a",
        "synthetic-b",
    ]
    assert all(item["relevant"] is None for item in question["candidates"])
    assert question["review_complete"] is False


def test_apply_preserves_source_and_numeric_reference_fields():
    source, index, packet = reviewed_packet()
    original = deepcopy(source)
    packet["questions"][0]["additional_relevant_ids"] = ["synthetic-c"]

    output, count = apply_annotations(source, packet, index)

    assert source == original
    assert count == 1
    assert output[0]["expected_answer"] is None
    assert output[0]["expected_evidence"] == ["synthetic-a", "synthetic-c"]
    assert output[0]["retrieval_annotation_status"] == "reviewed"
    assert output[0]["index_signature"] == digest(index.manifest)


def test_changed_index_rejected():
    source, index, packet = reviewed_packet()
    index.manifest["index_version"] = 999

    with pytest.raises(ValueError, match="different index"):
        apply_annotations(source, packet, index)


def test_changed_dataset_rejected():
    source, index, packet = reviewed_packet()
    source[0]["question"] = "What risks did Apple identify in FY2023?"

    with pytest.raises(ValueError, match="different dataset"):
        apply_annotations(source, packet, index)


def test_cross_company_additional_id_rejected():
    source, index, packet = reviewed_packet()
    packet["questions"][0]["additional_relevant_ids"] = ["synthetic-other-company"]

    with pytest.raises(ValueError, match="cross-scope"):
        apply_annotations(source, packet, index)


def test_modified_excerpt_rejected():
    source, index, packet = reviewed_packet()
    packet["questions"][0]["candidates"][0]["text"] = "Changed source wording."

    with pytest.raises(ValueError, match="changed during review"):
        apply_annotations(source, packet, index)


def test_missing_relevance_judgment_rejected():
    source, index, packet = reviewed_packet()
    packet["questions"][0]["candidates"][1]["relevant"] = None

    with pytest.raises(ValueError, match="boolean relevance"):
        apply_annotations(source, packet, index)


def test_no_relevant_chunks_does_not_create_positive_gold():
    source, index, packet = reviewed_packet()

    for candidate in packet["questions"][0]["candidates"]:
        candidate["relevant"] = False

    output, count = apply_annotations(source, packet, index)

    assert count == 1
    assert output[0]["expected_evidence"] == []
    assert output[0]["retrieval_annotation_status"] == ("reviewed_no_relevant_chunks")
    assert output[0]["expected_answer"] is None


def test_incomplete_reviews_are_not_applied():
    source, index, packet = reviewed_packet()
    packet["questions"][0]["review_complete"] = False

    output, count = apply_annotations(source, packet, index)

    assert count == 0
    assert output == source


def test_full_scope_declaration_is_required():
    source, index, packet = reviewed_packet()
    packet["questions"][0]["review_scope"] = "only_top_two_results"

    with pytest.raises(ValueError, match="requested company/year scope"):
        apply_annotations(source, packet, index)
