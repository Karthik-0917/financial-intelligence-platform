"""Offline SQLite evidence persistence and failure-boundary tests."""

import sqlite3

import pytest

from ai_service.citations.registry import Registry, validate_citations
from core.schemas import Synthesis


def test_application_overrides_source_supplied_identifier(tmp_path):
    registry = Registry(tmp_path / "evidence.sqlite")
    records = registry.register(
        "synthetic-request",
        [
            {
                "text": "Synthetic source text.",
                "evidence_id": "source-cannot-assign-this",
            }
        ],
    )

    identifier = next(iter(records))

    assert identifier == "EVIDENCE_synthetic-request_001"
    assert records[identifier]["evidence_id"] == identifier
    assert registry.get(identifier)["evidence_id"] == identifier


def test_invalid_later_record_does_not_publish_partial_batch(tmp_path):
    registry = Registry(tmp_path / "evidence.sqlite")

    with pytest.raises(ValueError, match="source text"):
        registry.register(
            "synthetic-request",
            [
                {"text": "Valid synthetic text."},
                {"text": ""},
            ],
        )

    assert registry.get("EVIDENCE_synthetic-request_001") is None


def test_existing_request_namespace_is_not_overwritten(tmp_path):
    registry = Registry(tmp_path / "evidence.sqlite")
    registry.register("synthetic-request", [{"text": "Original evidence."}])

    with pytest.raises(OSError, match="Evidence storage"):
        registry.register("synthetic-request", [{"text": "Replacement evidence."}])

    assert registry.get("EVIDENCE_synthetic-request_001")["text"] == (
        "Original evidence."
    )


def test_returned_record_is_detached_from_input(tmp_path):
    registry = Registry(tmp_path / "evidence.sqlite")
    original = {
        "text": "Synthetic source.",
        "metadata": {"value": "original"},
    }
    records = registry.register("synthetic-request", [original])
    original["metadata"]["value"] = "changed"

    identifier = next(iter(records))

    assert records[identifier]["metadata"]["value"] == "original"
    assert registry.get(identifier)["metadata"]["value"] == "original"


def test_nonfinite_metadata_is_not_persisted(tmp_path):
    registry = Registry(tmp_path / "evidence.sqlite")

    with pytest.raises(ValueError, match="finite JSON"):
        registry.register(
            "synthetic-request",
            [{"text": "Synthetic source.", "score": float("nan")}],
        )


def test_corrupt_database_error_is_sanitized(tmp_path):
    path = tmp_path / "evidence.sqlite"
    path.write_bytes(b"synthetic invalid database")

    with pytest.raises(OSError) as error:
        Registry(path)

    assert str(error.value) == "Evidence storage unavailable or inconsistent"
    assert str(path) not in str(error.value)


def test_corrupt_stored_record_is_rejected(tmp_path):
    path = tmp_path / "evidence.sqlite"
    registry = Registry(path)
    records = registry.register("synthetic-request", [{"text": "Evidence."}])
    identifier = next(iter(records))

    with sqlite3.connect(path) as database:
        database.execute(
            "UPDATE evidence SET body = ? WHERE id = ?",
            ('{"evidence_id": "different", "text": "Evidence."}', identifier),
        )

    with pytest.raises(OSError, match="identity or text"):
        registry.get(identifier)


def test_unknown_identifier_remains_not_found(tmp_path):
    assert Registry(tmp_path / "evidence.sqlite").get("unknown") is None


def test_blank_claim_text_is_rejected():
    synthesis = Synthesis(
        claims=[{"text": "   ", "citation_ids": ["synthetic-evidence"]}]
    )

    with pytest.raises(ValueError, match="no text"):
        validate_citations(
            synthesis,
            {"synthetic-evidence": {"text": "Synthetic source."}},
        )
