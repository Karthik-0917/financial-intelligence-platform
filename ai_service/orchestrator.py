"""Coordinate deterministic financial answers and narrative synthesis.

Trace fields describe application stages, not hidden model reasoning.
A generated response and an accepted answer are distinct outcomes.
"""

import logging
import time
from dataclasses import asdict
from decimal import Decimal

from ai_service.citations.registry import Registry, validate_citations
from ai_service.financial.engine import display
from ai_service.financial.resolver import FactError
from ai_service.financial.store import FinancialStore
from ai_service.generation.context import prepare_context
from ai_service.generation.narrative_validation import validate_narrative
from ai_service.generation.providers import (
    ProviderError,
    configured_model,
    synthesize,
)
from ai_service.routing import classify
from core.request_context import get_request_id
from core.schemas import Response

log = logging.getLogger(__name__)


class ResearchEngine:
    def __init__(self, settings):
        self.s = settings
        self.store = FinancialStore(settings)
        self.registry = Registry(settings.data_dir / "processed/evidence.sqlite")
        self.retriever = None

    def _financial_records(self, facts):
        return [
            {
                **fact,
                "section": "SEC Company Facts with inline-XBRL reconciliation",
                "subsection": fact["concept"],
                "page": None,
                "location": (
                    f"{fact['taxonomy']}:{fact['concept']} / "
                    f"{fact['accession_number']} / {fact['period_end']}"
                ),
                "chunk_id": None,
                "retrieval_score": None,
                "reranker_score": None,
                "text": (
                    f"{fact['ticker']} FY{fact['fiscal_year']} "
                    f"{fact['metric']} = {fact['value']} {fact['unit']}; "
                    f"period {fact.get('period_start')} to {fact['period_end']}"
                ),
            }
            for fact in facts
        ]

    def _financial_lines(self, result, route):
        lines = [
            (
                f"{fact['ticker']} · FY{fact['fiscal_year']} · "
                f"{fact['metric'].replace('_', ' ')}: "
                f"{display(fact['value'], fact['unit'])}"
            )
            for fact in result.facts
        ]
        lines.extend(
            (
                f"{calculation['ticker']} · "
                f"{calculation['metric'].replace('_', ' ')}: "
                f"{display(calculation['value'], calculation['unit'])}"
            )
            for calculation in result.calculations
        )

        if route.operation and len(route.tickers) > 1 and result.calculations:
            top = max(
                result.calculations,
                key=lambda calculation: Decimal(calculation["value"]),
            )
            leaders = [
                calculation["ticker"]
                for calculation in result.calculations
                if Decimal(calculation["value"]) == Decimal(top["value"])
            ]
            lines.append(
                f"Highest {route.operation}: {', '.join(leaders)} "
                f"({display(top['value'], top['unit'])})."
            )

        return lines

    def query(self, query):
        started = time.perf_counter()
        result = Response(request_id=get_request_id())
        route = classify(query)
        result.question_type = route.question_type
        result.trace = {
            "routing": asdict(route),
            "latency_ms": {},
            "llm": {
                "configured_provider": self.s.llm_provider,
                "configured_model": configured_model(self.s),
                "attempted_provider": None,
                "attempted_model": None,
                "response_provider": None,
                "response_model": None,
                "provider": None,
                "model": None,
                "fallback_used": False,
                "fallback": None,
                "status": "not_invoked",
            },
        }

        try:
            if route.reason:
                raise ValueError(route.reason)

            records = []

            if route.path in {"structured", "mixed"}:
                stage_started = time.perf_counter()
                try:
                    result.facts, result.calculations = self.store.answer(route)
                finally:
                    result.trace["latency_ms"]["calculation"] = (
                        time.perf_counter() - stage_started
                    ) * 1000

                records.extend(self._financial_records(result.facts))
                result.trace["financial_validation"] = {
                    "status": "validated",
                    "fact_count": len(result.facts),
                    "calculation_count": len(result.calculations),
                    "corpus_version": self.store.data.get("corpus_version"),
                    "scope": (
                        "Stored Company Facts provenance and matched inline "
                        "observations; deterministic Decimal calculations"
                    ),
                }

            if route.path in {"rag", "mixed"}:
                if self.retriever is None:
                    from ai_service.retrieval.hybrid import HybridRetriever

                    self.retriever = HybridRetriever(self.s)

                if (
                    self.store.data.get("corpus_version")
                    != self.retriever.manifest["corpus_version"]
                ):
                    raise ValueError(
                        "Financial store and retrieval corpus versions disagree"
                    )

                chunks, retrieval_trace = self.retriever.retrieve(
                    query.question,
                    route.tickers,
                    route.years,
                )
                result.trace["retrieval"] = retrieval_trace
                records.extend(chunks)

            if not records:
                raise ValueError("No validated evidence available")

            registry = self.registry.register(result.request_id, records)
            result.evidence = list(registry.values())
            result.citation_ids = list(registry)
            result.trace["selected_evidence_ids"] = list(registry)
            lines = self._financial_lines(result, route)
            result.grounding_status = "deterministic_validated"

            if route.path in {"rag", "mixed"}:
                context, registry, context_trace = prepare_context(
                    self.s,
                    query.question,
                    registry,
                    result.calculations,
                )
                result.evidence = list(registry.values())
                result.citation_ids = []
                result.trace["context"] = context_trace
                result.trace["selected_evidence_ids"] = list(registry)
                result.trace["llm"].update(
                    {
                        "attempted_provider": self.s.llm_provider,
                        "attempted_model": configured_model(self.s),
                        "status": "requested",
                    }
                )

                stage_started = time.perf_counter()

                try:
                    output, metadata = synthesize(
                        self.s,
                        query.question,
                        context,
                        result.calculations,
                    )
                finally:
                    result.trace["latency_ms"]["llm"] = (
                        time.perf_counter() - stage_started
                    ) * 1000

                result.fallback_used = metadata["fallback_used"]
                result.fallback = metadata.get("fallback")
                result.trace["llm"].update(
                    {
                        "response_provider": metadata["provider"],
                        "response_model": metadata["model"],
                        "fallback_used": result.fallback_used,
                        "fallback": result.fallback,
                        "status": "response_received",
                    }
                )

                citations = validate_citations(output, registry)

                if not output.claims or not citations:
                    raise ValueError("Generated response has no cited claims")

                validate_narrative(output, registry, route.years)

                cited_groups = {
                    (
                        registry[evidence_id]["ticker"],
                        registry[evidence_id]["fiscal_year"],
                    )
                    for evidence_id in citations
                }

                if any(
                    (ticker, year) not in cited_groups
                    for ticker in route.tickers
                    for year in route.years
                ):
                    raise ValueError(
                        "Narrative citations do not cover all requested "
                        "company/year groups"
                    )

                result.provider = metadata["provider"]
                result.model = metadata["model"]
                result.citation_ids = citations
                result.key_findings = [claim.model_dump() for claim in output.claims]
                lines.extend(claim.text for claim in output.claims)
                result.grounding_status = "citations_validated_semantics_unverified"
                result.trace["llm"].update(
                    {
                        "provider": result.provider,
                        "model": result.model,
                        "status": "schema_and_citations_validated",
                    }
                )
                result.trace["narrative_citation_ids"] = citations

            result.answer = "\n".join(lines)
            result.grounded = route.path == "structured"
            result.trace["validation"] = result.grounding_status

        except (ValueError, FactError, ProviderError, OSError, ImportError) as exc:
            result.abstained = True
            result.grounded = False
            result.grounding_status = "abstained"
            result.answer = "Unable to provide a validated answer."
            result.abstention_reason = (
                str(exc)[:500]
                if isinstance(exc, (ValueError, ProviderError))
                else "Knowledge base or model unavailable; inspect system status"
            )
            result.key_findings = []
            result.provider = None
            result.model = None
            result.trace["validation"] = "abstained"
            result.trace["llm"]["provider"] = None
            result.trace["llm"]["model"] = None

            if isinstance(exc, ProviderError):
                result.trace["llm"].update(
                    {
                        "attempted_provider": exc.provider or self.s.llm_provider,
                        "attempted_model": (
                            exc.model
                            if exc.model is not None
                            else configured_model(self.s)
                        ),
                        "failure_category": exc.category,
                        "attempts": exc.attempts,
                        "status": "failed",
                    }
                )

                if exc.fallback is not None:
                    result.fallback_used = True
                    result.fallback = exc.fallback
                    result.trace["llm"]["fallback_used"] = True
                    result.trace["llm"]["fallback"] = exc.fallback
            elif result.trace["llm"]["status"] == "response_received":
                result.trace["llm"]["status"] = "response_rejected"
                result.trace["llm"][
                    "failure_category"
                ] = "application_output_validation_failed"
            elif result.trace["llm"]["status"] == "requested":
                result.trace["llm"]["status"] = "failed"

        except Exception:
            result.abstained = True
            result.grounded = False
            result.grounding_status = "abstained"
            result.answer = "Unable to provide a validated answer."
            result.abstention_reason = (
                "Processing failed; consult server logs using the request ID"
            )
            result.key_findings = []
            result.provider = None
            result.model = None
            result.trace["validation"] = "abstained"
            result.trace["llm"]["provider"] = None
            result.trace["llm"]["model"] = None

            if result.trace["llm"]["status"] in {
                "requested",
                "response_received",
            }:
                result.trace["llm"]["status"] = "failed"

            log.error("research_failure request_id=%s", result.request_id)

        result.latency_ms = (time.perf_counter() - started) * 1000
        result.trace["latency_ms"]["total"] = result.latency_ms

        log.info(
            "request_id=%s route=%s type=%s latency_ms=%.2f "
            "provider=%s model=%s fallback=%s abstained=%s",
            result.request_id,
            route.path,
            route.question_type,
            result.latency_ms,
            result.provider,
            result.model,
            result.fallback_used,
            result.abstained,
        )

        return result