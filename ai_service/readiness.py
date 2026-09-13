"""Local readiness inspection without network requests or model loading.

Status describes observable local state. A configured API key does not
prove authentication. Existing index files do not prove index integrity.

Financial checks validate currently accepted facts, not every possible
metric and not financial-statement layout.
"""

from ai_service.financial.resolver import METRICS, FactError
from ai_service.generation.providers import (
    ProviderError,
    _validate_base_url,
    configured_model,
)
from ai_service.retrieval.contracts import validate_index_manifest
from core.config import COMPANIES, YEARS
from core.storage import digest, read_json
from ingestion.validate import validate_manifest

INDEX_ARTIFACTS = (
    "manifest.json",
    "chunks.json",
    "bm25.json",
    "dense.faiss",
)


def provider_configuration(settings):
    provider = settings.llm_provider
    model = configured_model(settings)
    error = None

    try:
        _validate_base_url(
            settings.groq_base_url if provider == "groq" else settings.ollama_base_url,
            require_https=provider == "groq",
        )

        if not model.strip():
            raise ProviderError("invalid_provider_configuration")
    except ProviderError:
        error = "invalid_provider_configuration"

    key_configured = (
        bool(settings.groq_api_key.get_secret_value().strip())
        if provider == "groq"
        else None
    )
    credentials_configured = (
        bool(key_configured)
        if provider == "groq"
        else bool(settings.ollama_model.strip())
    )
    complete = error is None and credentials_configured

    return {
        "provider": provider,
        "model": model,
        "llm_provider": provider,
        "llm_model": model,
        "provider_configured": error is None,
        "api_key_configured": key_configured,
        "primary_credentials_configured": credentials_configured,
        "primary_configuration_complete": complete,
        "provider_configuration_error": error,
        "fallback_enabled": settings.enable_llm_fallback,
        "fallback_model_configured": bool(settings.ollama_model.strip()),
        "provider_reachable": None,
        "provider_reachability": "not_checked",
        "provider_authentication": "not_checked",
        "structured_output_capability": "not_verified",
    }


def _read(path, default=None):
    try:
        return read_json(path, default), None
    except (OSError, ValueError):
        return default, "unreadable"


def _ingestion_summary(path):
    audit, error = _read(path)

    if error:
        return {"status": "unreadable", "error": "ingestion_audit_unreadable"}

    if audit is None:
        return {"status": "not_run"}

    if not isinstance(audit, dict):
        return {"status": "invalid", "error": "ingestion_audit_invalid"}

    summary = {
        key: audit.get(key)
        for key in (
            "run_id",
            "status",
            "started_at",
            "finished_at",
            "updated_at",
            "corpus_version",
            "publication",
            "index",
            "pipeline_version",
            "resolution_policy_version",
            "reconciliation_policy_version",
            "accepted_fact_count",
            "unavailable_metric_count",
            "error_category",
        )
    }
    slots = audit.get("slots", [])

    summary["slots"] = (
        [
            {
                "ticker": slot.get("ticker"),
                "fiscal_year": slot.get("fiscal_year"),
                "status": slot.get("status"),
                "stages": slot.get("stages", {}),
                "error_category": slot.get("error_category"),
            }
            for slot in slots
            if isinstance(slot, dict)
        ]
        if isinstance(slots, list)
        else []
    )

    summary["scope"] = (
        "Latest offline attempt; not necessarily the currently published corpus"
    )
    return summary


def _financial_summary(store):
    facts = store.data.get("facts", [])
    summary = {
        "stored_fact_count": len(facts),
        "validated_fact_count": 0,
        "invalid_fact_count": 0,
        "expected_metric_slots": len(COMPANIES) * len(YEARS) * len(METRICS),
        "coverage_complete": False,
        "artifact_versions_valid": False,
        "ready": False,
        "error": None,
    }

    if store.load_error:
        summary["error"] = "financial_artifacts_unreadable"
        return summary

    if not store.data.get("corpus_version") and not facts and not store.manifest:
        summary["status"] = "not_initialized"
        return summary

    try:
        store.validate_version()
    except (FactError, OSError, ValueError, TypeError, KeyError):
        summary["error"] = "financial_artifact_validation_failed"
        summary["status"] = "invalid"
        return summary

    summary["artifact_versions_valid"] = True
    validated_keys = set()

    for fact in facts:
        try:
            if not isinstance(fact, dict):
                raise FactError("Malformed fact")

            key = (fact["ticker"], fact["fiscal_year"], fact["metric"])
            store.fact(*key)
            validated_keys.add(key)
        except (FactError, OSError, ValueError, TypeError, KeyError):
            summary["invalid_fact_count"] += 1

    summary["validated_fact_count"] = len(validated_keys)
    summary["coverage_complete"] = (
        len(validated_keys) == summary["expected_metric_slots"]
        and summary["invalid_fact_count"] == 0
    )
    summary["ready"] = bool(validated_keys) and summary["invalid_fact_count"] == 0
    summary["status"] = (
        "invalid_facts"
        if summary["invalid_fact_count"]
        else (
            "available"
            if summary["coverage_complete"]
            else "available_with_gaps" if validated_keys else "no_validated_facts"
        )
    )
    return summary


