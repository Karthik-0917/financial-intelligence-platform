"""Offline submission selection and audit tests using synthetic fixtures."""

from types import SimpleNamespace

import pytest

from core.storage import read_json, write_json
from ingestion.pipeline import candidate_filings, rows, run


def filing(**overrides):
    return {
        "accessionNumber": "0000000000-25-000001",
        "filingDate": "2025-01-15",
        "reportDate": "2024-12-31",
        "form": "10-K",
        "primaryDocument": "fixture-annual.htm",
        **overrides,
    }


def test_report_year_not_filing_year_selects_candidate():
    selected = candidate_filings([filing()], 2024)

    assert len(selected) == 1
    assert selected[0]["filingDate"].startswith("2025")


def test_amendments_are_excluded():
    selected = candidate_filings(
        [
            filing(form="10-K/A"),
            filing(
                accessionNumber="0000000000-25-000002",
                form="10-K",
            ),
        ],
        2024,
    )

    assert len(selected) == 1
    assert selected[0]["form"] == "10-K"


def test_identical_submission_duplicates_are_collapsed():
    assert len(candidate_filings([filing(), filing()], 2024)) == 1


def test_conflicting_duplicate_accession_rejected():
    with pytest.raises(ValueError):
        candidate_filings(
            [
                filing(),
                filing(primaryDocument="different.htm"),
            ],
            2024,
        )


def test_different_original_accessions_remain_candidates():
    selected = candidate_filings(
        [
            filing(),
            filing(accessionNumber="0000000000-25-000002"),
        ],
        2024,
    )

    assert len(selected) == 2


def test_wrong_report_year_is_not_selected():
    assert candidate_filings([filing()], 2023) == []


def test_column_rows_preserve_alignment():
    source = filing()
    table = {key: [value] for key, value in source.items()}

    assert rows(table) == [source]


def test_unequal_column_lengths_rejected():
    source = filing()
    table = {key: [value] for key, value in source.items()}
    table["reportDate"] = []

    with pytest.raises(ValueError):
        rows(table)


def test_missing_required_submission_column_rejected():
    table = {key: [value] for key, value in filing().items() if key != "reportDate"}

    with pytest.raises(ValueError):
        rows(table)


def test_failed_acquisition_preserves_published_manifest(tmp_path, monkeypatch):
    settings = SimpleNamespace(data_dir=tmp_path)
    processed = tmp_path / "processed"
    published = [{"synthetic": "previous published artifact"}]
    write_json(processed / "corpus_manifest.json", published)

    class FailingClient:
        def __init__(self, settings):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            pass

        def get(self, url, *, refresh=False):
            raise RuntimeError("Synthetic transport failure")

    monkeypatch.setattr("ingestion.pipeline.SECClient", FailingClient)

    with pytest.raises(RuntimeError, match="Corpus acquisition incomplete"):
        run(settings, build_index=False)

    assert read_json(processed / "corpus_manifest.json") == published

    audit = read_json(processed / "ingestion_run.json")

    assert audit["status"] == "acquisition_incomplete"
    assert audit["publication"] == "not_started"
    assert audit["index"] == "not_requested"
    assert len(audit["slots"]) == 9
    assert all(slot["status"] == "failed" for slot in audit["slots"])
    assert audit["finished_at"] is not None
    assert not (processed / "corpus.json").exists()
    assert not (processed / "financials.json").exists()
