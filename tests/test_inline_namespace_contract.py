"""Synthetic namespace and reconciliation regression tests.

The HTML and values below are invented test fixtures, not SEC filings.
These tests do not claim real-corpus coverage or browser CSS visibility.
"""

import pytest

from ai_service.financial.reconciliation import reconcile
from core.storage import sha256_bytes
from ingestion.inline_facts import (
    INLINE_EXTRACTION_VERSION,
    extract_inline_facts,
)


def document(
    *,
    text="1,000",
    format_name="t:num-dot-decimal",
    format_namespace=("http://www.xbrl.org/inlineXBRL/transformation/2020-02-12"),
    unit_namespace="http://www.xbrl.org/2003/iso4217",
    extra_attributes="",
    hidden=False,
    duplicate_context=False,
    end="2024-12-31",
    extra_fact="",
):
    context = f"""
    <i:context id="annual">
      <i:entity>
        <i:identifier scheme="http://www.sec.gov/CIK">320193</i:identifier>
      </i:entity>
      <i:period>
        <i:startDate>2024-01-01</i:startDate>
        <i:endDate>{end}</i:endDate>
      </i:period>
    </i:context>
    """
    format_attribute = f'format="{format_name}"' if format_name is not None else ""
    fact = f"""
    <f:nonFraction
        name="g:Revenues"
        contextRef="annual"
        unitRef="dollars"
        {format_attribute}
        {extra_attributes}>{text}</f:nonFraction>
    """

    if hidden:
        fact = f"<f:hidden>{fact}</f:hidden>"

    return f"""
    <html
      xmlns:f="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:i="http://www.xbrl.org/2003/instance"
      xmlns:c="{unit_namespace}"
      xmlns:g="http://fasb.org/us-gaap/2024"
      xmlns:t="{format_namespace}"
      xmlns:n="http://www.w3.org/2001/XMLSchema-instance">
      <body>
        <f:header>
          <f:resources>
            {context}
            {context if duplicate_context else ""}
            <i:unit id="dollars"><i:measure>c:USD</i:measure></i:unit>
          </f:resources>
        </f:header>
        <div>{fact}{extra_fact}</div>
      </body>
    </html>
    """.encode()


def extract(raw):
    return extract_inline_facts(
        raw,
        {
            "document_id": "synthetic-document",
            "accession_number": "synthetic-accession",
            "source_url": None,
        },
    )


def candidate(raw):
    return {
        "document_id": "synthetic-document",
        "accession_number": "synthetic-accession",
        "content_sha256": sha256_bytes(raw),
        "ticker": "AAPL",
        "cik": "0000320193",
        "fiscal_year": 2024,
        "metric": "revenue",
        "taxonomy": "us-gaap",
        "concept": "Revenues",
        "unit": "USD",
        "kind": "duration",
        "period_start": "2024-01-01",
        "period_end": "2024-12-31",
        "value": "1000",
        "original_fact": {"val": 1000},
        "source": None,
        "source_url": None,
    }


def test_alternate_prefixes_parse_and_reconcile():
    raw = document()
    inline = extract(raw)
    observation = inline["observations"][0]

    assert INLINE_EXTRACTION_VERSION == "inline-numeric-v2"
    assert inline["parsed_count"] == 1
    assert observation["source_concept"] == "g:Revenues"
    assert observation["concept"] == "us-gaap:Revenues"
    assert observation["concept_namespace"] == "http://fasb.org/us-gaap/2024"
    assert observation["normalized_value"] == "1000"
    assert observation["unit"] == "USD"
    assert observation["hidden"] is False
    assert observation["page"] is None
    assert reconcile(candidate(raw), inline)["status"] == "matched"


def test_unknown_transform_namespace_is_not_trusted():
    raw = document(format_namespace="urn:synthetic:unknown-transform")
    observation = extract(raw)["observations"][0]

    assert observation["status"] == "unresolved"
    assert observation["reason"] == "Unsupported inline transformation namespace"
    assert observation["context"]["period_end"] == "2024-12-31"
    assert observation["unit"] == "USD"


def test_unknown_currency_namespace_is_not_usd():
    raw = document(unit_namespace="urn:synthetic:not-iso4217")
    inline = extract(raw)

    assert inline["parsed_count"] == 0
    assert inline["observations"][0]["status"] == "unresolved"
    assert any(issue["kind"] == "unit" for issue in inline["issues"])


def test_hidden_alias_does_not_validate_visible_evidence():
    raw = document(hidden=True)
    inline = extract(raw)

    assert inline["observations"][0]["hidden"] is True
    assert reconcile(candidate(raw), inline)["status"] == "not_verified"


def test_duplicate_context_remains_unresolved():
    inline = extract(document(duplicate_context=True))

    assert inline["parsed_count"] == 0
    assert any(issue["reason"] == "duplicate_identifier" for issue in inline["issues"])


@pytest.mark.parametrize(
    ("text", "format_name", "expected"),
    [
        ("1,234.50", "t:num-dot-decimal", "1234.50"),
        ("1.234,50", "t:num-comma-decimal", "1234.50"),
        ("1 234.50", "t:num-dot-decimal", "1234.50"),
        ("1\u00a0234,50", "t:num-comma-decimal", "1234.50"),
        (".50", None, "0.50"),
        ("-25", None, "-25"),
    ],
)
def test_supported_numeric_presentations(text, format_name, expected):
    observation = extract(document(text=text, format_name=format_name))["observations"][
        0
    ]

    assert observation["status"] == "parsed"
    assert observation["normalized_value"] == expected


@pytest.mark.parametrize("text", ["1 2", "12,34", "(100)", "—", "1,234 567"])
def test_unsupported_presentations_are_not_guessed(text):
    observation = extract(document(text=text))["observations"][0]

    assert observation["status"] == "unresolved"
    assert observation["normalized_value"] is None


def test_explicit_scale_and_sign():
    observation = extract(document(text="2", extra_attributes='scale="3" sign="-"'))[
        "observations"
    ][0]

    assert observation["status"] == "parsed"
    assert observation["normalized_value"] == "-2000"
    assert observation["scale"] == 3


def test_nil_alias_is_detected():
    observation = extract(document(extra_attributes='n:nil="true"'))["observations"][0]

    assert observation["status"] == "unresolved"
    assert observation["reason"] == "Inline fact is nil"


def test_unsupported_numeric_continuation_is_explicit():
    observation = extract(
        document(extra_attributes='continuedAt="synthetic-continuation"')
    )["observations"][0]

    assert observation["status"] == "unresolved"
    assert observation["reason"] == "Continued numeric facts are not supported"


def test_valid_context_survives_numeric_failure():
    raw = document(text="unsupported", end="2023-12-31")
    observation = extract(raw)["observations"][0]

    # The period itself is syntactically valid but reversed here, so the
    # context must not be retained as valid scope.
    assert observation["status"] == "unresolved"
    assert "context" not in observation

    raw = document(text="unsupported")
    observation = extract(raw)["observations"][0]

    assert observation["status"] == "unresolved"
    assert observation["context"]["period_end"] == "2024-12-31"


def test_same_scope_conflict_preserves_both_values():
    extra = """
    <f:nonFraction name="g:Revenues"
      contextRef="annual" unitRef="dollars"
      format="t:num-dot-decimal">2,000</f:nonFraction>
    """
    raw = document(extra_fact=extra)
    result = reconcile(candidate(raw), extract(raw))

    assert result["status"] == "conflict"
    assert result["companyfacts_value"] == "1000"
    assert {
        observation["normalized_value"] for observation in result["filing_observations"]
    } == {"1000", "2000"}
