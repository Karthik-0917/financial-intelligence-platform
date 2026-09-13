"""Evaluation metrics with explicit eligibility and matching rules.

Malformed ground truth raises ValueError and must be repaired before grading.
Malformed actual structured output is graded incorrect, not allowed to abort
an otherwise valid evaluation run.

These checks measure exact structured agreement and citation ID validity.
They do not establish semantic grounding or narrative correctness.
"""

import statistics
from collections import Counter
from decimal import Decimal, InvalidOperation

FACT_REFERENCE_FIELDS = (
    "ticker",
    "fiscal_year",
    "metric",
    "value",
    "unit",
    "accession_number",
    "period_start",
    "period_end",
    "concept",
)

CALCULATION_REFERENCE_FIELDS = (
    "ticker",
    "fiscal_year",
    "metric",
    "value",
    "unit",
    "years",
)


def retrieval_metrics(retrieved, relevant):
    relevant = set(relevant)

    if not relevant:
        return None

    retrieved = list(dict.fromkeys(retrieved))

    def hits(k):
        return len(set(retrieved[:k]) & relevant)

    return {
        "recall_at_5": hits(5) / len(relevant),
        "recall_at_10": hits(10) / len(relevant),
        "precision_at_5": hits(5) / 5,
        "mrr": next(
            (
                1 / rank
                for rank, identifier in enumerate(retrieved, 1)
                if identifier in relevant
            ),
            0,
        ),
        "hit_rate": float(bool(set(retrieved) & relevant)),
    }


def aggregate(rows):
    if not rows:
        return None

    return {key: statistics.mean(row[key] for row in rows) for key in rows[0]}


def mean(values):
    return statistics.mean(values) if values else None


def project_reference(record, fields):
    if not isinstance(record, dict):
        raise ValueError("Reference collection contains a non-object")

    return {field: record.get(field) for field in fields}


def _signature(record, fields):
    if not isinstance(record, dict):
        raise ValueError("Reference collection contains a non-object")

    if any(field not in record for field in fields):
        raise ValueError("Reference lacks required comparison fields")

    for field in ("ticker", "metric", "unit"):
        value = record.get(field)

        if not isinstance(value, str) or not value.strip():
            raise ValueError("Reference lacks financial identity or unit")

    fiscal_year = record.get("fiscal_year")

    if type(fiscal_year) is not int or not 1 <= fiscal_year <= 9999:
        raise ValueError("Reference fiscal year must be an integer year")

    values = []

    for field in fields:
        value = record[field]

        if field == "value":
            if isinstance(value, bool) or value is None:
                raise ValueError("Invalid numeric reference")

            try:
                value = Decimal(str(value))
            except (InvalidOperation, TypeError, ValueError):
                raise ValueError("Invalid numeric reference") from None

            if not value.is_finite():
                raise ValueError("Non-finite numeric reference")

        elif field == "years":
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError("Calculation years must be a positive integer or null")

            if record["metric"] in {"growth", "cagr"} and value is None:
                raise ValueError("Growth reference requires an explicit year count")

        elif field == "period_start":
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError("Invalid reference period start")

        elif field != "fiscal_year":
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Invalid reference identity field")

        values.append(value)

    return tuple(values)


def structured_correctness(response, expected):
    """Compare exact multisets, rejecting missing or extra actual records.

    Return None when no structured reference is available.
    Raise ValueError for malformed ground truth.
    Return False for abstention or malformed actual structured output.
    """
    if not isinstance(expected, dict):
        return None

    expected_facts = expected.get("facts", [])
    expected_calculations = expected.get("calculations", [])

    if not isinstance(expected_facts, list) or not isinstance(
        expected_calculations, list
    ):
        raise ValueError("Structured references must be arrays")

    if not expected_facts and not expected_calculations:
        return None

    expected_signatures = []

    for collection, fields in (
        (expected_facts, FACT_REFERENCE_FIELDS),
        (expected_calculations, CALCULATION_REFERENCE_FIELDS),
    ):
        expected_signatures.append(
            Counter(_signature(record, fields) for record in collection)
        )

    if response.abstained:
        return False

    for actual, expected_signature, fields in (
        (response.facts, expected_signatures[0], FACT_REFERENCE_FIELDS),
        (
            response.calculations,
            expected_signatures[1],
            CALCULATION_REFERENCE_FIELDS,
        ),
    ):
        if not isinstance(actual, list):
            return False

        try:
            actual_signature = Counter(
                _signature(project_reference(record, fields), fields)
                for record in actual
            )
        except ValueError:
            return False

        if actual_signature != expected_signature:
            return False

    return True


def _nonempty_ids(value):
    return (
        isinstance(value, list)
        and bool(value)
        and all(
            isinstance(identifier, str) and bool(identifier.strip())
            for identifier in value
        )
    )


def citation_id_validity(response):
    """Structural citation validity, not semantic citation correctness."""
    if response.abstained:
        return None

    if not isinstance(response.evidence, list) or any(
        not isinstance(evidence, dict) for evidence in response.evidence
    ):
        return False

    evidence_ids = [evidence.get("evidence_id") for evidence in response.evidence]

    if (
        not _nonempty_ids(evidence_ids)
        or len(set(evidence_ids)) != len(evidence_ids)
        or not _nonempty_ids(response.citation_ids)
    ):
        return False

    supplied = set(evidence_ids)

    if any(identifier not in supplied for identifier in response.citation_ids):
        return False

    if not isinstance(response.key_findings, list):
        return False

    for finding in response.key_findings:
        if not isinstance(finding, dict):
            return False

        ids = finding.get("citation_ids")

        if not _nonempty_ids(ids):
            return False

        if any(identifier not in supplied for identifier in ids):
            return False

    return True


def ranked_trace_ids(trace):
    """Interleave company/year rankings without asserting global calibration."""
    if not isinstance(trace, dict):
        raise ValueError("Malformed retrieval trace")

    groups = trace.get("reranked")

    if not isinstance(groups, list):
        return None

    if any(not isinstance(group, list) for group in groups):
        raise ValueError("Malformed reranked trace")

    result = []
    seen = set()

    for rank in range(max((len(group) for group in groups), default=0)):
        for group in groups:
            if rank >= len(group):
                continue

            entry = group[rank]

            if not isinstance(entry, dict):
                raise ValueError("Malformed reranked trace entry")

            identifier = entry.get("chunk_id")

            if not isinstance(identifier, str) or not identifier.strip():
                raise ValueError("Malformed reranked trace entry")

            if identifier not in seen:
                seen.add(identifier)
                result.append(identifier)

    return result
