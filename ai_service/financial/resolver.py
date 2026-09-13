"""Authoritative resolution of supported SEC Company Facts metrics.

SEC Company Facts values are already scaled. No additional multiplier
or inferred sign reversal is applied.

Candidate order selects between equivalent, agreeing concepts only.
Different financial meanings are not interchangeable fallbacks.
"""

from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation

from core.config import COMPANIES
from core.storage import digest

RESOLUTION_POLICY_VERSION = "sec-companyfacts-annual-v2"

METRICS = {
    "revenue": (
        [
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "SalesRevenueNet",
            "Revenues",
        ],
        "USD",
        "duration",
    ),
    "gross_profit": (["GrossProfit"], "USD", "duration"),
    "operating_income": (["OperatingIncomeLoss"], "USD", "duration"),
    "net_income": (["NetIncomeLoss"], "USD", "duration"),
    "eps": (["EarningsPerShareDiluted"], "USD/shares", "duration"),
    "assets": (["Assets"], "USD", "instant"),
    "liabilities": (["Liabilities"], "USD", "instant"),
    "equity": (["StockholdersEquity"], "USD", "instant"),
    "cash": (["CashAndCashEquivalentsAtCarryingValue"], "USD", "instant"),
    "operating_cash_flow": (
        ["NetCashProvidedByUsedInOperatingActivities"],
        "USD",
        "duration",
    ),
    "capex": (
        ["PaymentsToAcquirePropertyPlantAndEquipment"],
        "USD",
        "duration",
    ),
}

METRIC_DEFINITIONS = {
    "eps": "Diluted earnings per share; basic EPS is not a fallback",
    "equity": (
        "Stockholders' equity excluding noncontrolling interests; "
        "equity including noncontrolling interests is not a fallback"
    ),
    "capex": (
        "Payments to acquire property, plant and equipment, represented "
        "as a nonnegative cash outflow"
    ),
}


class FactError(ValueError):
    """Safe resolution or calculation failure."""


def decimal_value(value):
    if isinstance(value, bool):
        raise FactError("Boolean is not a financial value")

    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise FactError("Malformed financial value") from None

    if not result.is_finite():
        raise FactError("Non-finite financial value")

    return result


