"""Strict Company Facts versus filing inline-XBRL reconciliation.

A parsed inline observation is not automatically financial evidence.
Entity, period, concept, unit, dimensional scope, visibility, and value
must satisfy this policy.

Exact normalized numeric agreement is required. Decimal precision
annotations are preserved but do not authorize silently overwriting
different values or applying an inferred tolerance.
"""

from copy import deepcopy

from ai_service.financial.resolver import FactError, decimal_value

RECONCILIATION_POLICY_VERSION = "exact-visible-inline-v1"

MATCH_SCOPE = (
    "Exact normalized-value agreement with visible inline-XBRL "
    "observations of the same entity, concept, unit and period. "
    "Financial-statement layout and labels are not independently audited."
)


def _same_period(context, fact):
    return (
        context.get("cik") == fact.get("cik")
        and context.get("period_start") == fact.get("period_start")
        and context.get("period_end") == fact.get("period_end")
        and context.get("kind") == fact.get("kind")
    )


def reconcile(fact: dict, inline: dict) -> dict:
    """Return a reconciliation record without mutating either input.

    An unresolved observation for the selected concept blocks automatic
    acceptance when its context cannot be established. This conservative
    rule may require manual review even if another observation matches.
    """
    if not isinstance(fact, dict) or not isinstance(inline, dict):
        raise FactError("Invalid reconciliation inputs")

    if (
        inline.get("document_id") != fact.get("document_id")
        or not fact.get("content_sha256")
        or inline.get("content_sha256") != fact["content_sha256"]
    ):
        raise FactError("Reconciliation filing identity or checksum mismatch")

    observations = inline.get("observations")

    if not isinstance(observations, list) or any(
        not isinstance(observation, dict) for observation in observations
    ):
        raise FactError("Malformed inline observations")

    expected = decimal_value(fact.get("value"))
    expected_concept = f"{fact.get('taxonomy')}:{fact.get('concept')}"
    eligible = []
    blockers = []

    for observation in observations:
        if observation.get("concept") != expected_concept:
            continue

        context = observation.get("context")

        if observation.get("status") != "parsed":
            # The extractor may not have been able to attach a valid
            # context. Do not guess that this observation is irrelevant.
            if not isinstance(context, dict) or _same_period(context, fact):
                blockers.append(deepcopy(observation))
            continue

        if not isinstance(context, dict):
            blockers.append(deepcopy(observation))
            continue

        if not _same_period(context, fact):
            continue

        if context.get("dimensions") or context.get("has_segment_or_scenario"):
            continue

        if observation.get("unit") != fact.get("unit"):
            blockers.append(deepcopy(observation))
            continue

        try:
            actual = decimal_value(observation.get("normalized_value"))
        except FactError:
            blockers.append(deepcopy(observation))
            continue

        eligible.append((actual, observation))

    result = {
        "policy_version": RECONCILIATION_POLICY_VERSION,
        "document_id": fact.get("document_id"),
        "accession_number": fact.get("accession_number"),
        "ticker": fact.get("ticker"),
        "cik": fact.get("cik"),
        "fiscal_year": fact.get("fiscal_year"),
        "metric": fact.get("metric"),
        "concept": expected_concept,
        "unit": fact.get("unit"),
        "period_start": fact.get("period_start"),
        "period_end": fact.get("period_end"),
        "companyfacts_value": str(fact.get("value")),
        "companyfacts_original": deepcopy(fact.get("original_fact")),
        "companyfacts_source": fact.get("source"),
        "filing_source": fact.get("source_url"),
        "filing_content_sha256": fact.get("content_sha256"),
        "filing_observations": [deepcopy(observation) for _, observation in eligible],
        "blocking_observations": blockers,
        "status": "not_verified",
        "verification_scope": MATCH_SCOPE,
    }

    differing = [observation for value, observation in eligible if value != expected]

    if differing:
        result["status"] = "conflict"
        result["reason"] = (
            "A same-scope inline-XBRL value differs from Company Facts; "
            "neither source was overwritten"
        )
    elif blockers:
        result["reason"] = (
            "Unresolved or incompatible observations prevent an "
            "unambiguous automatic match"
        )
    elif not eligible:
        result["reason"] = (
            "No parsed consolidated inline observation matches the "
            "selected concept, entity, period and unit"
        )
    elif not any(observation.get("hidden") is False for _, observation in eligible):
        result["reason"] = "Only hidden or visibility-unknown inline observations match"
    else:
        result["status"] = "matched"
        result["reason"] = (
            "All eligible observations agree exactly with Company Facts, "
            "including at least one visible observation"
        )

    return result
