"""Validate an original annual filing against application-owned scope.

The SEC submissions record supplies the accession and archive path.
Inline XBRL DEI facts independently confirm entity and fiscal identity.

This module does not infer fiscal year from the filing date.
"""

import re
from datetime import date

from bs4 import BeautifulSoup

from ingestion.extract import filing_identity, normalize

IDENTITY_POLICY_VERSION = "dei-original-annual-v1"


def normalized_cik(value) -> str:
    text = str(value).strip()

    if not re.fullmatch(r"\d{1,10}", text):
        raise ValueError("Invalid SEC entity CIK")

    if int(text) <= 0:
        raise ValueError("Invalid SEC entity CIK")

    return text.zfill(10)


def _single_dei_value(soup, local_name: str) -> str:
    values = set()

    for tag in soup.find_all(attrs={"name": True}):
        name = str(tag.get("name")).lower()

        if name != f"dei:{local_name.lower()}":
            continue

        value = normalize(tag.get_text(" ", strip=True))

        if value:
            values.add(value)

    if len(values) != 1:
        raise ValueError(f"Missing or conflicting DEI identity field: {local_name}")

    return next(iter(values))


def validate_filing_identity(raw: bytes, report: dict) -> dict:
    """Reject missing, conflicting, amended, or cross-entity identity.

    The existing date normalizer handles supported human-readable DEI
    period-end dates. Additional checks here validate the entity and
    annual/original-filing declarations.
    """
    identity = filing_identity(raw)
    soup = BeautifulSoup(raw, "lxml")

    cik = normalized_cik(_single_dei_value(soup, "EntityCentralIndexKey"))
    fiscal_period = _single_dei_value(
        soup,
        "DocumentFiscalPeriodFocus",
    ).upper()
    amendment = _single_dei_value(soup, "AmendmentFlag").lower()

    if cik != normalized_cik(report["cik"]):
        raise ValueError("DEI entity CIK does not match requested company")

    if identity["documenttype"].upper() != "10-K":
        raise ValueError("DEI document type is not an original 10-K")

    if report.get("filing_type") != "10-K":
        raise ValueError("Submission form is not an original 10-K")

    if amendment not in {"false", "0"}:
        raise ValueError("DEI amendment flag is not explicitly false")

    if fiscal_period != "FY":
        raise ValueError("DEI fiscal-period focus is not FY")

    fiscal_year = identity["documentfiscalyearfocus"]

    if not re.fullmatch(r"\d{4}", fiscal_year):
        raise ValueError("DEI fiscal-year focus is not a four-digit year")

    if int(fiscal_year) != report["fiscal_year"]:
        raise ValueError("DEI fiscal-year focus does not match requested year")

    period_end = date.fromisoformat(identity["documentperiodenddate"])
    expected_end = date.fromisoformat(report["period_end"])
    filing_date = date.fromisoformat(report["filing_date"])

    if period_end != expected_end:
        raise ValueError("DEI period end does not match submission report date")

    if filing_date < period_end:
        raise ValueError("Submission filing date precedes the reporting period")

    return {
        "policy_version": IDENTITY_POLICY_VERSION,
        "cik": cik,
        "document_type": "10-K",
        "fiscal_year": int(fiscal_year),
        "fiscal_period": "FY",
        "period_end": period_end.isoformat(),
        "amendment": False,
        "validation_status": "validated",
    }
