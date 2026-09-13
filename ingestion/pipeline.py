"""Offline acquisition, resolution, and inline-XBRL reconciliation.

Stop runtime services before publishing or replacing artifacts.

Each output file is atomically replaced, but the collection is not one
filesystem transaction. The corpus manifest is published last.

Only inline-reconciled candidates enter financials.json. Unresolved and
conflicting candidates remain available in the reconciliation artifact.
"""

import argparse
import json
import re
from datetime import UTC, date, datetime
from uuid import uuid4

from ai_service.financial.reconciliation import (
    RECONCILIATION_POLICY_VERSION,
    reconcile,
)
from ai_service.financial.resolver import (
    METRICS,
    RESOLUTION_POLICY_VERSION,
    FactError,
    resolve,
)
from core.config import COMPANIES, YEARS, Settings
from core.storage import digest, sha256_bytes, write_json
from ingestion.download_reports import SECClient
from ingestion.extract import extract_html
from ingestion.identity import normalized_cik, validate_filing_identity
from ingestion.inline_facts import (
    INLINE_EXTRACTION_VERSION,
    extract_inline_facts,
)
from ingestion.validate import validate_manifest

# This identifies the acquisition/manifest protocol. Financial and inline
# policies have separate versions and participate in manifest provenance.
PIPELINE_VERSION = "offline-acquisition-v2"

SUBMISSION_COLUMNS = {
    "accessionNumber",
    "filingDate",
    "reportDate",
    "form",
    "primaryDocument",
}


def _now():
    return datetime.now(UTC).isoformat()


def rows(table):
    if not isinstance(table, dict):
        raise ValueError("SEC submissions table must be an object")

    if not SUBMISSION_COLUMNS.issubset(table):
        raise ValueError("SEC submissions table lacks required columns")

    if any(not isinstance(value, list) for value in table.values()):
        raise ValueError("SEC submissions columns must be arrays")

    if len({len(value) for value in table.values()}) != 1:
        raise ValueError("SEC submissions columns have inconsistent lengths")

    return [
        dict(zip(table, values, strict=True))
        for values in zip(*table.values(), strict=True)
    ]


def _json_object(raw):
    value = json.loads(raw)

    if not isinstance(value, dict):
        raise ValueError("SEC metadata response must be a JSON object")

    return value


def _load_company_sources(client, company, refresh_metadata):
    cik = normalized_cik(company["cik"])
    submissions_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    facts_url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

    submissions_raw = client.get(
        submissions_url,
        refresh=refresh_metadata,
    )
    submissions = _json_object(submissions_raw)

    if normalized_cik(submissions.get("cik")) != cik:
        raise ValueError("Submissions entity CIK mismatch")

    filings = rows(submissions["filings"]["recent"])
    source_hashes = {submissions_url: sha256_bytes(submissions_raw)}

    for archive in submissions["filings"].get("files", []):
        name = archive.get("name", "")

        if not re.fullmatch(r"CIK\d{10}-submissions-\d+\.json", name):
            raise ValueError("Unexpected historical submissions filename")

        if not name.startswith(f"CIK{cik}-"):
            raise ValueError("Historical submissions filename CIK mismatch")

        url = f"https://data.sec.gov/submissions/{name}"
        raw = client.get(url, refresh=refresh_metadata)
        source_hashes[url] = sha256_bytes(raw)
        filings.extend(rows(_json_object(raw)))

    facts_raw = client.get(facts_url, refresh=refresh_metadata)
    companyfacts = _json_object(facts_raw)

    if normalized_cik(companyfacts.get("cik")) != cik:
        raise ValueError("Company Facts entity CIK mismatch")

    return (
        filings,
        companyfacts,
        {
            "submissions_sources_sha256": source_hashes,
            "companyfacts_url": facts_url,
            "companyfacts_sha256": sha256_bytes(facts_raw),
        },
    )


