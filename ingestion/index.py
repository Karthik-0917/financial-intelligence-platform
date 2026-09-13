"""Offline index construction.

Stop runtime services before replacing index artifacts.
Files are published individually, with the manifest last.
"""

import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from ai_service.retrieval.contracts import (
    INDEX_POLICY,
    SOURCE_FIELDS,
    validate_chunks,
)
from ai_service.retrieval.hybrid import Encoder, persist_bm25
from core.config import Settings
from core.storage import digest, read_json, sha256_bytes, write_json
from ingestion.chunk import chunk_blocks
from ingestion.validate import validate_manifest


def build(settings):
    import faiss

    processed = settings.data_dir / "processed"
    corpus = read_json(processed / "corpus.json")
    sources = read_json(processed / "corpus_manifest.json", [])

    validate_manifest(sources)

    if (
        not isinstance(corpus, dict)
        or corpus.get("version") != digest(sources)
        or not isinstance(corpus.get("documents"), list)
        or len(corpus["documents"]) != len(sources)
    ):
        raise ValueError("Refusing to index incomplete or mismatched corpus")

    by_document = {source["document_id"]: source for source in sources}
    seen = set()

    for document in corpus["documents"]:
        if not isinstance(document, dict):
            raise ValueError("Malformed corpus document")

        metadata = document.get("metadata")

        if not isinstance(metadata, dict):
            raise ValueError("Corpus document lacks metadata")

        document_id = metadata.get("document_id")
        source = by_document.get(document_id)

        if source is None or document_id in seen:
            raise ValueError("Unknown or duplicate corpus document")

        if any(metadata.get(field) != source.get(field) for field in SOURCE_FIELDS):
            raise ValueError("Corpus document provenance mismatch")

        if (
            not isinstance(document.get("blocks"), list)
            or len(document["blocks"]) != source["block_count"]
        ):
            raise ValueError("Corpus extraction count mismatch")

        seen.add(document_id)

    # Offline construction may acquire model assets when absent.
    # Runtime retrieval below requests locally cached assets only.
    encoder = Encoder(settings.embedding_model, local_only=False)
    chunks = []

    for document in corpus["documents"]:
        chunks.extend(
            chunk_blocks(
                document["blocks"],
                document["metadata"],
                encoder.tokenizer,
                settings.chunk_size,
                settings.chunk_overlap,
            )
        )

    validate_chunks(chunks, sources, settings.chunk_size)
    vectors = encoder.documents([chunk["text"] for chunk in chunks])

    if (
        vectors.ndim != 2
        or vectors.shape[0] != len(chunks)
        or vectors.shape[1] <= 0
        or not np.isfinite(vectors).all()
        or not np.allclose(
            np.linalg.norm(vectors, axis=1),
            1,
            atol=1e-4,
        )
    ):
        raise ValueError("Embedding output is invalid or not normalized")

    vectors = np.ascontiguousarray(vectors, dtype="float32")
    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)
    lexical_data = persist_bm25(chunks)

    settings.index_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=settings.index_dir) as temporary:
        root = Path(temporary)
        faiss.write_index(index, str(root / "dense.faiss"))
        write_json(root / "chunks.json", chunks)
        write_json(root / "bm25.json", lexical_data)
        write_json(
            root / "manifest.json",
            {
                **INDEX_POLICY,
                "corpus_version": corpus["version"],
                "document_count": len(sources),
                "chunk_count": len(chunks),
                "embedding_model": settings.embedding_model,
                "embedding_dimension": int(vectors.shape[1]),
                "chunk_size": settings.chunk_size,
                "chunk_overlap": settings.chunk_overlap,
                "reranker_model": settings.reranker_model,
                "created_at": datetime.now(UTC).isoformat(),
                "sources": sources,
                "chunks_sha256": digest(chunks),
                "bm25_sha256": digest(lexical_data),
                "faiss_sha256": sha256_bytes((root / "dense.faiss").read_bytes()),
                "score_semantics": (
                    "Retrieval and reranker relevance; "
                    "not calibrated answer confidence"
                ),
            },
        )

        for name in (
            "dense.faiss",
            "chunks.json",
            "bm25.json",
            "manifest.json",
        ):
            os.replace(root / name, settings.index_dir / name)


if __name__ == "__main__":
    build(Settings())
