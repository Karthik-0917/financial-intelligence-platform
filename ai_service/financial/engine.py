"""Deterministic Decimal arithmetic over explicitly scoped financial inputs.

The store validates source provenance before calling this module.
This module independently validates arithmetic roles, units, periods,
entity consistency, signs, and finite numeric values.
"""

from copy import deepcopy
from datetime import date
from decimal import Decimal, DecimalException, localcontext

from ai_service.financial.resolver import FactError, decimal_value
from core.config import COMPANIES
from core.storage import digest

CALCULATION_POLICY_VERSION = "decimal-financial-v2"
DECIMAL_PRECISION = 38

ROLES = {
    "free_cash_flow": ["operating_cash_flow", "capex"],
    "operating_margin": ["operating_income", "revenue"],
    "net_margin": ["net_income", "revenue"],
    "fcf_margin": ["operating_cash_flow", "capex", "revenue"],
}

SUPPORTED_OPERATIONS = set(ROLES) | {"growth", "cagr"}


def _date(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise FactError("Calculation input has an invalid period") from None


def _validate_inputs(metric, facts):
    if metric not in SUPPORTED_OPERATIONS:
        raise FactError("Unsupported calculation")

    if not isinstance(facts, list) or not facts:
        raise FactError("Calculation requires financial inputs")

    required = {
        "value",
        "unit",
        "ticker",
        "cik",
        "metric",
        "fiscal_year",
        "period_start",
        "period_end",
        "accession_number",
    }

    for fact in facts:
        if not isinstance(fact, dict) or not required.issubset(fact):
            raise FactError("Calculation input lacks required scope metadata")

        if (
            type(fact["fiscal_year"]) is not int
            or not isinstance(fact["accession_number"], str)
            or not fact["accession_number"]
        ):
            raise FactError("Calculation input has invalid filing identity")

        end = _date(fact["period_end"])

        if fact["period_start"] is not None:
            start = _date(fact["period_start"])

            if not 350 <= (end - start).days <= 380:
                raise FactError("Calculation requires annual flow periods")

    identities = {(fact["ticker"], fact["cik"]) for fact in facts}
    known = {(company["ticker"], company["cik"]) for company in COMPANIES}

    if len(identities) != 1 or not identities.issubset(known):
        raise FactError("Calculation inputs must belong to one supported company")

    units = {fact["unit"] for fact in facts}

    if len(units) != 1 or not units.issubset({"USD", "USD/shares"}):
        raise FactError("Calculation input units disagree or are unsupported")

    if metric in ROLES:
        if [fact["metric"] for fact in facts] != ROLES[metric]:
            raise FactError("Calculation input metric roles disagree")

        if units != {"USD"}:
            raise FactError("Margins and free cash flow require USD inputs")

        scopes = {
            (
                fact["fiscal_year"],
                fact["period_start"],
                fact["period_end"],
                fact["accession_number"],
            )
            for fact in facts
        }

        if len(scopes) != 1 or facts[0]["period_start"] is None:
            raise FactError("Calculation inputs have different annual filing periods")
    else:
        if len(facts) != 2 or facts[0]["metric"] != facts[1]["metric"]:
            raise FactError("Growth requires two matching metrics")

        if facts[0]["fiscal_year"] >= facts[1]["fiscal_year"]:
            raise FactError("Growth periods must be ascending")

        if _date(facts[0]["period_end"]) >= _date(facts[1]["period_end"]):
            raise FactError("Growth reporting dates must be ascending")

        if (facts[0]["period_start"] is None) != (facts[1]["period_start"] is None):
            raise FactError("Cannot mix instant and duration inputs")

    values = [decimal_value(fact["value"]) for fact in facts]

    for fact, value in zip(facts, values, strict=True):
        if fact["metric"] == "capex" and value < 0:
            raise FactError("CapEx must be a nonnegative cash outflow")

    return values


def calculate(metric, facts, years=None):
    """Calculate without rounding inputs to display precision."""
    values = _validate_inputs(metric, facts)
    year_count = None

    if metric in {"growth", "cagr"}:
        year_count = facts[1]["fiscal_year"] - facts[0]["fiscal_year"]

        if years is not None and (type(years) is not int or years != year_count):
            raise FactError("Year count does not match fiscal-year endpoints")

    try:
        with localcontext() as context:
            context.prec = DECIMAL_PRECISION

            if metric in {"growth", "cagr"}:
                if values[0] <= 0:
                    raise FactError("Growth undefined for a nonpositive base")

                if metric == "growth":
                    value = (values[1] - values[0]) / values[0] * 100
                    formula = "(ending - beginning) / beginning × 100"
                else:
                    if values[1] <= 0:
                        raise FactError("CAGR requires positive endpoint values")

                    value = (
                        (values[1] / values[0]) ** (Decimal(1) / Decimal(year_count))
                        - 1
                    ) * 100
                    formula = "((ending / beginning)^(1 / years) - 1) × 100"
            elif metric == "free_cash_flow":
                value = values[0] - values[1]
                formula = "operating cash flow - capital expenditure"
            else:
                if values[-1] <= 0:
                    raise FactError("Margin requires a positive revenue denominator")

                numerator = (
                    values[0] - values[1] if metric == "fcf_margin" else values[0]
                )
                value = numerator / values[-1] * 100
                formula = (
                    "(operating cash flow - capex) / revenue × 100"
                    if metric == "fcf_margin"
                    else f"{facts[0]['metric']} / revenue × 100"
                )

            if not value.is_finite():
                raise FactError("Calculation produced a non-finite result")

            result_value = str(value)
    except DecimalException:
        raise FactError("Calculation exceeds supported Decimal arithmetic") from None

    identity = {
        "policy": CALCULATION_POLICY_VERSION,
        "metric": metric,
        "inputs": facts,
        "years": year_count,
    }

    return {
        "calculation_id": digest(identity),
        "calculation_policy_version": CALCULATION_POLICY_VERSION,
        "metric": metric,
        "value": result_value,
        "unit": "USD" if metric == "free_cash_flow" else "percentage",
        "formula": formula,
        "inputs": deepcopy(facts),
        "years": year_count,
        "decimal_precision": DECIMAL_PRECISION,
        "rounding_policy": (
            "Decimal arithmetic at 38 significant digits; "
            "no input or display-precision rounding before calculation"
        ),
    }


def display(value, unit):
    number = decimal_value(value)

    if unit == "percentage":
        return f"{number:.2f}%"

    if unit == "USD":
        for divisor, suffix in (
            (Decimal("1e9"), "B"),
            (Decimal("1e6"), "M"),
            (Decimal("1e3"), "K"),
        ):
            if abs(number) >= divisor:
                return f"${number / divisor:,.2f}{suffix}"

        return f"${number:,.2f}"

    return f"{number:,.2f} {unit}"