def candidate_filings(filings, fiscal_year):
    """Narrow by report year for the configured three-company corpus.

    Fiscal identity must subsequently be confirmed by inline DEI fields.
    Filing-date year is never used to choose the fiscal year.
    """
    candidates = {}

    for filing in filings:
        if filing.get("form") != "10-K":
            continue

        report_date = filing.get("reportDate")

        if not report_date:
            continue

        try:
            period = date.fromisoformat(report_date)
        except (TypeError, ValueError):
            raise ValueError("Invalid SEC submission report date") from None

        if period.year != fiscal_year:
            continue

        accession = filing.get("accessionNumber")

        if not isinstance(accession, str) or not re.fullmatch(
            r"\d{10}-\d{2}-\d{6}",
            accession,
        ):
            raise ValueError("Invalid SEC accession number")

        identity = {key: filing[key] for key in sorted(SUBMISSION_COLUMNS)}

        if accession in candidates and candidates[accession] != identity:
            raise ValueError("Conflicting metadata for the same accession")

        candidates[accession] = identity

    return [candidates[key] for key in sorted(candidates)]


def _report_metadata(company, fiscal_year, filing):
    primary = filing["primaryDocument"]

    if not isinstance(primary, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]*\.html?",
        primary,
    ):
        raise ValueError("Primary document is not a safe HTML archive filename")

    accession = filing["accessionNumber"]
    cik = normalized_cik(company["cik"])

    return {
        **company,
        "cik": cik,
        "fiscal_year": fiscal_year,
        "filing_type": "10-K",
        "accession_number": accession,
        "filing_date": date.fromisoformat(filing["filingDate"]).isoformat(),
        "period_start": None,
        "period_end": date.fromisoformat(filing["reportDate"]).isoformat(),
        "primary_document": primary,
        "source_url": (
            "https://www.sec.gov/Archives/edgar/data/"
            f"{int(cik)}/{accession.replace('-', '')}/{primary}"
        ),
        "document_id": f"{company['ticker']}-{accession}",
    }


def acquire_report(client, company, fiscal_year, filings, stages):
    candidates = candidate_filings(filings, fiscal_year)
    stages["candidate_count"] = len(candidates)

    if not candidates:
        raise ValueError("No original 10-K candidate for requested report year")

    validated, rejected = [], []

    for filing in candidates:
        report = _report_metadata(company, fiscal_year, filing)
        raw = client.get(report["source_url"])
        stages["download"] = "completed"

        try:
            identity = validate_filing_identity(raw, report)
        except ValueError:
            rejected.append(
                {
                    "accession_number": report["accession_number"],
                    "reason": "filing_identity_validation_failed",
                }
            )
            continue

        validated.append((report, raw, identity))

    stages["rejected_candidates"] = rejected

    if len(validated) != 1:
        raise ValueError(
            "Expected exactly one identity-validated original annual filing"
        )

    report, raw, identity = validated[0]
    stages["identity"] = "completed"
    blocks = extract_html(raw)
    stages["extraction"] = "completed"
    stages["block_count"] = len(blocks)

    report.update(
        content_sha256=sha256_bytes(raw),
        content_byte_count=len(raw),
        identity=identity,
        extraction_policy="existing-html-block-extractor-v1",
        block_count=len(blocks),
    )

    return report, blocks, raw


def resolve_report(companyfacts, report, inline):
    """Return accepted facts, issues, and complete resolution records."""
    accepted, issues, records = [], [], []
    resolved_count = 0

    for metric in METRICS:
        try:
            candidate = resolve(companyfacts, report, metric)
        except FactError as exc:
            issue = {
                "document_id": report["document_id"],
                "ticker": report["ticker"],
                "fiscal_year": report["fiscal_year"],
                "metric": metric,
                "stage": "financial_resolution",
                "reason": str(exc),
            }
            issues.append(issue)
            records.append(
                {
                    **issue,
                    "status": "unresolved",
                    "candidate_fact": None,
                }
            )
            continue

        resolved_count += 1
        result = reconcile(candidate, inline)

        records.append(
            {
                **result,
                "candidate_fact": candidate,
            }
        )

        if result["status"] == "matched":
            accepted.append(
                {
                    **candidate,
                    "reconciliation_status": "matched",
                    "reconciliation_policy_version": (RECONCILIATION_POLICY_VERSION),
                    "reconciliation": result,
                }
            )
        else:
            issues.append(
                {
                    "document_id": report["document_id"],
                    "ticker": report["ticker"],
                    "fiscal_year": report["fiscal_year"],
                    "metric": metric,
                    "stage": "inline_reconciliation",
                    "status": result["status"],
                    "reason": result["reason"],
                    "reconciliation": result,
                }
            )

    return accepted, issues, records, resolved_count


