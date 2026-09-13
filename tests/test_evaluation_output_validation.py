"""Synthetic regression tests; no SEC, model, or network access."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from evaluation.metrics import (
    citation_id_validity,
    ranked_trace_ids,
    structured_correctness,
)


def calculation():
    return {
        "ticker": "AAPL",
        "fiscal_year": 2024,
        "metric": "growth",
        "value": "25",
        "unit": "percentage",
        "years": 1,
    }


def response(calculations=None):
    return SimpleNamespace(
        abstained=False,
        facts=[],
        calculations=([calculation()] if calculations is None else calculations),
        evidence=[{"evidence_id": "synthetic-evidence-1"}],
        citation_ids=["synthetic-evidence-1"],
        key_findings=[
            {
                "text": "Synthetic test finding.",
                "citation_ids": ["synthetic-evidence-1"],
            }
        ],
    )


def expected():
    return {"facts": [], "calculations": [calculation()]}


def test_decimal_equivalent_values_match():
    actual = calculation()
    actual["value"] = "25.000"

    assert structured_correctness(response([actual]), expected()) is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fiscal_year", True),
        ("fiscal_year", 2024.0),
        ("fiscal_year", "2024"),
        ("years", True),
        ("years", 1.0),
        ("years", 0),
        ("years", None),
        ("value", True),
        ("value", "NaN"),
        ("value", "Infinity"),
        ("ticker", ""),
        ("unit", " "),
    ],
)
def test_malformed_actual_is_incorrect(field, value):
    actual = calculation()
    actual[field] = value

    assert structured_correctness(response([actual]), expected()) is False


@pytest.mark.parametrize("actual", [None, "invalid", [], 17])
def test_non_object_actual_record_is_incorrect(actual):
    assert structured_correctness(response([actual]), expected()) is False


def test_missing_actual_scope_is_incorrect():
    actual = calculation()
    del actual["ticker"]

    assert structured_correctness(response([actual]), expected()) is False


def test_malformed_ground_truth_still_raises():
    reference = expected()
    reference["calculations"][0]["fiscal_year"] = 2024.0

    with pytest.raises(ValueError, match="integer year"):
        structured_correctness(response(), reference)


def test_duplicate_actual_is_not_subset_matched():
    actual = calculation()

    assert (
        structured_correctness(
            response([actual, deepcopy(actual)]),
            expected(),
        )
        is False
    )


def test_absent_reference_is_not_graded():
    assert structured_correctness(response(), {}) is None


def test_abstention_is_incorrect_for_structured_reference():
    actual = response()
    actual.abstained = True

    assert structured_correctness(actual, expected()) is False
    assert citation_id_validity(actual) is None


def test_valid_synthetic_citation_ids():
    assert citation_id_validity(response()) is True


@pytest.mark.parametrize(
    "identifiers",
    [[], [""], [" "], [None], [["nested"]], "synthetic-evidence-1"],
)
def test_malformed_answer_citations_are_invalid(identifiers):
    actual = response()
    actual.citation_ids = identifiers

    assert citation_id_validity(actual) is False


def test_malformed_finding_is_invalid():
    actual = response()
    actual.key_findings = ["not an object"]

    assert citation_id_validity(actual) is False


def test_unknown_finding_citation_is_invalid():
    actual = response()
    actual.key_findings[0]["citation_ids"] = ["unknown-synthetic-id"]

    assert citation_id_validity(actual) is False


def test_duplicate_evidence_ids_are_invalid():
    actual = response()
    actual.evidence.append(deepcopy(actual.evidence[0]))

    assert citation_id_validity(actual) is False


def test_rankings_are_interleaved_and_deduplicated():
    trace = {
        "reranked": [
            [{"chunk_id": "synthetic-a"}, {"chunk_id": "synthetic-c"}],
            [{"chunk_id": "synthetic-b"}, {"chunk_id": "synthetic-a"}],
        ]
    }

    assert ranked_trace_ids(trace) == [
        "synthetic-a",
        "synthetic-b",
        "synthetic-c",
    ]


def test_blank_ranked_identifier_is_rejected():
    with pytest.raises(ValueError, match="Malformed reranked trace entry"):
        ranked_trace_ids({"reranked": [[{"chunk_id": " "}]]})
