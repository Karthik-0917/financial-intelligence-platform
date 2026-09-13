import argparse
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from ai_service.generation.providers import configured_model
from ai_service.orchestrator import ResearchEngine
from ai_service.routing import classify
from core.config import Settings
from core.schemas import Query
from core.storage import digest, read_json, write_json
from evaluation.metrics import (
    aggregate,
    citation_id_validity,
    mean,
    ranked_trace_ids,
    retrieval_metrics,
    structured_correctness,
)
from evaluation.prepare import validate_questions

EVALUATION_VERSION = "actual-trace-evaluation-v2"

CONFIGURATION_FIELDS = (
    "embedding_model",
    "reranker_model",
    "chunk_size",
    "chunk_overlap",
    "faiss_top_k",
    "bm25_top_k",
    "rrf_k",
    "rerank_top_k",
    "final_context_chunks",
    "min_retrieval_score",
    "abstention_threshold",
    "llm_provider",
    "groq_model",
    "ollama_model",
    "enable_llm_fallback",
    "llm_request_timeout",
    "llm_total_timeout",
    "llm_max_retries",
    "llm_retry_backoff_seconds",
    "llm_retry_max_backoff_seconds",
    "llm_max_output_tokens",
    "llm_token_safety_margin",
    "groq_context_window_tokens",
    "ollama_context_window_tokens",
    "context_char_budget",
)


def _load_retriever(engine, settings):
    if engine.retriever is None:
        from ai_service.retrieval.hybrid import HybridRetriever

        engine.retriever = HybridRetriever(settings)

    return engine.retriever


def validate_retrieval_annotation(item, retriever, route):
    relevant = item.get("expected_evidence", [])

    if not isinstance(relevant, list) or any(
        not isinstance(identifier, str) for identifier in relevant
    ):
        raise ValueError("Invalid retrieval relevance annotations")

    if not relevant:
        return None

    if item.get("retrieval_annotation_status") != "reviewed":
        return None

    if item.get("index_signature") != digest(retriever.manifest):
        raise ValueError(
            "Reviewed retrieval annotations do not match the current index"
        )

    chunks = {chunk["chunk_id"]: chunk for chunk in retriever.chunks}

    for identifier in relevant:
        chunk = chunks.get(identifier)

        if chunk is None:
            raise ValueError("Reviewed annotation references an unknown chunk")

        if (
            chunk["ticker"] not in route.tickers
            or chunk["fiscal_year"] not in route.years
        ):
            raise ValueError("Reviewed annotation crosses requested scope")

    return list(dict.fromkeys(relevant))


def _provider_counts(counter):
    return [
        {
            "provider": provider,
            "model": model,
            "fallback_used": fallback,
            "response_count": count,
        }
        for (provider, model, fallback), count in sorted(counter.items())
    ]