def _new_slots():
    return [
        {
            **company,
            "fiscal_year": year,
            "filing_type": "10-K",
            "status": "pending",
            "accession_number": None,
            "filing_date": None,
            "period_end": None,
            "source_url": None,
            "stages": {
                "metadata": "not_started",
                "download": "not_started",
                "identity": "not_started",
                "extraction": "not_started",
                "inline_extraction": "not_started",
                "financial_resolution": "not_started",
                "inline_reconciliation": "not_started",
                "statement_layout_audit": "not_performed",
            },
        }
        for company in COMPANIES
        for year in YEARS
    ]


def run(settings=None, *, build_index=True, refresh_metadata=False):
    settings = settings if settings is not None else Settings()
    processed = settings.data_dir / "processed"
    slots = _new_slots()
    documents, facts, issues = [], [], []
    inline_documents, reconciliation_records = [], []

    audit = {
        "run_id": uuid4().hex,
        "pipeline_version": PIPELINE_VERSION,
        "resolution_policy_version": RESOLUTION_POLICY_VERSION,
        "reconciliation_policy_version": RECONCILIATION_POLICY_VERSION,
        "started_at": _now(),
        "finished_at": None,
        "status": "running",
        "refresh_metadata": refresh_metadata,
        "slots": slots,
        "publication": "not_started",
        "index": "not_started" if build_index else "not_requested",
        "statement_layout_audit": "not_performed",
    }

    def checkpoint():
        audit["updated_at"] = _now()
        write_json(processed / "ingestion_run.json", audit)

    checkpoint()

    try:
        with SECClient(settings) as client:
            for company in COMPANIES:
                company_slots = [
                    slot for slot in slots if slot["ticker"] == company["ticker"]
                ]

                try:
                    filings, companyfacts, provenance = _load_company_sources(
                        client,
                        company,
                        refresh_metadata,
                    )
                except Exception as exc:
                    for slot in company_slots:
                        slot["status"] = "failed"
                        slot["stages"]["metadata"] = "failed"
                        slot["error_category"] = type(exc).__name__
                    checkpoint()
                    continue

                for slot in company_slots:
                    stages = slot["stages"]
                    stages["metadata"] = "completed"

                    try:
                        report, blocks, raw = acquire_report(
                            client,
                            company,
                            slot["fiscal_year"],
                            filings,
                            stages,
                        )
                        report.update(provenance)
                        report.update(
                            pipeline_version=PIPELINE_VERSION,
                            resolution_policy_version=RESOLUTION_POLICY_VERSION,
                            inline_extraction_version=INLINE_EXTRACTION_VERSION,
                            reconciliation_policy_version=(
                                RECONCILIATION_POLICY_VERSION
                            ),
                            statement_layout_audit="not_performed",
                        )

                        inline = extract_inline_facts(raw, report)
                        stages["inline_extraction"] = "completed"
                        stages["inline_parsed_count"] = inline["parsed_count"]
                        stages["inline_unresolved_count"] = inline["unresolved_count"]

                        accepted, report_issues, records, resolved_count = (
                            resolve_report(companyfacts, report, inline)
                        )

                        stages["financial_resolution"] = (
                            "completed" if resolved_count == len(METRICS) else "partial"
                        )
                        stages["inline_reconciliation"] = (
                            "completed" if len(accepted) == len(METRICS) else "partial"
                        )
                        stages["resolved_metric_count"] = resolved_count
                        stages["reconciled_metric_count"] = len(accepted)
                        stages["unavailable_metric_count"] = len(METRICS) - len(
                            accepted
                        )

                        slot.update(report)
                        slot["status"] = "acquired"
                        documents.append({"metadata": report, "blocks": blocks})
                        inline_documents.append(inline)
                        reconciliation_records.extend(records)
                        facts.extend(accepted)
                        issues.extend(report_issues)
                    except Exception as exc:
                        slot["status"] = "failed"
                        slot["error_category"] = type(exc).__name__

                        for stage in (
                            "download",
                            "identity",
                            "extraction",
                            "inline_extraction",
                            "financial_resolution",
                            "inline_reconciliation",
                        ):
                            if stages[stage] == "not_started":
                                stages[stage] = "failed"
                                break

                    checkpoint()

        if any(slot["status"] != "acquired" for slot in slots):
            audit["status"] = "acquisition_incomplete"
            raise RuntimeError(
                "Corpus acquisition incomplete; inspect "
                "data/processed/ingestion_run.json. "
                "The previously published corpus was not replaced."
            )

        validate_manifest(slots)
        version = digest(slots)

        audit["corpus_version"] = version
        audit["accepted_fact_count"] = len(facts)
        audit["unavailable_metric_count"] = len(issues)
        audit["publication"] = "in_progress"
        checkpoint()

        write_json(
            processed / "corpus.json",
            {
                "version": version,
                "documents": documents,
                "created_at": _now(),
                "pipeline_version": PIPELINE_VERSION,
            },
        )
        write_json(
            processed / "inline_facts.json",
            {
                "corpus_version": version,
                "extraction_version": INLINE_EXTRACTION_VERSION,
                "documents": inline_documents,
            },
        )
        write_json(
            processed / "reconciliation.json",
            {
                "corpus_version": version,
                "policy_version": RECONCILIATION_POLICY_VERSION,
                "records": reconciliation_records,
                "statement_layout_audit": "not_performed",
            },
        )
        write_json(
            processed / "financials.json",
            {
                "corpus_version": version,
                "facts": facts,
                "issues": issues,
                "resolution_policy_version": RESOLUTION_POLICY_VERSION,
                "reconciliation_policy_version": (RECONCILIATION_POLICY_VERSION),
                "publication_policy": "Publish matched inline candidates only",
                "statement_layout_audit": "not_performed",
            },
        )
        write_json(processed / "corpus_manifest.json", slots)

        audit["publication"] = "completed"
        checkpoint()

        if build_index:
            audit["index"] = "in_progress"
            checkpoint()

            from ingestion.index import build

            build(settings)
            audit["index"] = "completed"

        audit["status"] = "completed_with_unresolved_metrics" if issues else "completed"
        return audit

    except Exception as exc:
        if audit["publication"] == "in_progress":
            audit["publication"] = "failed"
            audit["status"] = "publication_failed"
        elif audit["index"] == "in_progress":
            audit["index"] = "failed"
            audit["status"] = "index_failed"
        elif audit["status"] == "running":
            audit["status"] = "failed"

        audit["error_category"] = type(exc).__name__
        raise
    finally:
        audit["finished_at"] = _now()
        checkpoint()


def main():
    parser = argparse.ArgumentParser(
        description="Offline SEC acquisition and inline reconciliation"
    )
    parser.add_argument(
        "--skip-index",
        action="store_true",
        help="Publish source artifacts without constructing an index",
    )
    parser.add_argument(
        "--refresh-metadata",
        action="store_true",
        help="Refresh cached SEC submissions and Company Facts metadata",
    )
    args = parser.parse_args()

    run(
        build_index=not args.skip_index,
        refresh_metadata=args.refresh_metadata,
    )


if __name__ == "__main__":
    main()
