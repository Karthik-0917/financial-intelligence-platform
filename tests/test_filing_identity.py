"""Synthetic identity fixtures; no real filing or network access."""

import pytest

from ingestion.identity import normalized_cik, validate_filing_identity


def identity_html(*, extra="", **overrides):
    fields = {
        "EntityCentralIndexKey": "0000320193",
        "DocumentFiscalYearFocus": "2024",
        "DocumentFiscalPeriodFocus": "FY",
        "DocumentPeriodEndDate": "2024-09-28",
        "DocumentType": "10-K",
        "AmendmentFlag": "false",
    }
    fields.update(overrides)

    return (
        '<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" '
        'xmlns:dei="http://xbrl.sec.gov/dei/2024"><body>'
        + "".join(
            f'<ix:nonNumeric name="dei:{name}">{value}</ix:nonNumeric>'
            for name, value in fields.items()
            if value is not None
        )
        + extra
        + "</body></html>"
    ).encode()


def report():
    return {
        "cik": "0000320193",
        "fiscal_year": 2024,
        "filing_type": "10-K",
        "period_end": "2024-09-28",
        "filing_date": "2024-11-01",
    }


def test_complete_original_annual_identity():
    result = validate_filing_identity(identity_html(), report())

    assert result["cik"] == "0000320193"
    assert result["fiscal_year"] == 2024
    assert result["fiscal_period"] == "FY"
    assert result["amendment"] is False
    assert result["validation_status"] == "validated"


@pytest.mark.parametrize(
    "change",
    [
        {"EntityCentralIndexKey": "0000789019"},
        {"DocumentFiscalYearFocus": "2023"},
        {"DocumentFiscalPeriodFocus": "Q4"},
        {"DocumentPeriodEndDate": "2024-12-31"},
        {"DocumentType": "10-K/A"},
        {"AmendmentFlag": "true"},
        {"AmendmentFlag": "unknown"},
        {"AmendmentFlag": None},
        {"EntityCentralIndexKey": None},
        {"DocumentFiscalPeriodFocus": None},
    ],
)
def test_identity_mismatch_or_missing_field_rejected(change):
    with pytest.raises(ValueError):
        validate_filing_identity(identity_html(**change), report())


def test_conflicting_entity_identity_rejected():
    raw = identity_html(
        extra=(
            '<ix:nonNumeric name="dei:EntityCentralIndexKey">'
            "0000789019</ix:nonNumeric>"
        )
    )

    with pytest.raises(
        ValueError,
        match="Missing or conflicting DEI identity field: EntityCentralIndexKey",
    ):
        validate_filing_identity(raw, report())


def test_conflicting_period_end_dates_rejected():
    raw = identity_html(
        extra=(
            '<ix:nonNumeric name="dei:DocumentPeriodEndDate">'
            "September 29 , 2024</ix:nonNumeric>"
        )
    )

    with pytest.raises(ValueError, match="Missing or conflicting DEI filing identity"):
        validate_filing_identity(raw, report())


def test_filing_date_cannot_precede_period_end():
    metadata = {**report(), "filing_date": "2024-08-01"}

    with pytest.raises(ValueError):
        validate_filing_identity(identity_html(), metadata)


def test_filing_year_is_not_used_as_fiscal_year():
    metadata = {**report(), "filing_date": "2025-01-15"}

    result = validate_filing_identity(identity_html(), metadata)

    assert result["fiscal_year"] == 2024


def test_human_readable_dei_date():
    result = validate_filing_identity(
        identity_html(DocumentPeriodEndDate="September 28, 2024"),
        report(),
    )

    assert result["period_end"] == "2024-09-28"


@pytest.mark.parametrize(
    "text",
    [
        "September 28 , 2024",
        "September 28,2024",
        "September 28  ,   2024",
        "September\u00a028\u00a0,\u00a02024",
        "<span>September 28</span><span>, 2024</span>",
        "<span>September</span> <span>28</span> , <span>2024</span>",
    ],
)
def test_date_punctuation_whitespace_is_normalized(text):
    result = validate_filing_identity(
        identity_html(DocumentPeriodEndDate=text),
        report(),
    )

    assert result["period_end"] == "2024-09-28"


def test_december_date_with_space_before_comma():
    metadata = {
        **report(),
        "period_end": "2024-12-31",
        "filing_date": "2025-02-01",
    }

    result = validate_filing_identity(
        identity_html(DocumentPeriodEndDate="December 31 , 2024"),
        metadata,
    )

    assert result["period_end"] == "2024-12-31"
    assert result["fiscal_year"] == 2024


def test_normalized_date_still_must_match_submission():
    with pytest.raises(ValueError, match="DEI period end does not match"):
        validate_filing_identity(
            identity_html(DocumentPeriodEndDate="September 29 , 2024"),
            report(),
        )


@pytest.mark.parametrize(
    "text",
    [
        "September 31 , 2024",
        "September 28 ,, 2024",
        "September 28 , 2024 unexpected text",
        "not a date",
    ],
)
def test_invalid_date_is_not_guessed(text):
    with pytest.raises(ValueError, match="Unrecognized DEI period-end date format"):
        validate_filing_identity(
            identity_html(DocumentPeriodEndDate=text),
            report(),
        )


@pytest.mark.parametrize("value", ["320193", 320193, "0000320193"])
def test_cik_normalization(value):
    assert normalized_cik(value) == "0000320193"


@pytest.mark.parametrize("value", [None, "", "0", "-1", "1.2", "12345678901"])
def test_invalid_cik_rejected(value):
    with pytest.raises(ValueError):
        normalized_cik(value)
