"""Validate the acquired corpus manifest before artifact consumption.

This validates metadata consistency and declared acquisition stages.
It does not independently reread raw downloads or prove checksum
authenticity. Runtime index loading performs its own artifact checks.
"""

import re
from datetime import date

from core.config import COMPANIES, YEARS

SUPPORTED_PIPELINE_VERSION = "offline-acquisition-v2"
SUPPORTED_IDENTITY_POLICY = "dei-original-annual-v1"


def _sha256(value) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def _date(value, field):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid manifest {field}") from None


def validate_manifest(manifest: list[dict]) -> None:
    companies = {company["ticker"]: company for company in COMPANIES}
    expected = {(company["ticker"], year) for company in COMPANIES for year in YEARS}

    if not isinstance(manifest, list) or any(
        not isinstance(report, dict) for report in manifest
    ):
        raise ValueError("Corpus manifest must be an array of objects")

    pairs = [(report.get("ticker"), report.get("fiscal_year")) for report in manifest]

    if len(pairs) != len(expected) or any(
        not isinstance(ticker, str) or type(year) is not int for ticker, year in pairs
    ):
        raise ValueError("Corpus must contain nine valid company/year slots")

    if set(pairs) != expected or len(set(pairs)) != len(pairs):
        raise ValueError(
            "Corpus must contain exactly the nine expected company/year slots"
        )

    accessions = set()
    document_ids = set()

    for report in manifest:
        company = companies[report["ticker"]]

        if (
            report.get("company") != company["company"]
            or report.get("cik") != company["cik"]
        ):
            raise ValueError("Manifest company identity mismatch")

        if report.get("status") != "acquired" or report.get("filing_type") != "10-K":
            raise ValueError("Corpus contains unavailable or non-original filings")

        if report.get("pipeline_version") != SUPPORTED_PIPELINE_VERSION:
            raise ValueError("Unsupported corpus provenance version; reacquire offline")

        accession = report.get("accession_number")
        primary = report.get("primary_document")

        if not isinstance(accession, str) or not re.fullmatch(
            r"\d{10}-\d{2}-\d{6}",
            accession,
        ):
            raise ValueError("Invalid manifest accession")

        if not isinstance(primary, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]*\.html?",
            primary,
        ):
            raise ValueError("Invalid manifest primary document")

        expected_url = (
            "https://www.sec.gov/Archives/edgar/data/"
            f"{int(company['cik'])}/{accession.replace('-', '')}/{primary}"
        )
        expected_id = f"{company['ticker']}-{accession}"

        if report.get("source_url") != expected_url:
            raise ValueError("Manifest source URL does not match accession")

        if report.get("document_id") != expected_id:
            raise ValueError("Manifest document identifier mismatch")

        if accession in accessions or expected_id in document_ids:
            raise ValueError("Duplicate accession or document identifier")

        accessions.add(accession)
        document_ids.add(expected_id)

        period_end = _date(report.get("period_end"), "period end")
        filing_date = _date(report.get("filing_date"), "filing date")

        if filing_date < period_end:
            raise ValueError("Filing date precedes reporting period")

        # This is a supported-corpus convention, not a general SEC rule.
        if period_end.year != report["fiscal_year"]:
            raise ValueError("Period end conflicts with supported fiscal scope")

        identity = report.get("identity")

        if not isinstance(identity, dict):
            raise ValueError("Manifest lacks validated inline filing identity")

        expected_identity = {
            "policy_version": SUPPORTED_IDENTITY_POLICY,
            "cik": company["cik"],
            "document_type": "10-K",
            "fiscal_year": report["fiscal_year"],
            "fiscal_period": "FY",
            "period_end": report["period_end"],
            "validation_status": "validated",
        }

        if (
            any(identity.get(key) != value for key, value in expected_identity.items())
            or identity.get("amendment") is not False
        ):
            raise ValueError("Inline filing identity disagrees with manifest")

        if not _sha256(report.get("content_sha256")):
            raise ValueError("Manifest lacks raw filing SHA-256")

        if (
            type(report.get("content_byte_count")) is not int
            or report["content_byte_count"] <= 0
            or type(report.get("block_count")) is not int
            or report["block_count"] <= 0
        ):
            raise ValueError("Manifest lacks acquired content/extraction counts")

        expected_facts_url = (
            "https://data.sec.gov/api/xbrl/companyfacts/" f"CIK{company['cik']}.json"
        )

        if report.get("companyfacts_url") != expected_facts_url or not _sha256(
            report.get("companyfacts_sha256")
        ):
            raise ValueError("Manifest lacks Company Facts source provenance")

        stages = report.get("stages")

        if not isinstance(stages, dict) or any(
            stages.get(stage) != "completed"
            for stage in ("metadata", "download", "identity", "extraction")
        ):
            raise ValueError("Manifest acquisition stages are incomplete")

        if stages.get("financial_resolution") not in {"completed", "partial"}:
            raise ValueError("Manifest financial resolution was not performed")
