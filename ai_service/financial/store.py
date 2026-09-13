"""Persisted financial data with mandatory inline reconciliation.

No SEC requests, model calls, or index construction occur here.

A genuinely absent store supports an empty analytics state. Populated
stores require current policies, matching corpus versions, and independently
rechecked persisted reconciliation inputs.

Artifacts remain trusted local application inputs. These checks detect
inconsistency, not an attacker who can rewrite every source artifact.
"""

from copy import deepcopy
from datetime import date

from ai_service.financial.engine import calculate
from ai_service.financial.reconciliation import (
    RECONCILIATION_POLICY_VERSION,
    reconcile,
)
from ai_service.financial.resolver import (
    METRICS,
    RESOLUTION_POLICY_VERSION,
    FactError,
    decimal_value,
)
from core.storage import digest, read_json
from ingestion.inline_facts import INLINE_EXTRACTION_VERSION
from ingestion.validate import validate_manifest

DERIVED = {
    "free_cash_flow": ["operating_cash_flow", "capex"],
    "operating_margin": ["operating_income", "revenue"],
    "net_margin": ["net_income", "revenue"],
    "fcf_margin": ["operating_cash_flow", "capex", "revenue"],
}

VALIDATION_SCOPE = (
    "Versioned SEC Company Facts provenance and exact agreement with "
    "persisted visible same-scope inline-XBRL observations. "
    "Financial-statement layout and labels are not independently audited."
)


