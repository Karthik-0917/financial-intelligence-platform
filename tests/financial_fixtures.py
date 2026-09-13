"""Synthetic financial artifacts for offline tests.

No fixture here represents a real filing or actual financial observation.
Archive-shaped URLs and accessions are structural test data only.
"""

from ai_service.financial.reconciliation import RECONCILIATION_POLICY_VERSION
from ai_service.financial.resolver import RESOLUTION_POLICY_VERSION
from core.config import COMPANIES, YEARS
from core.storage import digest, sha256_bytes, write_json
from ingestion.inline_facts import INLINE_EXTRACTION_VERSION
from ingestion.pipeline import resolve_report


def synthetic_manifest():
    manifest = []

    for company_index, company in enumerate(COMPANIES, start=1):
        for year in YEARS:
            accession = f"0000000000-{year % 100:02d}-{company_index:06d}"
            period_end = f"{year}-12-31"
            primary = "synthetic-fixture.htm"

            manifest.append(
                {
                    **company,
                    "fiscal_year": year,
                    "filing_type": "10-K",
                    "status": "acquired",
                    "accession_number": accession,
                    "document_id": f"{company['ticker']}-{accession}",
                    "primary_document": primary,
                    "filing_date": f"{year + 1}-02-01",
                    "period_start": None,
                    "period_end": period_end,
                    "source_url": (
                        "https://www.sec.gov/Archives/edgar/data/"
                        f"{int(company['cik'])}/"
                        f"{accession.replace('-', '')}/{primary}"
                    ),
                    "content_sha256": sha256_bytes(b"synthetic filing"),
                    "content_byte_count": len(b"synthetic filing"),
                    "block_count": 1,
                    "companyfacts_url": (
                        "https://data.sec.gov/api/xbrl/companyfacts/"
                        f"CIK{company['cik']}.json"
                    ),
                    "companyfacts_sha256": sha256_bytes(b"synthetic facts"),
                    "pipeline_version": "offline-acquisition-v2",
                    "resolution_policy_version": RESOLUTION_POLICY_VERSION,
                    "reconciliation_policy_version": (RECONCILIATION_POLICY_VERSION),
                    "identity": {
                        "policy_version": "dei-original-annual-v1",
                        "cik": company["cik"],
                        "document_type": "10-K",
                        "fiscal_year": year,
                        "fiscal_period": "FY",
                        "period_end": period_end,
                        "amendment": False,
                        "validation_status": "validated",
                    },
                    "stages": {
                        "metadata": "completed",
                        "download": "completed",
                        "identity": "completed",
                        "extraction": "completed",
                        "financial_resolution": "partial",
                        "inline_extraction": "completed",
                        "inline_reconciliation": "partial",
                    },
                }
            )

    return manifest


def publish_synthetic_financials(settings):
    manifest = synthetic_manifest()
    version = digest(manifest)
    facts, issues, records, documents = [], [], [], []

    for report in manifest:
        available = report["ticker"] == "AAPL" and report["fiscal_year"] == 2024
        original = {
            "val": 100,
            "start": f"{report['fiscal_year']}-01-01",
            "end": report["period_end"],
            "fy": report["fiscal_year"],
            "fp": "FY",
            "form": "10-K",
            "accn": report["accession_number"],
        }
        companyfacts = {
            "cik": int(report["cik"]),
            "facts": {
                "us-gaap": (
                    {"Revenues": {"units": {"USD": [original]}}} if available else {}
                )
            },
        }
        observations = []

        if available:
            observations.append(
                {
                    "concept": "us-gaap:Revenues",
                    "status": "parsed",
                    "normalized_value": "100",
                    "raw_text": "100",
                    "unit": "USD",
                    "hidden": False,
                    "location": "html-element-10",
                    "page": None,
                    "context": {
                        "cik": report["cik"],
                        "period_start": original["start"],
                        "period_end": original["end"],
                        "kind": "duration",
                        "dimensions": [],
                        "has_segment_or_scenario": False,
                    },
                }
            )

        inline = {
            "extraction_version": INLINE_EXTRACTION_VERSION,
            "document_id": report["document_id"],
            "content_sha256": report["content_sha256"],
            "observations": observations,
            "issues": [],
        }
        accepted, report_issues, report_records, _ = resolve_report(
            companyfacts,
            report,
            inline,
        )

        facts.extend(accepted)
        issues.extend(report_issues)
        records.extend(report_records)
        documents.append(inline)

    data = {
        "corpus_version": version,
        "facts": facts,
        "issues": issues,
        "resolution_policy_version": RESOLUTION_POLICY_VERSION,
        "reconciliation_policy_version": RECONCILIATION_POLICY_VERSION,
    }
    root = settings.data_dir / "processed"

    write_json(root / "corpus_manifest.json", manifest)
    write_json(root / "financials.json", data)
    write_json(
        root / "inline_facts.json",
        {
            "corpus_version": version,
            "extraction_version": INLINE_EXTRACTION_VERSION,
            "documents": documents,
        },
    )
    write_json(
        root / "reconciliation.json",
        {
            "corpus_version": version,
            "policy_version": RECONCILIATION_POLICY_VERSION,
            "records": records,
        },
    )

    return manifest, data
