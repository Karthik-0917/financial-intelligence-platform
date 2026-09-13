"""Synthetic inline-XBRL fixtures, never actual financial evidence."""

from ingestion.inline_facts import extract_inline_facts


def filing(
    text="1,234",
    attributes='format="ixt:num-dot-decimal" scale="6"',
    extra="",
):
    return f"""
    <html
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
      xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
      xmlns:us-gaap="http://fasb.org/us-gaap/2024"
      xmlns:ixt="http://www.xbrl.org/inlineXBRL/transformation/2020-02-12"
      xmlns:fixture="urn:synthetic:fixture">
    <body>
      <xbrli:context id="annual">
        <xbrli:entity>
          <xbrli:identifier scheme="http://www.sec.gov/CIK">
            320193
          </xbrli:identifier>
        </xbrli:entity>
        <xbrli:period>
          <xbrli:startDate>2024-01-01</xbrli:startDate>
          <xbrli:endDate>2024-12-31</xbrli:endDate>
        </xbrli:period>
      </xbrli:context>
      <xbrli:unit id="usd">
        <xbrli:measure>iso4217:USD</xbrli:measure>
      </xbrli:unit>
      <p>
        <ix:nonFraction
          name="us-gaap:Revenues"
          contextRef="annual"
          unitRef="usd"
          decimals="-6"
          {attributes}
        >{text}</ix:nonFraction>
      </p>
      {extra}
    </body></html>
    """.encode()


def report():
    return {
        "document_id": "synthetic-document",
        "accession_number": "synthetic-accession",
        "source_url": "https://example.invalid/synthetic-filing",
    }


def observation(raw):
    result = extract_inline_facts(raw, report())
    assert len(result["observations"]) == 1
    return result["observations"][0]


def test_scale_and_context_preserved():
    result = extract_inline_facts(filing(), report())
    assert len(result["observations"]) == 1
    item = result["observations"][0]

    assert item["status"] == "parsed"
    assert item["normalized_value"] == "1234000000"
    assert item["raw_text"] == "1,234"
    assert item["scale"] == 6
    assert item["unit"] == "USD"
    assert item["context"]["cik"] == "0000320193"
    assert item["context"]["period_start"] == "2024-01-01"
    assert item["context"]["period_end"] == "2024-12-31"
    assert item["page"] is None
    assert item["location"].startswith("html-element-")
    assert result["reconciliation_status"] == "not_performed"


def test_negative_sign_is_applied_once():
    item = observation(
        filing(
            text="25",
            attributes='format="ixt:num-dot-decimal" sign="-"',
        )
    )

    assert item["status"] == "parsed"
    assert item["normalized_value"] == "-25"


def test_comma_decimal_transformation():
    item = observation(
        filing(
            text="1.234,50",
            attributes='format="ixt:num-comma-decimal"',
        )
    )

    assert item["status"] == "parsed"
    assert item["normalized_value"] == "1234.50"


def test_unknown_format_remains_unresolved():
    item = observation(filing(attributes='format="ixt:unsupported-format"'))

    assert item["status"] == "unresolved"
    assert item["normalized_value"] is None
    assert "transformation" in item["reason"]


def test_currency_or_parentheses_are_not_guessed():
    item = observation(filing(text="($123)", attributes='format="ixt:num-dot-decimal"'))

    assert item["status"] == "unresolved"


def test_double_negative_is_not_guessed():
    item = observation(filing(text="-25", attributes='sign="-"'))

    assert item["status"] == "unresolved"
    assert "double-negative" in item["reason"]


def test_duplicate_context_is_ambiguous():
    duplicate = """
    <xbrli:context id="annual">
      <xbrli:entity>
        <xbrli:identifier scheme="http://www.sec.gov/CIK">
          789019
        </xbrli:identifier>
      </xbrli:entity>
      <xbrli:period>
        <xbrli:instant>2024-12-31</xbrli:instant>
      </xbrli:period>
    </xbrli:context>
    """
    item = observation(filing(extra=duplicate))

    assert item["status"] == "unresolved"
    assert "context" in item["reason"]


def test_hidden_observation_is_marked_not_discarded():
    raw = filing().replace(
        b"<p>",
        b'<p style="display: none">',
    )
    item = observation(raw)

    assert item["hidden"] is True
    assert item["status"] == "parsed"


def test_missing_context_does_not_produce_a_number():
    raw = filing().replace(b'contextRef="annual"', b'contextRef="missing"')
    item = observation(raw)

    assert item["normalized_value"] is None
    assert item["status"] == "unresolved"


def test_dimensional_context_is_preserved_for_later_rejection():
    raw = filing().replace(
        b"</xbrli:entity>",
        b"""
        <xbrli:segment>
          <xbrldi:explicitMember dimension="fixture:BusinessAxis">
            fixture:SegmentMember
          </xbrldi:explicitMember>
        </xbrli:segment>
        </xbrli:entity>
        """,
    )
    item = observation(raw)

    assert item["status"] == "parsed"
    assert item["context"]["has_segment_or_scenario"] is True
    assert item["context"]["dimensions"][0]["dimension"] == "fixture:BusinessAxis"