def _date(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise FactError("Invalid stored financial period") from None


class FinancialStore:
    def __init__(self, settings):
        self.load_error = None
        self.manifest = []
        self.data = {"facts": [], "issues": []}
        self.inline_data = None
        self.reconciliation_data = None

        root = settings.data_dir / "processed"

        try:
            self.manifest = read_json(root / "corpus_manifest.json", [])
            self.data = read_json(
                root / "financials.json",
                {"facts": [], "issues": []},
            )
            self.inline_data = read_json(root / "inline_facts.json")
            self.reconciliation_data = read_json(root / "reconciliation.json")

            if (
                not isinstance(self.data, dict)
                or not isinstance(self.data.get("facts"), list)
                or not isinstance(self.data.get("issues", []), list)
                or not isinstance(self.manifest, list)
            ):
                raise ValueError("Invalid financial artifact structure")
        except (OSError, ValueError):
            self.load_error = "Financial artifacts are unreadable or malformed"
            self.manifest = []
            self.data = {"facts": [], "issues": []}
            self.inline_data = None
            self.reconciliation_data = None

    def validate_version(self):
        if self.load_error:
            raise FactError(self.load_error)

        version = self.data.get("corpus_version")

        if not isinstance(version, str) or not version:
            raise FactError("Financial store lacks corpus provenance; acquire offline")

        try:
            validate_manifest(self.manifest)
        except ValueError:
            raise FactError(
                "Acquired corpus provenance is invalid or incomplete; "
                "inspect the offline ingestion audit"
            ) from None

        if digest(self.manifest) != version:
            raise FactError(
                "Financial store and acquired corpus manifest disagree; "
                "rebuild offline"
            )

        if (
            self.data.get("resolution_policy_version") != RESOLUTION_POLICY_VERSION
            or self.data.get("reconciliation_policy_version")
            != RECONCILIATION_POLICY_VERSION
        ):
            raise FactError(
                "Financial policy version is missing or outdated; "
                "rerun offline resolution and reconciliation"
            )

        if any(not isinstance(fact, dict) for fact in self.data["facts"]):
            raise FactError("Financial store contains malformed fact records")

        if any(not isinstance(issue, dict) for issue in self.data.get("issues", [])):
            raise FactError("Financial store contains malformed issue records")

        if (
            not isinstance(self.inline_data, dict)
            or self.inline_data.get("corpus_version") != version
            or self.inline_data.get("extraction_version") != INLINE_EXTRACTION_VERSION
            or not isinstance(self.inline_data.get("documents"), list)
        ):
            raise FactError(
                "Inline evidence artifacts are missing, outdated or mismatched"
            )

        if (
            not isinstance(self.reconciliation_data, dict)
            or self.reconciliation_data.get("corpus_version") != version
            or self.reconciliation_data.get("policy_version")
            != RECONCILIATION_POLICY_VERSION
            or not isinstance(self.reconciliation_data.get("records"), list)
        ):
            raise FactError(
                "Reconciliation artifacts are missing, outdated or mismatched"
            )

        documents = self.inline_data["documents"]
        records = self.reconciliation_data["records"]

        if any(not isinstance(document, dict) for document in documents):
            raise FactError("Malformed inline document records")

        if any(not isinstance(record, dict) for record in records):
            raise FactError("Malformed reconciliation records")

        expected_ids = {report["document_id"] for report in self.manifest}
        actual_ids = [document.get("document_id") for document in documents]

        if (
            any(not isinstance(identifier, str) for identifier in actual_ids)
            or len(actual_ids) != len(expected_ids)
            or set(actual_ids) != expected_ids
        ):
            raise FactError("Inline evidence does not cover the acquired corpus")

        expected_keys = {
            (document_id, metric) for document_id in expected_ids for metric in METRICS
        }
        actual_keys = [
            (record.get("document_id"), record.get("metric")) for record in records
        ]

        if (
            any(
                not isinstance(document_id, str) or not isinstance(metric, str)
                for document_id, metric in actual_keys
            )
            or len(actual_keys) != len(expected_keys)
            or set(actual_keys) != expected_keys
        ):
            raise FactError(
                "Reconciliation records have missing or duplicate metric scope"
            )

    def _validate_reconciliation(self, fact, report):
        if (
            fact.get("resolution_policy_version") != RESOLUTION_POLICY_VERSION
            or fact.get("reconciliation_policy_version")
            != RECONCILIATION_POLICY_VERSION
            or fact.get("reconciliation_status") != "matched"
        ):
            raise FactError("Stored fact lacks current matched reconciliation")

        documents = [
            document
            for document in self.inline_data["documents"]
            if document["document_id"] == report["document_id"]
        ]
        records = [
            record
            for record in self.reconciliation_data["records"]
            if record["document_id"] == report["document_id"]
            and record["metric"] == fact["metric"]
        ]

        if len(documents) != 1 or len(records) != 1:
            raise FactError("Ambiguous reconciliation artifact linkage")

        current = reconcile(fact, documents[0])

        if current["status"] != "matched":
            raise FactError(
                "Persisted inline evidence does not validate the stored fact"
            )

        if fact.get("reconciliation") != current:
            raise FactError("Embedded reconciliation differs from source evidence")

        record = records[0]
        candidate = record.get("candidate_fact")

        if not isinstance(candidate, dict):
            raise FactError("Reconciliation lacks the resolved source candidate")

        # Compare the source candidate before publication annotations
        # against the published fact's financial and source identity.
        for key in (
            "fact_id",
            "document_id",
            "ticker",
            "cik",
            "fiscal_year",
            "accession_number",
            "taxonomy",
            "concept",
            "metric",
            "unit",
            "period_start",
            "period_end",
            "value",
            "original_value",
            "original_fact",
            "content_sha256",
            "companyfacts_sha256",
            "resolution_policy_version",
        ):
            if candidate.get(key) != fact.get(key):
                raise FactError("Published fact differs from its reconciled candidate")

        recorded_result = {
            key: value for key, value in record.items() if key != "candidate_fact"
        }

        if recorded_result != current:
            raise FactError("Persisted reconciliation result is inconsistent")

    def _validate_fact(self, fact, report, metric):
        concepts, expected_unit, kind = METRICS[metric]

        for key in (
            "company",
            "ticker",
            "cik",
            "fiscal_year",
            "filing_type",
            "accession_number",
            "filing_date",
            "period_end",
            "document_id",
            "source_url",
            "content_sha256",
            "companyfacts_sha256",
        ):
            if fact.get(key) != report.get(key):
                raise FactError("Stored fact disagrees with acquired provenance")

        if (
            fact.get("taxonomy") != "us-gaap"
            or fact.get("concept") not in concepts
            or fact.get("unit") != expected_unit
            or fact.get("original_unit") != expected_unit
            or fact.get("kind") != kind
            or fact.get("form") != "10-K"
            or fact.get("source") != report["companyfacts_url"]
        ):
            raise FactError("Stored fact concept, unit, or source is invalid")

        original = fact.get("original_fact")

        if not isinstance(original, dict):
            raise FactError("Stored fact lacks its original SEC payload")

        if (
            original.get("form") != "10-K"
            or original.get("accn") != report["accession_number"]
            or type(original.get("fy")) is not int
            or original.get("fy") != report["fiscal_year"]
            or original.get("fp") != "FY"
            or original.get("end") != report["period_end"]
            or original.get("start") != fact.get("period_start")
        ):
            raise FactError("Original SEC fact has inconsistent annual scope")

        value = decimal_value(fact.get("value"))

        if value != decimal_value(original.get("val")) or value != decimal_value(
            fact.get("original_value")
        ):
            raise FactError("Stored financial value differs from original SEC value")

        if metric in {"revenue", "assets", "cash", "capex"} and value < 0:
            raise FactError("Stored financial value has an unsupported sign")

        if kind == "duration":
            start = _date(original.get("start"))
            end = _date(original.get("end"))

            if not 350 <= (end - start).days <= 380:
                raise FactError("Stored fact is not an annual duration")
        elif original.get("start") is not None:
            raise FactError("Instant fact unexpectedly contains a start date")

        self._validate_reconciliation(fact, report)

    def fact(self, ticker, year, metric):
        self.validate_version()

        if metric not in METRICS:
            raise FactError("Unsupported financial metric")

        reports = [
            report
            for report in self.manifest
            if report["ticker"] == ticker and report["fiscal_year"] == year
        ]

        if len(reports) != 1:
            raise FactError("Requested company/year is outside acquired scope")

        matches = [
            fact
            for fact in self.data["facts"]
            if fact.get("ticker") == ticker
            and fact.get("fiscal_year") == year
            and fact.get("metric") == metric
        ]

        if len(matches) != 1:
            raise FactError(f"Missing or ambiguous {ticker} FY{year} {metric}")

        report = reports[0]

        for issue in self.data.get("issues", []):
            same_document = issue.get("document_id") == report["document_id"]
            same_scope = (
                issue.get("ticker") == ticker and issue.get("fiscal_year") == year
            )

            if issue.get("metric") == metric and (same_document or same_scope):
                raise FactError(
                    f"Unresolved source issue for {ticker} FY{year} {metric}"
                )

        self._validate_fact(matches[0], report, metric)
        return deepcopy(matches[0])

    def _calculate(self, metric, inputs, years=None):
        """Attach application scope only after arithmetic input validation.

        For growth and CAGR, fiscal_year identifies the ending year.
        The complete endpoint facts and year count remain in the result.
        """
        result = calculate(metric, inputs, years)

        return {
            **result,
            "ticker": inputs[-1]["ticker"],
            "fiscal_year": inputs[-1]["fiscal_year"],
            "corpus_version": self.data["corpus_version"],
            "validation_scope": VALIDATION_SCOPE,
        }

    def answer(self, route):
        self.validate_version()
        facts, calculations = [], []

        if not route.tickers or not route.years:
            raise FactError("Calculation requires explicit company/year scope")

        if route.metric not in METRICS and route.metric not in DERIVED:
            raise FactError("Unsupported financial metric")

        if route.operation and len(route.years) != 2:
            raise FactError("Growth/CAGR requires exactly two fiscal years")

        if route.operation and route.metric not in METRICS:
            raise FactError(
                "Growth of derived metrics is unsupported; compare them instead"
            )

        for ticker in route.tickers:
            for year in route.years:
                inputs = [
                    self.fact(ticker, year, metric)
                    for metric in DERIVED.get(route.metric, [route.metric])
                ]
                facts.extend(inputs)

                if route.metric in DERIVED:
                    calculations.append(self._calculate(route.metric, inputs))

            if route.operation:
                inputs = [self.fact(ticker, year, route.metric) for year in route.years]
                calculations.append(
                    self._calculate(
                        route.operation,
                        inputs,
                        route.years[-1] - route.years[0],
                    )
                )

        return facts, calculations

    def analytics(self):
        if (
            not self.load_error
            and not self.manifest
            and not self.data["facts"]
            and not self.data.get("corpus_version")
            and self.inline_data is None
            and self.reconciliation_data is None
        ):
            return {
                "status": "not_initialized",
                "rows": [],
                "issues": deepcopy(self.data.get("issues", [])),
                "corpus_version": None,
                "validation_scope": VALIDATION_SCOPE,
            }

        self.validate_version()
        rows = []
        issues = deepcopy(self.data.get("issues", []))

        for report in self.manifest:
            ticker = report["ticker"]
            year = report["fiscal_year"]
            row = {
                "ticker": ticker,
                "fiscal_year": year,
                "values": {},
                "evidence": [],
                "calculations": [],
                "unavailable_metrics": {},
            }

            for metric in METRICS:
                try:
                    fact = self.fact(ticker, year, metric)
                    row["values"][metric] = fact["value"]
                    row["evidence"].append(fact)
                except FactError as exc:
                    row["unavailable_metrics"][metric] = str(exc)

            for metric, inputs in DERIVED.items():
                try:
                    calculation = self._calculate(
                        metric,
                        [self.fact(ticker, year, name) for name in inputs],
                    )
                    row["values"][metric] = calculation["value"]
                    row["calculations"].append(calculation)
                except FactError as exc:
                    row["unavailable_metrics"][metric] = str(exc)

            for metric, base in (
                ("revenue_yoy_growth", year - 1),
                ("revenue_cagr", 2022),
            ):
                if base >= year:
                    continue

                try:
                    calculation = self._calculate(
                        "cagr" if metric.endswith("cagr") else "growth",
                        [
                            self.fact(ticker, base, "revenue"),
                            self.fact(ticker, year, "revenue"),
                        ],
                        year - base,
                    )
                    row["values"][metric] = calculation["value"]
                    row["calculations"].append(calculation)
                except FactError as exc:
                    row["unavailable_metrics"][metric] = str(exc)

            rows.append(row)

        return {
            "status": (
                "available_with_gaps"
                if any(row["unavailable_metrics"] for row in rows)
                else "available"
            ),
            "rows": rows,
            "issues": issues,
            "corpus_version": self.data["corpus_version"],
            "validation_scope": VALIDATION_SCOPE,
        }
