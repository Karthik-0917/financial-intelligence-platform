import argparse
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from ai_service.financial.store import FinancialStore
from ai_service.routing import classify
from core.config import Settings
from core.schemas import Query
from core.storage import digest, read_json, write_json
from evaluation.metrics import ranked_trace_ids
from evaluation.prepare import validate_questions

PACKET_VERSION = 1
REVIEW_SCOPE = "entire_requested_company_year_scope"

CANDIDATE_FIELDS = (
    "chunk_id",
    "document_id",
    "ticker",
    "fiscal_year",
    "section",
    "subsection",
    "location",
    "source_url",
    "text",
)


def _candidate(chunk):
    return {
        **{field: chunk.get(field) for field in CANDIDATE_FIELDS},
        "relevant": None,
    }


def _scope_chunks(chunks, route):
    return [
        chunk
        for chunk in chunks
        if chunk["ticker"] in route.tickers and chunk["fiscal_year"] in route.years
    ]


def build_packet(dataset, retriever, corpus_version, question_ids=None):
    validate_questions(dataset)

    if retriever.manifest.get("corpus_version") != corpus_version:
        raise ValueError("Index and corpus versions disagree")

    if any(item.get("corpus_version") != corpus_version for item in dataset):
        raise ValueError("Dataset and corpus versions disagree")

    known_ids = {item["id"] for item in dataset}

    if question_ids and not set(question_ids).issubset(known_ids):
        raise ValueError("Requested question ID is not in the dataset")

    chunks = {chunk["chunk_id"]: chunk for chunk in retriever.chunks}
    questions = []

    for item in dataset:
        if question_ids and item["id"] not in question_ids:
            continue

        route = classify(Query(question=item["question"]))

        if route.path not in {"rag", "mixed"} or route.reason:
            continue

        scoped = _scope_chunks(retriever.chunks, route)
        record = {
            "id": item["id"],
            "question": item["question"],
            "tickers": route.tickers,
            "years": route.years,
            "status": "ready_for_review",
            "scope_chunk_ids": sorted(chunk["chunk_id"] for chunk in scoped),
            "scope_chunk_count": len(scoped),
            "candidates": [],
            "additional_relevant_ids": [],
            "review_complete": False,
            "review_scope": None,
            "review_reference": "",
            "review_notes": "",
        }

        try:
            _, trace = retriever.retrieve(
                item["question"],
                route.tickers,
                route.years,
            )
            ranked = ranked_trace_ids(trace)

            if ranked is None:
                raise ValueError("Retrieval did not return a ranking trace")

            scoped_ids = set(record["scope_chunk_ids"])

            if any(
                identifier not in chunks or identifier not in scoped_ids
                for identifier in ranked
            ):
                raise ValueError("Retrieval trace contains invalid source scope")

            record["candidates"] = [
                _candidate(chunks[identifier]) for identifier in ranked
            ]
        except (ValueError, OSError, ImportError):
            record["status"] = "retrieval_unavailable"
            record["failure_category"] = "local_retrieval_failed_or_abstained"

        questions.append(record)

    return {
        "packet_version": PACKET_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "dataset_signature": digest(dataset),
        "corpus_version": corpus_version,
        "index_signature": digest(retriever.manifest),
        "review_instructions": [
            "Candidate ordering is a retrieval result, not a relevance label.",
            "Set each candidate's relevant field to true or false after review.",
            "Review the complete requested source scope in indexes/chunks.json.",
            "Add relevant IDs outside the candidate list to additional_relevant_ids.",
            "Do not modify source excerpts, identifiers, or question scope.",
            "Set review_scope to entire_requested_company_year_scope.",
            "Provide a non-sensitive review_reference and set review_complete true.",
            "No relevant chunks means undefined recall, not a perfect score.",
        ],
        "questions": questions,
    }


