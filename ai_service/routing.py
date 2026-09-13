import re
from dataclasses import dataclass

from core.config import COMPANIES, YEARS

ALIASES = {
    "fcf_margin": ["free cash flow margin", "fcf margin"],
    "operating_margin": ["operating margin"],
    "net_margin": ["net margin"],
    "free_cash_flow": ["free cash flow", "fcf"],
    "operating_cash_flow": ["operating cash flow", "cash from operations"],
    "capex": ["capital expenditures", "capital expenditure", "capex"],
    "operating_income": ["operating income"],
    "net_income": ["net income"],
    "gross_profit": ["gross profit"],
    "revenue": ["revenues", "revenue", "net sales"],
    "eps": ["eps", "earnings per share"],
    "assets": ["assets"],
    "liabilities": ["liabilities"],
    "equity": ["equity"],
    "cash": ["cash and cash equivalents", "cash & cash equivalents"],
}

YEAR_PATTERN = re.compile(
    r"(?<!\w)(?:fy\s*)?((?:19|20)\d{2})(?!\w)",
    re.IGNORECASE,
)

SHORT_FISCAL_YEAR_PATTERN = re.compile(
    r"(?<!\w)fy\s*['’]?\d{2}(?!\d)",
    re.IGNORECASE,
)

RANGE_CONNECTOR_PATTERN = re.compile(
    r"\s*(?:-|–|—|to|through|until)\s*",
    re.IGNORECASE,
)

DERIVED_METRICS = {
    "operating_margin",
    "net_margin",
    "fcf_margin",
    "free_cash_flow",
}


@dataclass
class Route:
    question_type: str
    path: str
    tickers: list[str]
    years: list[int]
    metric: str | None = None
    operation: str | None = None
    reason: str | None = None


def _contains_alias(text: str, alias: str) -> bool:
    return bool(
        re.search(
            rf"(?<!\w){re.escape(alias)}(?!\w)",
            text,
        )
    )


def _operation(text: str) -> str | None:
    if re.search(r"\bcagr\b|\bcompound annual\b", text):
        return "cagr"

    if re.search(r"\bgrowth\b", text):
        return "growth"

    return None


def _question_years(
    text: str,
    operation: str | None,
) -> tuple[list[int], str | None]:
    """Extract explicit years without substituting supported defaults."""
    if SHORT_FISCAL_YEAR_PATTERN.search(text):
        return [], "Use four-digit fiscal years, for example FY2024"

    matches = list(YEAR_PATTERN.finditer(text))
    years = {int(match.group(1)) for match in matches}

    for first, second in zip(matches, matches[1:], strict=False):
        connector = text[first.end() : second.start()]
        is_range = bool(RANGE_CONNECTOR_PATTERN.fullmatch(connector))

        if connector.strip() == "and":
            before_first = text[: first.start()]
            is_range = bool(re.search(r"\bbetween\s*$", before_first))

        if not is_range:
            continue

        start = int(first.group(1))
        end = int(second.group(1))

        if start > end:
            return (
                sorted(years),
                "Fiscal-year range is reversed; specify the earlier year first",
            )

        if operation is None:
            years.update(range(start, end + 1))

    return sorted(years), None


def _unsupported(
    tickers: list[str],
    years: list[int],
    reason: str,
) -> Route:
    return Route(
        question_type="UNSUPPORTED",
        path="abstain",
        tickers=tickers,
        years=years,
        reason=reason,
    )


def classify(query):
    text = query.question.lower()
    operation = _operation(text)

    explicit_tickers = [
        company["ticker"]
        for company in COMPANIES
        if any(
            _contains_alias(text, alias.lower())
            for alias in (company["ticker"], company["company"])
        )
    ]

    all_companies_requested = bool(
        re.search(
            r"\b(?:which company|all companies|all three companies|"
            r"three companies)\b",
            text,
        )
    )

    if all_companies_requested:
        tickers = [company["ticker"] for company in COMPANIES]
    else:
        tickers = explicit_tickers or list(dict.fromkeys(query.tickers))

    explicit_years, year_error = _question_years(text, operation)
    years = explicit_years or sorted(set(query.years))

    if re.search(
        r"\b(tesla|tsla|nvidia|nvda|google|alphabet|meta|netflix)\b",
        text,
    ):
        return _unsupported(
            tickers,
            years,
            "Company outside the supported corpus",
        )

    if re.search(
        r"\b(predict|prediction|stock price|buy|sell|invest|"
        r"investment advice|guaranteed return)\b",
        text,
    ):
        return _unsupported(
            tickers,
            years,
            "Predictions and investment advice are unsupported",
        )

    if year_error:
        return _unsupported(tickers, years, year_error)

    if any(year not in YEARS for year in years):
        return _unsupported(
            tickers,
            years,
            "Only fiscal years 2022–2024 are supported",
        )

    if re.search(
        r"\b(quarter|quarterly|q[1-4]|ttm|trailing|segment|monthly|"
        r"ebitda|debt|ratio|eur|inr|rupees)\b",
        text,
    ):
        return _unsupported(
            tickers,
            years,
            "Only supported consolidated annual metrics in "
            "SEC-reported units are available",
        )

    if not tickers:
        return _unsupported(
            tickers,
            years,
            "Specify Apple, Microsoft or Amazon",
        )

    if not years:
        return _unsupported(
            tickers,
            years,
            "Specify fiscal year(s); no implicit calendar-year assumptions",
        )

    metric = next(
        (
            name
            for name, aliases in ALIASES.items()
            if any(_contains_alias(text, alias) for alias in aliases)
        ),
        None,
    )

    # Asking for filing evidence does not by itself make a numerical
    # question narrative. Structured answers already carry provenance.
    narrative = bool(
        re.search(
            r"\b(why|explain|reason|risks?|factors?|describe|"
            r"discussion|discuss|summarize|summary)\b",
            text,
        )
    )

    if operation and metric is None:
        return _unsupported(
            tickers,
            years,
            "Specify the financial metric for the growth or CAGR calculation",
        )

    if operation and len(years) != 2:
        return _unsupported(
            tickers,
            years,
            "Growth/CAGR requires two distinct fiscal-year endpoints; "
            "for example, FY2022 to FY2024",
        )

    if not metric and not narrative:
        return _unsupported(
            tickers,
            years,
            "Metric or question intent unsupported; ask about a supported "
            "financial metric or filing narrative",
        )

    kind = "FACT"

    if len(tickers) > 1 or len(years) > 1:
        kind = "COMPARISON"

    if operation or metric in DERIVED_METRICS:
        kind = "CALCULATION"

    if len(tickers) > 1 and operation:
        kind = "MULTI_DOCUMENT"

    if narrative:
        kind = "RISK" if re.search(r"\brisks?\b", text) else "EXPLANATION"

    return Route(
        question_type=kind,
        path=(
            "mixed" if metric and narrative else "rag" if narrative else "structured"
        ),
        tickers=tickers,
        years=years,
        metric=metric,
        operation=operation,
    )