def _date(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise FactError("Malformed financial period") from None


def _cik(value):
    text = str(value).strip()

    if not text.isascii() or not text.isdigit() or not 1 <= len(text) <= 10:
        raise FactError("Missing or malformed Company Facts CIK")

    if int(text) <= 0:
        raise FactError("Missing or malformed Company Facts CIK")

    return text.zfill(10)


def _validate_entity(companyfacts, report):
    if not isinstance(companyfacts, dict) or not isinstance(report, dict):
        raise FactError("Invalid financial source or report metadata")

    companies = {company["ticker"]: company for company in COMPANIES}
    company = companies.get(report.get("ticker"))

    if company is None:
        raise FactError("Unsupported financial entity")

    if (
        _cik(report.get("cik")) != company["cik"]
        or _cik(companyfacts.get("cik")) != company["cik"]
        or report.get("company") != company["company"]
    ):
        raise FactError("Company Facts entity does not match requested company")

    if (
        report.get("filing_type") != "10-K"
        or type(report.get("fiscal_year")) is not int
        or not report.get("accession_number")
    ):
        raise FactError("Invalid annual report identity")

    _date(report.get("period_end"))


def _annual_candidate(fact, report, kind):
    if not isinstance(fact, dict):
        raise FactError("Malformed Company Facts observation")

    if (
        fact.get("form") != "10-K"
        or fact.get("accn") != report["accession_number"]
        or fact.get("end") != report["period_end"]
        or type(fact.get("fy")) is not int
        or fact.get("fy") != report["fiscal_year"]
        or fact.get("fp") != "FY"
    ):
        return False

    # Company Facts is used for entity-level observations. Do not accept
    # explicitly dimensional observations if such metadata is supplied.
    if fact.get("segment") or fact.get("dimensions"):
        raise FactError("Dimensional observations are not consolidated facts")

    if kind == "duration":
        if not fact.get("start"):
            return False

        start = _date(fact["start"])
        end = _date(fact["end"])

        if not 350 <= (end - start).days <= 380:
            return False

        if report.get("period_start") is not None:
            if fact["start"] != report["period_start"]:
                return False
    elif fact.get("start") is not None:
        return False

    return True


def resolve(companyfacts: dict, report: dict, metric: str) -> dict:
    if metric not in METRICS:
        raise FactError("Unsupported financial metric")

    _validate_entity(companyfacts, report)
    concepts, unit, kind = METRICS[metric]

    facts_root = companyfacts.get("facts", {})
    if not isinstance(facts_root, dict):
        raise FactError("Malformed Company Facts taxonomy data")

    taxonomy = facts_root.get("us-gaap", {})
    if not isinstance(taxonomy, dict):
        raise FactError("Malformed US GAAP fact data")

    found = []

    for concept in concepts:
        candidate = taxonomy.get(concept, {})

        if not isinstance(candidate, dict):
            raise FactError("Malformed candidate concept")

        units = candidate.get("units", {})
        if not isinstance(units, dict):
            raise FactError("Malformed candidate units")

        observations = units.get(unit, [])
        if not isinstance(observations, list):
            raise FactError("Malformed candidate observations")

        valid = []

        for original in observations:
            if not _annual_candidate(original, report, kind):
                continue

            value = decimal_value(original.get("val"))

            if metric in {"revenue", "assets", "cash", "capex"} and value < 0:
                raise FactError(f"Unexpected negative {metric}")

            valid.append((value, original))

        signatures = {
            (value, original.get("start"), original["end"]) for value, original in valid
        }

        if len(signatures) > 1:
            raise FactError(
                f"Conflicting annual values or periods for {metric}/{concept}"
            )

        if valid:
            # Select a stable representative only after numerical and
            # period agreement has been established.
            value, original = min(
                valid,
                key=lambda item: digest(item[1]),
            )
            found.append((concept, value, original))

    if not found:
        raise FactError(f"No validated annual {metric}")

    signatures = {
        (value, original.get("start"), original["end"]) for _, value, original in found
    }

    if len(signatures) != 1:
        raise FactError(f"Conflicting candidate concepts for {metric}")

    concept, value, original = found[0]
    original = deepcopy(original)
    normalized = format(value, "f")

    fact_identity = {
        "policy": RESOLUTION_POLICY_VERSION,
        "ticker": report["ticker"],
        "cik": report["cik"],
        "fiscal_year": report["fiscal_year"],
        "accession_number": report["accession_number"],
        "metric": metric,
        "concept": concept,
        "unit": unit,
        "period_start": original.get("start"),
        "period_end": original["end"],
        "value": normalized,
    }

    return {
        **deepcopy(report),
        "fact_id": digest(fact_identity),
        "metric": metric,
        "metric_definition": METRIC_DEFINITIONS.get(
            metric,
            metric.replace("_", " "),
        ),
        "taxonomy": "us-gaap",
        "concept": concept,
        "unit": unit,
        "original_unit": unit,
        "value": normalized,
        "original_value": str(original["val"]),
        "original_fact": original,
        "period_start": original.get("start"),
        "period_end": original["end"],
        "form": original["form"],
        "kind": kind,
        "source": (
            "https://data.sec.gov/api/xbrl/companyfacts/" f"CIK{report['cik']}.json"
        ),
        "scale_applied": "1",
        "scale_policy": "SEC Company Facts values are already scaled",
        "sign_policy": (
            "Nonnegative outflow; no absolute-value conversion"
            if metric == "capex"
            else "Preserve SEC-reported sign"
        ),
        "resolution_policy_version": RESOLUTION_POLICY_VERSION,
        "reconciliation_status": "not_performed",
        "agreeing_candidates": [
            {
                "taxonomy": "us-gaap",
                "concept": candidate_concept,
                "unit": unit,
                "original_fact": deepcopy(candidate_original),
            }
            for candidate_concept, _, candidate_original in found
        ],
        "selection_rationale": (
            "Requested entity CIK; exact accession, original 10-K, FY "
            "focus, period end and unit; annual duration for flow metrics. "
            "Candidate concepts must agree in numeric value and period. "
            "No latest-fact, basic-EPS, broader-equity, scale, or sign fallback."
        ),
    }