def apply_annotations(dataset, packet, retriever):
    validate_questions(dataset)

    if not isinstance(packet, dict) or packet.get("packet_version") != PACKET_VERSION:
        raise ValueError("Unsupported review packet")

    if packet.get("dataset_signature") != digest(dataset):
        raise ValueError("Review packet belongs to a different dataset")

    if packet.get("index_signature") != digest(retriever.manifest):
        raise ValueError("Review packet belongs to a different index")

    corpus_version = retriever.manifest.get("corpus_version")

    if packet.get("corpus_version") != corpus_version or any(
        item.get("corpus_version") != corpus_version for item in dataset
    ):
        raise ValueError("Review packet and dataset corpus versions disagree")

    entries = packet.get("questions")

    if not isinstance(entries, list):
        raise ValueError("Review packet questions must be an array")

    by_id = {item["id"]: item for item in dataset}
    chunks = {chunk["chunk_id"]: chunk for chunk in retriever.chunks}
    output = deepcopy(dataset)
    output_by_id = {item["id"]: item for item in output}
    seen = set()
    applied = 0

    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Malformed review question")

        identifier = entry.get("id")

        if (
            not isinstance(identifier, str)
            or identifier not in by_id
            or identifier in seen
        ):
            raise ValueError("Unknown or duplicate review question")

        seen.add(identifier)

        if entry.get("review_complete") is not True:
            continue

        original = by_id[identifier]
        route = classify(Query(question=original["question"]))

        if (
            route.path not in {"rag", "mixed"}
            or route.reason
            or entry.get("question") != original["question"]
            or entry.get("tickers") != route.tickers
            or entry.get("years") != route.years
        ):
            raise ValueError("Reviewed question or scope differs from dataset")

        if entry.get("status") != "ready_for_review":
            raise ValueError("Cannot apply an unavailable retrieval packet")

        if entry.get("review_scope") != REVIEW_SCOPE:
            raise ValueError(
                "Review must explicitly cover the requested company/year scope"
            )

        reference = entry.get("review_reference")

        if (
            not isinstance(reference, str)
            or not reference.strip()
            or len(reference) > 200
        ):
            raise ValueError("Provide a short non-sensitive review reference")

        scoped_ids = {
            chunk["chunk_id"] for chunk in _scope_chunks(retriever.chunks, route)
        }

        if entry.get("scope_chunk_ids") != sorted(scoped_ids):
            raise ValueError("Review scope catalog differs from current chunks")

        candidates = entry.get("candidates")
        additional = entry.get("additional_relevant_ids", [])

        if not isinstance(candidates, list) or not isinstance(additional, list):
            raise ValueError("Review candidates and additional IDs must be arrays")

        relevant = []
        candidate_ids = set()

        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise ValueError("Malformed reviewed candidate")

            chunk_id = candidate.get("chunk_id")

            if (
                not isinstance(chunk_id, str)
                or chunk_id not in scoped_ids
                or chunk_id in candidate_ids
            ):
                raise ValueError("Unknown, duplicate, or cross-scope candidate")

            candidate_ids.add(chunk_id)
            original_chunk = chunks[chunk_id]

            if any(
                candidate.get(field) != original_chunk.get(field)
                for field in CANDIDATE_FIELDS
            ):
                raise ValueError("Source excerpt or metadata changed during review")

            if type(candidate.get("relevant")) is not bool:
                raise ValueError("Every candidate requires a boolean relevance label")

            if candidate["relevant"]:
                relevant.append(chunk_id)

        for chunk_id in additional:
            if not isinstance(chunk_id, str) or chunk_id not in scoped_ids:
                raise ValueError("Additional relevant ID is unknown or cross-scope")

            if chunk_id in candidate_ids:
                candidate = next(
                    item for item in candidates if item["chunk_id"] == chunk_id
                )
                if not candidate["relevant"]:
                    raise ValueError("Conflicting relevance labels for one chunk")

            relevant.append(chunk_id)

        relevant = sorted(set(relevant))
        target = output_by_id[identifier]
        target.update(
            expected_evidence=relevant,
            retrieval_annotation_status=(
                "reviewed" if relevant else "reviewed_no_relevant_chunks"
            ),
            retrieval_annotation_scope=REVIEW_SCOPE,
            retrieval_review_reference=reference.strip(),
            retrieval_review_notes=str(entry.get("review_notes", "")),
            index_signature=packet["index_signature"],
        )
        applied += 1

    return output, applied


def _load_current(settings):
    from ai_service.retrieval.hybrid import HybridRetriever

    store = FinancialStore(settings)
    store.validate_version()
    retriever = HybridRetriever(settings)

    if retriever.manifest["corpus_version"] != store.data["corpus_version"]:
        raise ValueError("Current financial and retrieval corpora disagree")

    return store, retriever


def _check_output(source, output, overwrite):
    if source.resolve() == output.resolve():
        raise ValueError("Choose an output different from the source dataset")

    if output.exists() and not overwrite:
        raise ValueError("Output exists; choose another path or use --overwrite")


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("--dataset", default="evaluation/resolved.json")
    export_parser.add_argument("--output", default="evaluation/review.packet.json")
    export_parser.add_argument("--ids", nargs="+")
    export_parser.add_argument("--overwrite", action="store_true")

    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--dataset", default="evaluation/resolved.json")
    apply_parser.add_argument("--review", default="evaluation/review.packet.json")
    apply_parser.add_argument("--output", default="evaluation/reviewed.json")
    apply_parser.add_argument("--overwrite", action="store_true")

    args = parser.parse_args()

    try:
        source = Path(args.dataset)
        output = Path(args.output)
        _check_output(source, output, args.overwrite)
        dataset = read_json(source)
        settings = Settings()
        store, retriever = _load_current(settings)

        if args.command == "export":
            packet = build_packet(
                dataset,
                retriever,
                store.data["corpus_version"],
                args.ids,
            )
            write_json(output, packet)
        else:
            review = Path(args.review)

            if review.resolve() == output.resolve():
                raise ValueError("Do not overwrite the source review packet")

            annotated, applied = apply_annotations(
                dataset,
                read_json(review),
                retriever,
            )

            if applied == 0:
                raise ValueError("No completed reviews were available to apply")

            write_json(output, annotated)
            write_json(
                output.with_suffix(".review-metadata.json"),
                {
                    "packet_version": PACKET_VERSION,
                    "source_dataset_signature": digest(dataset),
                    "review_packet_signature": digest(read_json(review)),
                    "output_dataset_signature": digest(annotated),
                    "corpus_version": store.data["corpus_version"],
                    "index_signature": digest(retriever.manifest),
                    "applied_question_count": applied,
                    "scope": REVIEW_SCOPE,
                    "review_quality": "Human declaration; not independently verified",
                },
            )
    except (ValueError, OSError, ImportError) as exc:
        raise SystemExit(str(exc)) from None


if __name__ == "__main__":
    main()
