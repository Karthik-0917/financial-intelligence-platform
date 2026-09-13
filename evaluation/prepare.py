import argparse
from copy import deepcopy
from pathlib import Path

from ai_service.financial.resolver import FactError
from ai_service.financial.store import FinancialStore
from ai_service.routing import classify
from core.config import Settings
from core.schemas import Query
from core.storage import digest, read_json, write_json
from evaluation.metrics import (
    CALCULATION_REFERENCE_FIELDS,
    FACT_REFERENCE_FIELDS,
    project_reference,
)

PREPARATION_VERSION = "corpus-bound-references-v2"


def validate_questions(questions):
    if not isinstance(questions, list) or not questions:
        raise ValueError("Evaluation questions must be a nonempty array")

    identifiers = set()
    allowed_types = {
        "FACT",
        "COMPARISON",
        "CALCULATION",
        "MULTI_DOCUMENT",
        "EXPLANATION",
        "RISK",
        "UNSUPPORTED",
    }

    for item in questions:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("id"), str)
            or not item["id"]
            or item["id"] in identifiers
            or item.get("question_type") not in allowed_types
        ):
            raise ValueError("Invalid or duplicate evaluation question identity")

        Query(question=item.get("question"))
        identifiers.add(item["id"])


def prepare_references(questions, store):
    validate_questions(questions)
    store.validate_version()
    version = store.data["corpus_version"]
    prepared = []

    for original in questions:
        item = deepcopy(original)
        route = classify(Query(question=item["question"]))

        if item.get("annotation_status") == "human_reviewed":
            if item.get("corpus_version") != version:
                raise ValueError(
                    "Human-reviewed references belong to a different corpus"
                )

            item["preparation_version"] = PREPARATION_VERSION
            prepared.append(item)
            continue

        # Never retain stale automatic numerical references after failure.
        item.update(
            expected_answer=None,
            expected_source=[],
            annotation_status="unresolved",
            corpus_version=version,
            preparation_version=PREPARATION_VERSION,
        )
        item.pop("annotation_note", None)

        if item["question_type"] == "UNSUPPORTED":
            item.update(
                expected_answer={"abstained": True},
                annotation_status="policy_reference",
                annotation_note=(
                    "Expected unsupported scope comes from the curated "
                    "question label, not the router's prediction."
                ),
            )
        elif route.path == "structured":
            try:
                facts, calculations = store.answer(route)
            except FactError as exc:
                item["annotation_note"] = str(exc)
            else:
                item.update(
                    expected_answer={
                        "facts": [
                            project_reference(fact, FACT_REFERENCE_FIELDS)
                            for fact in facts
                        ],
                        "calculations": [
                            project_reference(
                                calculation,
                                CALCULATION_REFERENCE_FIELDS,
                            )
                            for calculation in calculations
                        ],
                    },
                    expected_source=sorted(
                        {fact["accession_number"] for fact in facts}
                    ),
                    annotation_status="store_derived_reference",
                    annotation_note=(
                        "Generated from the same validated financial domain "
                        "implementation; suitable for regression, not an "
                        "independent audit of financial correctness."
                    ),
                )
        else:
            item["annotation_note"] = (
                "Narrative answers and chunk relevance require reviewed labels."
            )

        item.setdefault("expected_evidence", [])
        item.setdefault("retrieval_annotation_status", "not_reviewed")
        prepared.append(item)

    return prepared


def prepare():
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", default="evaluation/questions.json")
    parser.add_argument("--output", default="evaluation/resolved.json")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    output = Path(args.output)

    if output.exists() and not args.overwrite:
        raise SystemExit(
            "Output already exists. Preserve reviewed annotations or choose "
            "another output path. Use --overwrite only intentionally."
        )

    settings = Settings()
    questions = read_json(Path(args.questions))
    store = FinancialStore(settings)

    try:
        prepared = prepare_references(questions, store)
    except (ValueError, OSError) as exc:
        raise SystemExit(str(exc)) from None

    write_json(output, prepared)
    write_json(
        output.with_suffix(".metadata.json"),
        {
            "preparation_version": PREPARATION_VERSION,
            "source_questions_sha256": digest(questions),
            "prepared_dataset_sha256": digest(prepared),
            "corpus_version": store.data["corpus_version"],
            "question_count": len(prepared),
            "reference_scope": (
                "Automatic financial regression references and curated "
                "unsupported-scope references; no invented narrative gold "
                "answers or chunk relevance labels."
            ),
        },
    )


if __name__ == "__main__":
    prepare()
