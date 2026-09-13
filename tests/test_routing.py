import pytest

from ai_service.routing import classify
from core.schemas import Query


@pytest.mark.parametrize(
    "question,path,kind",
    [
        ("What was Apple's revenue in 2024?", "structured", "FACT"),
        (
            "Compare Apple's revenue in 2023 and 2024.",
            "structured",
            "COMPARISON",
        ),
        (
            "What was Microsoft's operating margin in 2024?",
            "structured",
            "CALCULATION",
        ),
        (
            "Which company had the highest revenue growth " "between 2022 and 2024?",
            "structured",
            "MULTI_DOCUMENT",
        ),
        (
            "What risks did Amazon identify in its 2024 10-K?",
            "rag",
            "RISK",
        ),
        (
            "Why did Apple's operating margin change in 2023 and 2024?",
            "mixed",
            "EXPLANATION",
        ),
        (
            "What will Apple's stock price be in 2027?",
            "abstain",
            "UNSUPPORTED",
        ),
        ("What was Apple's revenue in 2030?", "abstain", "UNSUPPORTED"),
        ("What was Tesla's revenue in 2024?", "abstain", "UNSUPPORTED"),
        (
            "What was Microsoft's EBITDA in 2024?",
            "abstain",
            "UNSUPPORTED",
        ),
        ("What was Apple's revenue?", "abstain", "UNSUPPORTED"),
    ],
)
def test_routes(question, path, kind):
    route = classify(Query(question=question))
    assert (route.path, route.question_type) == (path, kind)


def test_comparison_filters():
    route = classify(Query(question="Compare Apple and Microsoft revenue in 2024."))
    assert route.tickers == ["AAPL", "MSFT"]
    assert route.years == [2024]


@pytest.mark.parametrize("year_text", ["2024", "FY2024", "FY 2024", "fy2024"])
def test_four_digit_fiscal_year_forms(year_text):
    route = classify(Query(question=f"What was Apple's revenue in {year_text}?"))
    assert route.path == "structured"
    assert route.years == [2024]
    assert route.reason is None


def test_explicit_company_overrides_generic_selector():
    route = classify(
        Query(
            question="What was Apple's revenue in FY2024?",
            tickers=["AMZN"],
            years=[2024],
        )
    )
    assert route.tickers == ["AAPL"]
    assert route.reason is None


def test_explicit_year_overrides_generic_selector():
    route = classify(
        Query(
            question="What was Apple's revenue in FY2023?",
            tickers=["AAPL"],
            years=[2024],
        )
    )
    assert route.years == [2023]
    assert route.reason is None


def test_explicit_comparison_overrides_single_year_selector():
    route = classify(
        Query(
            question="Compare Apple's revenue in FY2022 and FY2024.",
            tickers=["AAPL"],
            years=[2024],
        )
    )
    assert route.years == [2022, 2024]
    assert route.question_type == "COMPARISON"
    assert route.reason is None


@pytest.mark.parametrize(
    "year_text",
    [
        "FY2022-FY2024",
        "2022–2024",
        "FY2022 — FY2024",
        "FY2022 to FY2024",
        "2022 through 2024",
        "between FY2022 and FY2024",
    ],
)
def test_comparison_ranges_expand(year_text):
    route = classify(
        Query(
            question=f"Compare Apple's revenue {year_text}.",
            years=[2024],
        )
    )
    assert route.years == [2022, 2023, 2024]
    assert route.question_type == "COMPARISON"
    assert route.reason is None


@pytest.mark.parametrize("operation", ["growth", "CAGR"])
def test_calculation_range_uses_endpoints(operation):
    route = classify(
        Query(
            question=f"What was Apple's revenue {operation} "
            "from FY2022 through FY2024?",
            years=[2024],
        )
    )
    assert route.years == [2022, 2024]
    assert route.operation == operation.lower()
    assert route.path == "structured"
    assert route.reason is None


def test_selector_defaults_apply_when_question_omits_scope():
    route = classify(
        Query(
            question="What was revenue?",
            tickers=["MSFT"],
            years=[2024],
        )
    )
    assert route.tickers == ["MSFT"]
    assert route.years == [2024]
    assert route.path == "structured"


def test_all_companies_overrides_single_company_selector():
    route = classify(
        Query(
            question="Which company had the highest revenue "
            "growth between FY2022 and FY2024?",
            tickers=["AAPL"],
            years=[2024],
        )
    )
    assert route.tickers == ["AAPL", "MSFT", "AMZN"]
    assert route.years == [2022, 2024]
    assert route.question_type == "MULTI_DOCUMENT"


@pytest.mark.parametrize(
    "question",
    [
        "What was Apple's revenue in FY2030?",
        "Compare Apple's revenue from FY2021 to FY2024.",
    ],
)
def test_selector_cannot_hide_unsupported_explicit_year(question):
    route = classify(Query(question=question, tickers=["AAPL"], years=[2024]))
    assert route.path == "abstain"
    assert "2022–2024" in route.reason


def test_unsupported_company_is_not_replaced_by_selector():
    route = classify(
        Query(
            question="What was Tesla's revenue in FY2024?",
            tickers=["AAPL"],
            years=[2024],
        )
    )
    assert route.path == "abstain"
    assert "outside the supported corpus" in route.reason


def test_reversed_range_requests_clarification():
    route = classify(Query(question="Compare Apple's revenue from FY2024 to FY2022."))
    assert route.path == "abstain"
    assert "reversed" in route.reason


@pytest.mark.parametrize("year_text", ["FY24", "FY 24", "FY'24", "FY’24"])
def test_short_fiscal_year_requests_clarification(year_text):
    route = classify(
        Query(
            question=f"What was Apple's revenue in {year_text}?",
            years=[2024],
        )
    )
    assert route.path == "abstain"
    assert "four-digit" in route.reason


@pytest.mark.parametrize(
    "question",
    [
        "What was Apple's revenue in its FY2024 filing?",
        "Give evidence for Apple's revenue in FY2024.",
        "What was Apple's revenue in the FY2024 10-K?",
    ],
)
def test_source_words_do_not_force_numerical_queries_through_llm(question):
    route = classify(Query(question=question))
    assert route.path == "structured"
    assert route.metric == "revenue"
    assert route.question_type == "FACT"


def test_growth_with_three_explicit_years_requests_endpoints():
    route = classify(
        Query(
            question="Calculate Apple's revenue growth "
            "for FY2022, FY2023 and FY2024."
        )
    )
    assert route.path == "abstain"
    assert "two distinct fiscal-year endpoints" in route.reason


def test_growth_without_metric_requests_clarification():
    route = classify(Query(question="Calculate Apple's growth from FY2022 to FY2024."))
    assert route.path == "abstain"
    assert "Specify the financial metric" in route.reason