def evaluate(
    dataset,
    settings,
    *,
    allow_llm=False,
    retrieval_only=False,
    engine=None,
):
    if allow_llm and retrieval_only:
        raise ValueError("Choose generation evaluation or retrieval-only mode")

    validate_questions(dataset)
    engine = engine if engine is not None else ResearchEngine(settings)
    engine.store.validate_version()
    corpus_version = engine.store.data["corpus_version"]

    if any(item.get("corpus_version") != corpus_version for item in dataset):
        raise ValueError("Dataset and current corpus versions disagree")

    retrieval_scores = []
    correctness = []
    abstention = []
    false_abstention = []
    citations = []
    latencies = []
    retrieval_latencies = []
    routing_agreement = []
    records = []
    received = Counter()
    accepted = Counter()
    stage_latencies = {}
    wall_started = time.perf_counter()

    for item in dataset:
        question = Query(question=item["question"])
        route = classify(question)
        routing_agreement.append(float(route.question_type == item["question_type"]))
        record = {
            "id": item["id"],
            "expected_question_type": item["question_type"],
            "actual_question_type": route.question_type,
            "annotation_status": item.get("annotation_status"),
        }

        relevant = None

        if (
            item.get("expected_evidence")
            and item.get("retrieval_annotation_status") == "reviewed"
        ):
            retriever = _load_retriever(engine, settings)
            relevant = validate_retrieval_annotation(item, retriever, route)

        if retrieval_only:
            if not relevant:
                records.append(
                    {
                        **record,
                        "status": "skipped_no_reviewed_retrieval_labels",
                    }
                )
                continue

            if route.path not in {"rag", "mixed"} or route.reason:
                records.append(
                    {
                        **record,
                        "status": "skipped_non_retrieval_route",
                    }
                )
                continue

            started = time.perf_counter()

            try:
                _, trace = engine.retriever.retrieve(
                    question.question,
                    route.tickers,
                    route.years,
                )
                ranked = ranked_trace_ids(trace)
                score = retrieval_metrics(ranked or [], relevant)
                retrieval_scores.append(score)
                record.update(
                    status="retrieval_executed",
                    retrieval_metrics=score,
                    retrieval_trace=trace,
                )
            except (ValueError, OSError, ImportError):
                # Failed retrieval is reported separately. Its ranking is
                # not invented and is not silently graded as a measured
                # successful retrieval with zero relevant hits.
                record.update(
                    status="retrieval_failed",
                    failure_category="retrieval_unavailable_or_abstained",
                )

            elapsed = (time.perf_counter() - started) * 1000
            retrieval_latencies.append(elapsed)
            record["retrieval_attempt_latency_ms"] = elapsed
            records.append(record)
            continue

        if route.path in {"rag", "mixed"} and not allow_llm:
            records.append({**record, "status": "skipped_llm_disabled"})
            continue

        response = engine.query(question)
        gold = item.get("expected_answer")
        grade = None

        if item["question_type"] == "UNSUPPORTED":
            policy_abstention = (
                response.abstained
                and response.question_type == "UNSUPPORTED"
                and response.trace.get("routing", {}).get("path") == "abstain"
            )
            abstention.append(float(policy_abstention))
            record["unsupported_policy_abstention_correct"] = policy_abstention
        else:
            grade = structured_correctness(response, gold)

            if grade is not None:
                correctness.append(float(grade))
                false_abstention.append(float(response.abstained))
                record["structured_reference_correct"] = grade

        validity = citation_id_validity(response)

        if validity is not None:
            citations.append(float(validity))
            record["citation_id_valid"] = validity

        if relevant:
            trace = response.trace.get("retrieval")
            ranked = ranked_trace_ids(trace) if isinstance(trace, dict) else None

            if ranked is None:
                record["retrieval_scoring_status"] = (
                    "unavailable_no_returned_retrieval_trace"
                )
            else:
                score = retrieval_metrics(ranked, relevant)
                retrieval_scores.append(score)
                record["retrieval_metrics"] = score
                record["retrieval_scoring_status"] = "scored_actual_trace"

        llm = response.trace.get("llm", {})
        response_provider = llm.get("response_provider")
        response_model = llm.get("response_model")

        if response_provider is not None:
            received[
                (
                    str(response_provider),
                    str(response_model or ""),
                    bool(response.fallback_used),
                )
            ] += 1

        if response.provider is not None:
            accepted[
                (
                    response.provider,
                    response.model or "",
                    response.fallback_used,
                )
            ] += 1

        latencies.append(response.latency_ms)

        for stage, elapsed in response.trace.get("latency_ms", {}).items():
            if isinstance(elapsed, (int, float)) and not isinstance(elapsed, bool):
                stage_latencies.setdefault(stage, []).append(elapsed)

        record.update(
            status="executed",
            response=response.model_dump(),
        )
        records.append(record)

    counts = Counter(record["status"] for record in records)
    executed_count = counts["executed"]
    retrieval_attempt_count = counts["retrieval_executed"] + counts["retrieval_failed"]

    return {
        "status": (
            "completed"
            if executed_count or retrieval_attempt_count
            else "not_yet_evaluated"
        ),
        "evaluation_version": EVALUATION_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "mode": "retrieval_only" if retrieval_only else "answer_evaluation",
        "allow_llm": allow_llm,
        "corpus_version": corpus_version,
        "dataset_version": digest(dataset),
        "index_signature": (
            digest(engine.retriever.manifest) if engine.retriever is not None else None
        ),
        "configuration": {
            field: getattr(settings, field) for field in CONFIGURATION_FIELDS
        },
        "llm": {
            "configured_provider": settings.llm_provider,
            "configured_model": configured_model(settings),
            "fallback_enabled": settings.enable_llm_fallback,
            "received_responses": _provider_counts(received),
            "accepted_responses": _provider_counts(accepted),
            "count_definition": (
                "Received counts use orchestration response-provider traces. "
                "Accepted counts use final accepted provider metadata. "
                "Neither measures HTTP attempts, tokens, billing, or responses "
                "rejected inside the provider adapter before schema parsing."
            ),
        },
        "metrics": {
            "retrieval": aggregate(retrieval_scores),
            "structured_regression_correctness": mean(correctness),
            "unsupported_abstention_correctness": mean(abstention),
            "false_abstention_on_structured_references": mean(false_abstention),
            "citation_id_validity": mean(citations),
            "routing_type_agreement": mean(routing_agreement),
            "semantic_groundedness": None,
            "narrative_correctness": None,
            "completeness": None,
            "mean_total_latency_ms": mean(latencies),
            "mean_retrieval_attempt_latency_ms": mean(retrieval_latencies),
        },
        "stage_latency_ms": {
            stage: {
                "mean": mean(values),
                "observations": len(values),
            }
            for stage, values in stage_latencies.items()
        },
        "denominators": {
            "retrieval_scored": len(retrieval_scores),
            "structured": len(correctness),
            "unsupported_abstention": len(abstention),
            "false_abstention": len(false_abstention),
            "citation": len(citations),
            "routing": len(routing_agreement),
            "answer_requests_executed": executed_count,
            "retrieval_requests_attempted": retrieval_attempt_count,
            "dataset": len(dataset),
        },
        "record_status_counts": dict(counts),
        "evaluation_wall_time_ms": (time.perf_counter() - wall_started) * 1000,
        "definitions": {
            "structured": (
                "Exact multisets of expected facts and calculations, using "
                "Decimal value equality and explicit unit/period identity."
            ),
            "retrieval": (
                "Macro averages over reviewed, index-matched annotations "
                "with returned rankings. Per-group reranked lists are "
                "interleaved in request scope order. Short rankings are "
                "not padded with invented results."
            ),
            "citation": (
                "Structural validity over every non-abstained answer; "
                "missing citations fail rather than being excluded."
            ),
            "unsupported_abstention": (
                "Curated unsupported questions must abstain through the "
                "unsupported route, not merely fail from missing resources."
            ),
            "routing": (
                "Agreement with curated question-type labels; labels may "
                "require review when multiple interpretations are reasonable."
            ),
        },
        "limitations": [
            "Store-derived references are regression checks, not independent audits.",
            "Semantic and narrative grading remains unmeasured.",
            "Reviewed annotation status is a reviewer declaration, not proof of review.",
            "Failed retrieval attempts and missing traces are counted separately.",
            "Retrieval quality averages exclude attempts without observable rankings.",
            "Threshold calibration and held-out model comparisons are not performed.",
            "Reported latency includes the actual cold/warm state of this run.",
        ],
        "records": records,
    }


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="evaluation/resolved.json")
    parser.add_argument("--allow-llm", action="store_true")
    parser.add_argument("--retrieval-only", action="store_true")
    parser.add_argument("--output-dir", default="evaluation/results")
    args = parser.parse_args()

    dataset = read_json(Path(args.dataset))

    if not dataset:
        raise SystemExit("Prepare a corpus-bound evaluation dataset first")

    try:
        output = evaluate(
            dataset,
            Settings(),
            allow_llm=args.allow_llm,
            retrieval_only=args.retrieval_only,
        )
    except (ValueError, OSError, ImportError) as exc:
        raise SystemExit(str(exc)) from None

    root = Path(args.output_dir)
    write_json(root / f"{time.time_ns()}.json", output)
    write_json(root / "latest.json", output)


if __name__ == "__main__":
    run()
