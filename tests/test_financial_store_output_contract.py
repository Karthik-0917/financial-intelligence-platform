"""Synthetic store output-contract tests.

These tests isolate response scope and detachment behavior. Where source
validation is mocked, they do not claim to test SEC provenance validation.
No filings, models, provider calls, or network access are required.
"""

from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

import pytest

from ai_service.financial.resolver import FactError
from ai_service.financial.store import FinancialStore
from core.config import COMPANIES
from evaluation.metrics import (
    CALCULATION_REFERENCE_FIELDS,
    FACT_REFERENCE_FIELDS,
    project_reference,
    structured_correctness,
)


def synthetic_input(metric, value, year=2024):
    company = COMPANIES[0]

    return {
        "ticker": company["ticker"],
        "cik": company["cik"],
        "metric": metric,
        "value": str(value),
        "unit": "USD",
        "fiscal_year": year,
        "period_start": f"{year}-01-01",
        "period_end": f"{year}-12-31",
        "accession_number": f"synthetic-accession-{year}",
        "concept": f"Synthetic_{metric}",
        "original_fact": {"val": str(value)},
    }


def isolated_store():
    """Create an output-contract subject without loading source artifacts."""
    store = FinancialStore.__new__(FinancialStore)
    store.load_error = None
    store.manifest = []
    store.data = {
        "corpus_version": "synthetic-corpus-version",
        "facts": [],
        "issues": [],
    }
    store.inline_data = None
    store.reconciliation_data = None
    return store


def test_derived_calculation_has_explicit_scope():
    store = isolated_store()
    inputs = [
        synthetic_input("operating_cash_flow", 100),
        synthetic_input("capex", 25),
    ]

    result = store._calculate("free_cash_flow", inputs)

    assert result["ticker"] == inputs[0]["ticker"]
    assert result["fiscal_year"] == 2024
    assert result["years"] is None
    assert result["unit"] == "USD"
    assert Decimal(result["value"]) == Decimal("75")
    assert result["corpus_version"] == "synthetic-corpus-version"

    inputs[0]["original_fact"]["val"] = "changed"
    assert result["inputs"][0]["original_fact"]["val"] == "100"


def test_growth_scope_identifies_ending_year():
    store = isolated_store()
    inputs = [
        synthetic_input("revenue", 100, 2023),
        synthetic_input("revenue", 125, 2024),
    ]

    result = store._calculate("growth", inputs, 1)

    assert result["fiscal_year"] == 2024
    assert result["years"] == 1
    assert Decimal(result["value"]) == Decimal("25")
    assert [fact["fiscal_year"] for fact in result["inputs"]] == [2023, 2024]


def test_scope_is_not_attached_to_invalid_arithmetic_inputs():
    store = isolated_store()
    inputs = [
        synthetic_input("operating_cash_flow", 100),
        synthetic_input("capex", 25),
    ]
    inputs[1]["ticker"] = COMPANIES[1]["ticker"]
    inputs[1]["cik"] = COMPANIES[1]["cik"]

    with pytest.raises(FactError, match="one supported company"):
        store._calculate("free_cash_flow", inputs)


def test_answer_scope_is_compatible_with_evaluation(monkeypatch):
    store = isolated_store()
    first = synthetic_input("revenue", 100, 2023)
    second = synthetic_input("revenue", 125, 2024)
    lookup = {2023: first, 2024: second}

    monkeypatch.setattr(store, "validate_version", lambda: None)
    monkeypatch.setattr(
        store,
        "fact",
        lambda ticker, year, metric: deepcopy(lookup[year]),
    )

    route = SimpleNamespace(
        tickers=[first["ticker"]],
        years=[2023, 2024],
        metric="revenue",
        operation="growth",
    )
    facts, calculations = store.answer(route)

    reference_calculation = {
        "ticker": first["ticker"],
        "fiscal_year": 2024,
        "metric": "growth",
        "value": "25",
        "unit": "percentage",
        "years": 1,
    }
    expected = {
        "facts": [
            project_reference(first, FACT_REFERENCE_FIELDS),
            project_reference(second, FACT_REFERENCE_FIELDS),
        ],
        "calculations": [reference_calculation],
    }
    actual = SimpleNamespace(
        abstained=False,
        facts=facts,
        calculations=calculations,
    )

    assert structured_correctness(actual, expected) is True
    assert len(calculations) == 1

    projected = project_reference(
        calculations[0],
        CALCULATION_REFERENCE_FIELDS,
    )

    # Decimal values need numeric equality, not identical serialization.
    # Scope metadata must still match exactly.
    assert isinstance(projected["value"], str)
    assert Decimal(projected["value"]) == Decimal(reference_calculation["value"])
    assert {key: value for key, value in projected.items() if key != "value"} == {
        key: value for key, value in reference_calculation.items() if key != "value"
    }


def test_analytics_calculations_have_row_scope(monkeypatch):
    store = isolated_store()
    ticker = COMPANIES[0]["ticker"]
    store.manifest = [{"ticker": ticker, "fiscal_year": 2024}]

    values = {
        "operating_cash_flow": 100,
        "capex": 25,
        "revenue": 200,
        "operating_income": 40,
        "net_income": 30,
    }

    def lookup(requested_ticker, year, metric):
        if requested_ticker != ticker or year != 2024 or metric not in values:
            raise FactError("Synthetic metric unavailable")

        return synthetic_input(metric, values[metric], year)

    monkeypatch.setattr(store, "validate_version", lambda: None)
    monkeypatch.setattr(store, "fact", lookup)

    result = store.analytics()
    row = result["rows"][0]

    assert result["status"] == "available_with_gaps"
    assert len(row["calculations"]) == 4

    for calculation in row["calculations"]:
        assert calculation["ticker"] == ticker
        assert calculation["fiscal_year"] == 2024
        assert calculation["corpus_version"] == "synthetic-corpus-version"

    assert Decimal(row["values"]["free_cash_flow"]) == Decimal("75")


def test_returned_fact_does_not_mutate_loaded_store(monkeypatch):
    store = isolated_store()
    fact = synthetic_input("revenue", 100)
    fact["document_id"] = "synthetic-document"

    store.data["facts"] = [fact]
    store.manifest = [
        {
            "document_id": "synthetic-document",
            "ticker": fact["ticker"],
            "fiscal_year": 2024,
        }
    ]

    monkeypatch.setattr(store, "validate_version", lambda: None)
    monkeypatch.setattr(
        store,
        "_validate_fact",
        lambda candidate, report, metric: None,
    )

    returned = store.fact(fact["ticker"], 2024, "revenue")
    returned["value"] = "999"
    returned["original_fact"]["val"] = "999"

    assert store.data["facts"][0]["value"] == "100"
    assert store.data["facts"][0]["original_fact"]["val"] == "100"
