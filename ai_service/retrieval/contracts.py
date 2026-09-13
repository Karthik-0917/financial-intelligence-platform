"""Shared offline/runtime retrieval artifact contracts."""

from core.storage import digest
from ingestion.chunk import CHUNK_POLICY_VERSION
from ingestion.validate import validate_manifest

INDEX_POLICY = {
    "index_version": 2,
    "chunk_policy_version": CHUNK_POLICY_VERSION,
    "embedding_strategy": "normalized-mean-380-token-windows-v1",
    "faiss_configuration": "IndexFlatIP-normalized-float32-v1",
    "bm25_format_version": 1,
}

SOURCE_FIELDS = (
    "document_id",
    "ticker",
    "company",
    "cik",
    "fiscal_year",
    "filing_type",
    "accession_number",
    "filing_date",
    "period_end",
    "source_url",
    "content_sha256",
)


def validate_index_manifest(manifest, sources, settings):
    if not isinstance(manifest, dict):
        raise ValueError("Missing persisted index manifest")

    validate_manifest(sources)

    for field, expected in INDEX_POLICY.items():
        if manifest.get(field) != expected:
            raise ValueError(f"Incompatible index policy: {field}")

    for field in (
        "embedding_model",
        "reranker_model",
        "chunk_size",
        "chunk_overlap",
    ):
        if manifest.get(field) != getattr(settings, field):
            raise ValueError(f"Incompatible index configuration: {field}")

    if (
        manifest.get("sources") != sources
        or manifest.get("corpus_version") != digest(sources)
        or manifest.get("document_count") != len(sources)
    ):
        raise ValueError("Index and acquired corpus provenance disagree")

    if (
        type(manifest.get("embedding_dimension")) is not int
        or manifest["embedding_dimension"] <= 0
        or type(manifest.get("chunk_count")) is not int
        or manifest["chunk_count"] <= 0
    ):
        raise ValueError("Invalid index dimensions or counts")


def validate_chunks(chunks, sources, size):
    if not isinstance(chunks, list) or not chunks:
        raise ValueError("Missing persisted chunks")

    by_document = {source["document_id"]: source for source in sources}
    identifiers = set()
    covered = set()

    for chunk in chunks:
        if not isinstance(chunk, dict):
            raise ValueError("Malformed chunk record")

        document_id = chunk.get("document_id")
        source = by_document.get(document_id)

        if source is None:
            raise ValueError("Chunk belongs to an unknown source document")

        if any(chunk.get(field) != source.get(field) for field in SOURCE_FIELDS):
            raise ValueError("Chunk source provenance mismatch")

        identifier = chunk.get("chunk_id")

        if (
            not isinstance(identifier, str)
            or not identifier
            or identifier in identifiers
        ):
            raise ValueError("Missing or duplicate chunk identity")

        if (
            chunk.get("chunk_policy_version") != INDEX_POLICY["chunk_policy_version"]
            or not isinstance(chunk.get("text"), str)
            or not chunk["text"].strip()
            or type(chunk.get("token_count")) is not int
            or not 0 < chunk["token_count"] <= size
        ):
            raise ValueError("Invalid chunk text, policy or token budget")

        spans = chunk.get("source_spans")

        if not isinstance(spans, list) or not spans:
            raise ValueError("Chunk lacks source spans")

        for span in spans:
            if (
                not isinstance(span, dict)
                or not isinstance(span.get("location"), str)
                or not span["location"]
                or type(span.get("character_start")) is not int
                or type(span.get("character_end")) is not int
                or not 0 <= span["character_start"] < span["character_end"]
                or span.get("page") != chunk.get("page")
            ):
                raise ValueError("Invalid chunk source span")

        expected_location = ", ".join(dict.fromkeys(span["location"] for span in spans))

        if chunk.get("location") != expected_location:
            raise ValueError("Chunk location disagrees with source spans")

        identifiers.add(identifier)
        covered.add(document_id)

    if covered != set(by_document):
        raise ValueError("Chunks do not cover every acquired document")
