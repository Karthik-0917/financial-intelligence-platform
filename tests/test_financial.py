"""Synthetic financial-resolution and arithmetic tests.

No SEC requests, real financial observations, or model calls.
Local fixtures deliberately avoid depending on the older conftest
Company Facts wrapper, which does not include source entity identity.
"""

from copy import deepcopy
from decimal import Decimal

import pytest

from ai_service.financial.engine import calculate, display
from ai_service.financial.resolver import FactError, resolve
from tests.financial_fixtures import synthetic_manifest


@pytest.fixture
def report():
    return next(
        item
        for item in synthetic_manifest()
        if item["ticker"] == "AAPL" and item["fiscal_year"] == 2024
    )


@pytest.fixture
def raw_fact(report):
    return {
        "val": 100,
        "start": "2024-01-01",
        "end": "2024-12-31",
        "fy": 2024,
        "fp": "FY",
        "form": "10-K",
        "accn": report["accession_number"],
    }


def wrap(facts, concept="Revenues", unit="USD", cik=320193):
    return {
        "cik": cik,
        "facts": {
            "us-gaap": {
                concept: {
                    "units": {unit: facts},
                },
            },
        },
    }


def test_annual_resolves(report, raw_fact):
    result = resolve(wrap([raw_fact]), report, "revenue")

    assert result["value"] == "100"
    assert result["original_fact"] == raw_fact
    assert result["concept"] == "Revenues"
    assert result["scale_applied"] == "1"
    assert result["reconciliation_status"] == "not_performed"
    assert result["fact_id"]


@pytest.mark.parametrize(
    "changes",
    [
        {"form": "10-Q"},
        {"form": "10-K/A"},
        {"fy": 2023},
        {"fp": "Q4"},
        {"end": "2024-09-28"},
        {"start": "2024-07-01"},
        {"accn": "other"},
        {"start": "2022-10-01"},
        {"val": float("inf")},
        {"val": "NaN"},
        {"val": True},
        {"val": "not-a-number"},
        {"dimensions": {"synthetic": "segment"}},
    ],
)
def test_invalid_annual_rejected(report, raw_fact, changes):
    with pytest.raises(FactError):
        resolve(wrap([{**raw_fact, **changes}]), report, "revenue")


@pytest.mark.parametrize("cik", [None, 789019, "bad-cik", 0])
def test_wrong_or_missing_company_identity(report, raw_fact, cik):
    with pytest.raises(FactError):
        resolve(wrap([raw_fact], cik=cik), report, "revenue")


def test_wrong_unit(report, raw_fact):
    with pytest.raises(FactError):
        resolve(wrap([raw_fact], unit="shares"), report, "revenue")


def test_conflicting_annual_values(report, raw_fact):
    with pytest.raises(FactError):
        resolve(
            wrap([raw_fact, {**raw_fact, "val": 101}]),
            report,
            "revenue",
        )


def test_conflicting_annual_start_dates(report, raw_fact):
    with pytest.raises(FactError):
        resolve(
            wrap([raw_fact, {**raw_fact, "start": "2023-12-30"}]),
            report,
            "revenue",
        )


def test_cross_concept_conflict(report, raw_fact):
    data = wrap([raw_fact])
    data["facts"]["us-gaap"]["SalesRevenueNet"] = {
        "units": {"USD": [{**raw_fact, "val": 103}]}
    }

    with pytest.raises(FactError):
        resolve(data, report, "revenue")


def test_agreeing_candidate_provenance_preserved(report, raw_fact):
    data = wrap([raw_fact])
    data["facts"]["us-gaap"]["SalesRevenueNet"] = {
        "units": {"USD": [{**raw_fact, "val": 100.0}]}
    }

    result = resolve(data, report, "revenue")

    assert Decimal(result["value"]) == 100
    assert len(result["agreeing_candidates"]) == 2


def test_numeric_duplicate_equivalence(report, raw_fact):
    result = resolve(
        wrap([raw_fact, {**raw_fact, "val": 100.0}]),
        report,
        "revenue",
    )

    assert Decimal(result["value"]) == 100


def test_instant_fact_rejects_duration(report, raw_fact):
    with pytest.raises(FactError):
        resolve(wrap([raw_fact], "Assets"), report, "assets")

    instant = {key: value for key, value in raw_fact.items() if key != "start"}

    assert resolve(wrap([instant], "Assets"), report, "assets")["kind"] == "instant"


def test_diluted_eps_selected_without_basic_substitution(report, raw_fact):
    data = wrap([raw_fact], "EarningsPerShareDiluted", "USD/shares")
    data["facts"]["us-gaap"]["EarningsPerShareBasic"] = {
        "units": {"USD/shares": [{**raw_fact, "val": 105}]}
    }

    result = resolve(data, report, "eps")

    assert result["concept"] == "EarningsPerShareDiluted"
    assert result["value"] == "100"


def test_basic_only_eps_is_unavailable(report, raw_fact):
    with pytest.raises(FactError):
        resolve(
            wrap([raw_fact], "EarningsPerShareBasic", "USD/shares"),
            report,
            "eps",
        )


