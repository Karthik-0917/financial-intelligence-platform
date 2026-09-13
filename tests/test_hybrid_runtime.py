"""Real FAISS/BM25 artifacts with synthetic text and mocked model outputs."""

import sys
from types import SimpleNamespace

import faiss
import numpy as np
import pytest

from ai_service.retrieval.contracts import INDEX_POLICY
from ai_service.retrieval.hybrid import HybridRetriever, persist_bm25
from core.storage import digest, read_json, sha256_bytes, write_json
from ingestion.chunk import chunk_blocks
from tests.financial_fixtures import synthetic_manifest


class FakeTokenizer:
    def encode(self, text, **kwargs):
        return text.split()

    def decode(self, tokens, **kwargs):
        return " ".join(tokens)

    def num_special_tokens_to_add(self, pair=False):
        return 3 if pair else 2


class FakeReranker:
    tokenizer = FakeTokenizer()

    def predict(self, pairs, **kwargs):
        assert all(question and text for question, text in pairs)
        return np.array([2.0] * len(pairs))


@pytest.fixture
def knowledge_base(settings):
    root = settings.index_dir
    sources = synthetic_manifest()
    chunks = []

    for source in sources:
        # Same wording across companies must not erase company coverage.
        blocks = [
            {
                "text": "Shared supply chain risk",
                "section": f"Synthetic section {number}",
                "subsection": None,
                "location": f"synthetic-block-{number}",
                "page": None,
                "table": False,
            }
            for number in range(3)
        ]
        chunks.extend(
            chunk_blocks(
                blocks,
                source,
                FakeTokenizer(),
                settings.chunk_size,
                settings.chunk_overlap,
            )
        )

    lexical_data = persist_bm25(chunks)
    write_json(root / "chunks.json", chunks)
    write_json(root / "bm25.json", lexical_data)
    write_json(
        settings.data_dir / "processed/corpus_manifest.json",
        sources,
    )

    index = faiss.IndexFlatIP(2)
    index.add(np.array([[1, 0]] * len(chunks), dtype="float32"))
    faiss.write_index(index, str(root / "dense.faiss"))

    manifest = {
        **INDEX_POLICY,
        **{
            field: getattr(settings, field)
            for field in (
                "embedding_model",
                "reranker_model",
                "chunk_size",
                "chunk_overlap",
            )
        },
        "corpus_version": digest(sources),
        "sources": sources,
        "embedding_dimension": 2,
        "chunk_count": len(chunks),
        "document_count": len(sources),
        "chunks_sha256": digest(chunks),
        "bm25_sha256": digest(lexical_data),
        "faiss_sha256": sha256_bytes((root / "dense.faiss").read_bytes()),
    }
    write_json(root / "manifest.json", manifest)
    return root


def fake_models(retriever, monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(nn=SimpleNamespace(Identity=lambda: None)),
    )
    retriever.encoder = SimpleNamespace(
        query=lambda question: np.array([[1, 0]], dtype="float32")
    )
    retriever.reranker = FakeReranker()


def test_filtered_retrieval_preserves_identical_cross_company_text(
    settings,
    knowledge_base,
    monkeypatch,
):
    retriever = HybridRetriever(settings)
    fake_models(retriever, monkeypatch)

    selected, trace = retriever.retrieve(
        "supply chain risk",
        ["AAPL", "MSFT"],
        [2024],
    )

    assert {chunk["ticker"] for chunk in selected} == {"AAPL", "MSFT"}
    assert all(chunk["fiscal_year"] == 2024 for chunk in selected)
    assert len(selected) <= settings.final_context_chunks
    assert all(0 < chunk["reranker_score"] < 1 for chunk in selected)
    assert len(trace["groups"]) == 2
    assert all(
        len(group["rerank_candidates"]) <= settings.rerank_top_k
        for group in trace["groups"]
    )


def test_threshold_abstention(settings, knowledge_base, monkeypatch):
    retriever = HybridRetriever(settings)
    fake_models(retriever, monkeypatch)
    settings.abstention_threshold = 0.99

    with pytest.raises(ValueError, match="Insufficient evidence"):
        retriever.retrieve("supply risk", ["AAPL"], [2024])


def test_scope_exceeding_context_limit_abstains(settings, knowledge_base):
    retriever = HybridRetriever(settings)

    with pytest.raises(ValueError, match="context limit"):
        retriever.retrieve(
            "supply risk",
            ["AAPL", "MSFT", "AMZN"],
            [2022, 2023, 2024],
        )


def test_configuration_mismatch(settings, knowledge_base):
    settings.chunk_size += 1

    with pytest.raises(ValueError, match="Incompatible"):
        HybridRetriever(settings)


def test_old_policy_rejected(settings, knowledge_base):
    path = knowledge_base / "manifest.json"
    manifest = read_json(path)
    manifest["index_version"] = 1
    write_json(path, manifest)

    with pytest.raises(ValueError, match="Incompatible index policy"):
        HybridRetriever(settings)


def test_corrupt_chunks(settings, knowledge_base):
    write_json(knowledge_base / "chunks.json", [])

    with pytest.raises(ValueError, match="Corrupt"):
        HybridRetriever(settings)


def test_corrupt_faiss_rejected_before_deserialization(
    settings,
    knowledge_base,
    monkeypatch,
):
    (knowledge_base / "dense.faiss").write_bytes(b"synthetic corruption")

    def forbidden(*args):
        raise AssertionError("Deserialization must not be reached")

    monkeypatch.setattr(faiss, "deserialize_index", forbidden)

    with pytest.raises(ValueError, match="FAISS checksum"):
        HybridRetriever(settings)


def test_rehashed_cross_company_chunk_rejected(settings, knowledge_base):
    path = knowledge_base / "chunks.json"
    chunks = read_json(path)
    chunks[0]["cik"] = "0000789019"
    write_json(path, chunks)

    manifest_path = knowledge_base / "manifest.json"
    manifest = read_json(manifest_path)
    manifest["chunks_sha256"] = digest(chunks)
    write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match="provenance mismatch"):
        HybridRetriever(settings)


def test_runtime_does_not_refit_bm25(settings, knowledge_base, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("BM25 must not be fitted during runtime loading")

    monkeypatch.setattr(
        "ai_service.retrieval.hybrid.BM25Okapi.__init__",
        forbidden,
    )

    retriever = HybridRetriever(settings)

    assert len(retriever.groups) == 9


def test_nonfinite_query_embedding_rejected(
    settings,
    knowledge_base,
    monkeypatch,
):
    retriever = HybridRetriever(settings)
    fake_models(retriever, monkeypatch)
    retriever.encoder.query = lambda question: np.array(
        [[np.nan, 0]],
        dtype="float32",
    )

    with pytest.raises(ValueError, match="query embedding"):
        retriever.retrieve("supply risk", ["AAPL"], [2024])


def test_missing_index(settings):
    with pytest.raises(ValueError, match="Missing persisted"):
        HybridRetriever(settings)