def build_status(settings, engine):
    processed = settings.data_dir / "processed"
    sources, corpus_read_error = _read(
        processed / "corpus_manifest.json",
        [],
    )
    corpus_valid = False
    corpus_error = None
    corpus_version = None

    if corpus_read_error:
        corpus_error = "corpus_manifest_unreadable"
    elif sources:
        try:
            validate_manifest(sources)
        except (ValueError, TypeError, KeyError):
            corpus_error = "corpus_manifest_invalid"
        else:
            corpus_valid = True
            corpus_version = digest(sources)

    index_manifest, index_read_error = _read(settings.index_dir / "manifest.json")
    index_present = isinstance(index_manifest, dict) and bool(index_manifest)
    index_error = "index_manifest_unreadable" if index_read_error else None
    compatible = False

    if index_manifest is not None and not isinstance(index_manifest, dict):
        index_error = "index_manifest_invalid"
    elif index_present:
        try:
            validate_index_manifest(index_manifest, sources, settings)
        except (ValueError, TypeError, KeyError):
            index_error = "index_policy_or_corpus_mismatch"
        else:
            compatible = True

    artifacts = {
        name: (settings.index_dir / name).is_file() for name in INDEX_ARTIFACTS
    }
    artifacts_present = all(artifacts.values())
    retriever = engine.retriever
    index_loaded = retriever is not None

    loaded_manifest_matches = bool(
        index_loaded and index_present and retriever.manifest == index_manifest
    )
    models_loaded = bool(
        index_loaded
        and retriever.encoder is not None
        and retriever.reranker is not None
    )
    index_ready = bool(compatible and artifacts_present and loaded_manifest_matches)

    financial = _financial_summary(engine.store)
    store_snapshot_matches = bool(
        corpus_valid
        and not engine.store.load_error
        and engine.store.data.get("corpus_version") == corpus_version
        and digest(engine.store.manifest) == corpus_version
    )

    # This mirrors the current orchestrator's corpus-version dependency.
    # Narrative retrieval need not have all numerical metrics available.
    rag_ready = bool(
        index_ready and models_loaded and corpus_valid and store_snapshot_matches
    )

    provider = provider_configuration(settings)
    last_ingestion = _ingestion_summary(processed / "ingestion_run.json")
    last_ingestion["matches_published_corpus"] = (
        last_ingestion.get("corpus_version") == corpus_version
        if corpus_version is not None
        and last_ingestion.get("corpus_version") is not None
        else None
    )

    return {
        "status_scope": "local_readiness",
        "expected_report_count": len(COMPANIES) * len(YEARS),
        "validated_report_count": len(sources) if corpus_valid else 0,
        "corpus_valid": corpus_valid,
        "corpus_version": corpus_version,
        "corpus_error": corpus_error,
        "index_present": index_present,
        "configuration_compatible": compatible,
        "index_loaded": index_loaded,
        "index_artifacts": artifacts,
        "index_artifacts_present": artifacts_present,
        "index_ready": index_ready,
        "index_integrity": (
            "validated_at_load"
            if index_ready
            else (
                "not_loaded"
                if compatible and artifacts_present and not index_loaded
                else "not_ready"
            )
        ),
        "retrieval_models_loaded": models_loaded,
        "financial_fact_count": financial["stored_fact_count"],
        "financial_validated_fact_count": financial["validated_fact_count"],
        "financial_store_ready": financial["ready"] and store_snapshot_matches,
        "financial_coverage_complete": financial["coverage_complete"],
        "financial_store_error": financial["error"],
        "financial": financial,
        "store_snapshot_matches_published_corpus": store_snapshot_matches,
        "rag_ready": rag_ready,
        "narrative_locally_ready_to_attempt": (
            rag_ready and provider["primary_configuration_complete"]
        ),
        "index_error": index_error,
        **provider,
        "manifest": index_manifest if index_present else None,
        "last_ingestion": last_ingestion,
        "readiness_scope": (
            "Published corpus metadata; current financial artifact policies "
            "and accepted-fact reconciliation; index metadata and previously "
            "loaded index state; in-process model availability. "
            "No network or end-to-end answer test is performed."
        ),
        "note": (
            "A configured key is not authenticated here. Status does not "
            "load models, deserialize indexes, or rebuild artifacts. "
            "Index hashes were checked when the retriever loaded; they "
            "are not reread on every status request. Stop services before "
            "replacing artifacts. Full financial coverage is separate "
            "from the availability of some validated metrics."
        ),
    }