def test_broader_equity_is_not_a_fallback(report, raw_fact):
    instant = {key: value for key, value in raw_fact.items() if key != "start"}

    with pytest.raises(FactError):
        resolve(
            wrap(
                [instant],
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
            ),
            report,
            "equity",
        )


def test_negative_capex_is_not_absolutized(report, raw_fact):
    with pytest.raises(FactError):
        resolve(
            wrap(
                [{**raw_fact, "val": -1}],
                "PaymentsToAcquirePropertyPlantAndEquipment",
            ),
            report,
            "capex",
        )


def test_negative_net_income_preserved(report, raw_fact):
    result = resolve(
        wrap([{**raw_fact, "val": -100}], "NetIncomeLoss"),
        report,
        "net_income",
    )

    assert result["value"] == "-100"


def test_resolver_does_not_mutate_source(report, raw_fact):
    source = wrap([raw_fact])
    original = deepcopy(source)
    resolved = resolve(source, report, "revenue")
    resolved["original_fact"]["val"] = 999

    assert source == original


def fact(value, metric="revenue", year=2024, unit="USD", ticker="AAPL"):
    ciks = {"AAPL": "0000320193", "MSFT": "0000789019"}

    return {
        "value": str(value),
        "metric": metric,
        "fiscal_year": year,
        "unit": unit,
        "ticker": ticker,
        "cik": ciks[ticker],
        "accession_number": f"synthetic-{ticker}-{year}",
        "period_start": f"{year}-01-01",
        "period_end": f"{year}-12-31",
    }


@pytest.mark.parametrize(
    "metric,inputs,expected",
    [
        ("growth", [fact(100, year=2023), fact(120)], "20"),
        ("operating_margin", [fact(30, "operating_income"), fact(120)], "25"),
        ("net_margin", [fact(-3, "net_income"), fact(120)], "-2.5"),
        (
            "free_cash_flow",
            [fact(60, "operating_cash_flow"), fact(10, "capex")],
            "50",
        ),
        (
            "fcf_margin",
            [fact(60, "operating_cash_flow"), fact(10, "capex"), fact(200)],
            "25",
        ),
        (
            "growth",
            [
                fact(2, "eps", 2023, "USD/shares"),
                fact(3, "eps", 2024, "USD/shares"),
            ],
            "50",
        ),
    ],
)
def test_calculations(metric, inputs, expected):
    result = calculate(metric, inputs)

    assert Decimal(result["value"]) == Decimal(expected)
    assert result["inputs"] == inputs
    assert result["calculation_id"]
    assert result["decimal_precision"] == 38


def test_cagr():
    result = calculate("cagr", [fact(100, year=2022), fact(121)], 2)

    assert abs(Decimal(result["value"]) - 10) < Decimal("1e-25")
    assert result["years"] == 2


def test_wrong_cagr_year_count_rejected():
    with pytest.raises(FactError):
        calculate("cagr", [fact(100, year=2022), fact(121)], 1)


@pytest.mark.parametrize(
    "inputs",
    [
        [fact(0, year=2023), fact(1)],
        [fact(-1, year=2023), fact(1)],
        [fact(1, year=2024), fact(2)],
        [fact(1, year=2023, unit="shares"), fact(2)],
        [fact(1, year=2023), fact(2, ticker="MSFT")],
        [fact("NaN", year=2023), fact(2)],
        [fact(1, year=2023), fact("Infinity")],
    ],
)
def test_bad_growth(inputs):
    with pytest.raises(FactError):
        calculate("growth", inputs)


def test_period_mismatch():
    with pytest.raises(FactError):
        calculate(
            "operating_margin",
            [fact(1, "operating_income", year=2023), fact(2)],
        )


def test_same_year_different_accessions_rejected():
    revenue = fact(100)
    revenue["accession_number"] = "different-filing"

    with pytest.raises(FactError):
        calculate("operating_margin", [fact(20, "operating_income"), revenue])


@pytest.mark.parametrize("revenue", [0, -100])
def test_nonpositive_margin_denominator_rejected(revenue):
    with pytest.raises(FactError):
        calculate(
            "operating_margin",
            [fact(20, "operating_income"), fact(revenue)],
        )


def test_negative_capex_rejected_by_calculator():
    with pytest.raises(FactError):
        calculate(
            "free_cash_flow",
            [fact(60, "operating_cash_flow"), fact(-10, "capex")],
        )


def test_role_order_is_not_guessed():
    with pytest.raises(FactError):
        calculate(
            "free_cash_flow",
            [fact(10, "capex"), fact(60, "operating_cash_flow")],
        )


def test_calculation_provenance_is_independent_copy():
    inputs = [fact(100, year=2023), fact(120)]
    result = calculate("growth", inputs)
    inputs[0]["value"] = "999"

    assert result["inputs"][0]["value"] == "100"


def test_precise_display():
    assert display("123456789012", "USD") == "$123.46B"
    assert display("3.1415926", "percentage") == "3.14%"


def test_nonfinite_display_rejected():
    with pytest.raises(FactError):
        display("NaN", "USD")
