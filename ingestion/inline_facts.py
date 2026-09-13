"""Offline, namespace-aware extraction of inline-XBRL observations.

Observations are reconciliation inputs, not authoritative answers.

Supported:
- Inline XBRL 2008 and 2013 namespace identities.
- XBRL instance contexts and simple USD / shares units.
- Standard dot-decimal and comma-decimal transformations.
- Untransformed finite decimal values, explicit sign, and bounded scale.

Unsupported or ambiguous presentations remain unresolved. No source value
is inferred from parentheses, dash marks, fractions, or continuations.

HTML element ordinals identify parsed source locations, not page numbers
or application citation IDs.
"""

import re
from datetime import date
from decimal import Decimal, DecimalException, localcontext

from bs4 import BeautifulSoup

from core.storage import sha256_bytes
from ingestion.extract import normalize

INLINE_EXTRACTION_VERSION = "inline-numeric-v2"

IX_NAMESPACES = {
    "http://www.xbrl.org/2008/inlineXBRL",
    "http://www.xbrl.org/2013/inlineXBRL",
}
XBRLI_NAMESPACE = "http://www.xbrl.org/2003/instance"
XBRLDI_NAMESPACE = "http://xbrl.org/2006/xbrldi"
XSI_NAMESPACE = "http://www.w3.org/2001/XMLSchema-instance"
ISO4217_NAMESPACE = "http://www.xbrl.org/2003/iso4217"

TRANSFORMATION_NAMESPACES = {
    "http://www.xbrl.org/inlineXBRL/transformation/2010-04-20",
    "http://www.xbrl.org/inlineXBRL/transformation/2011-07-31",
    "http://www.xbrl.org/inlineXBRL/transformation/2015-02-26",
    "http://www.xbrl.org/inlineXBRL/transformation/2020-02-12",
    "http://www.xbrl.org/inlineXBRL/transformation/2022-02-16",
}

US_GAAP_NAMESPACE = re.compile(r"https?://fasb\.org/us-gaap/\d{4}(?:-\d{2}-\d{2})?")

DOT_FORMATS = {"numdotdecimal", "num-dot-decimal"}
COMMA_FORMATS = {"numcommadecimal", "num-comma-decimal"}

# Grouping separators must occur in consistent groups of three.
DOT_NUMBER = re.compile(r"(?:\d+|\d{1,3}(?:,\d{3})+|\d{1,3}(?: \d{3})+)(?:\.\d+)?")
COMMA_NUMBER = re.compile(r"(?:\d+|\d{1,3}(?:\.\d{3})+|\d{1,3}(?: \d{3})+)(?:,\d+)?")
PLAIN_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)")
QNAME = re.compile(
    r"(?:(?P<prefix>[A-Za-z_][A-Za-z0-9_.-]*):)?" r"(?P<local>[A-Za-z_][A-Za-z0-9_.-]*)"
)


def _local(tag):
    return str(tag.name).split(":")[-1].lower()


def _namespace(tag, prefix):
    """Resolve a namespace declaration in the parsed ancestor scope.

    BeautifulSoup's HTML parser lowercases attribute names. Namespace
    lookup therefore follows that parsed representation. If conflicting
    declaration spellings collapse during HTML parsing, this parser is not
    a substitute for XML schema validation.
    """
    attribute = f"xmlns:{prefix.lower()}" if prefix else "xmlns"
    current = tag

    while current is not None and getattr(current, "name", None):
        if current.has_attr(attribute):
            value = current.get(attribute)

            if not isinstance(value, str) or not value.strip():
                return None

            return value.strip()

        current = current.parent

    return None


def _qname(tag, value):
    if not isinstance(value, str):
        raise ValueError("Missing QName")

    match = QNAME.fullmatch(value.strip())

    if not match:
        raise ValueError("Malformed QName")

    namespace = _namespace(tag, match.group("prefix"))

    if namespace is None:
        raise ValueError("QName has no declared namespace")

    return namespace, match.group("local")


def _element_namespace(tag):
    name = str(tag.name)

    if ":" in name:
        prefix = name.split(":", 1)[0]
    else:
        prefix = None

    return _namespace(tag, prefix)


def _is_element(tag, namespace, local_name):
    return _local(tag) == local_name and _element_namespace(tag) == namespace


def _children(tag, local_name, namespace=XBRLI_NAMESPACE):
    return [
        child
        for child in tag.find_all(True)
        if _is_element(child, namespace, local_name)
    ]


def _one_text(tag, local_name):
    values = _children(tag, local_name)

    if len(values) != 1:
        raise ValueError(f"Expected one {local_name}")

    return normalize(values[0].get_text(" ", strip=True))


def _parse_context(tag):
    identifiers = _children(tag, "identifier")

    if len(identifiers) != 1:
        raise ValueError("Context requires one entity identifier")

    identifier = identifiers[0]
    scheme = str(identifier.get("scheme", "")).rstrip("/").lower()

    if scheme not in {
        "http://www.sec.gov/cik",
        "https://www.sec.gov/cik",
    }:
        raise ValueError("Unsupported context entity identifier scheme")

    cik = normalize(identifier.get_text())

    if not re.fullmatch(r"\d{1,10}", cik) or int(cik) <= 0:
        raise ValueError("Invalid context CIK")

    instants = _children(tag, "instant")
    starts = _children(tag, "startdate")
    ends = _children(tag, "enddate")

    if len(instants) == 1 and not starts and not ends:
        period_start = None
        period_end = date.fromisoformat(normalize(instants[0].get_text())).isoformat()
        kind = "instant"
    elif not instants and len(starts) == 1 and len(ends) == 1:
        period_start = date.fromisoformat(normalize(starts[0].get_text())).isoformat()
        period_end = date.fromisoformat(normalize(ends[0].get_text())).isoformat()

        if period_start > period_end:
            raise ValueError("Reversed inline context period")

        kind = "duration"
    else:
        raise ValueError("Unsupported context period")

    dimensions = [
        {
            "dimension": member.get("dimension"),
            "value": normalize(member.get_text(" ", strip=True)),
            "kind": _local(member),
        }
        for member in tag.find_all(True)
        if (
            _element_namespace(member) == XBRLDI_NAMESPACE
            and _local(member) in {"explicitmember", "typedmember"}
        )
    ]

    return {
        "cik": cik.zfill(10),
        "period_start": period_start,
        "period_end": period_end,
        "kind": kind,
        "dimensions": dimensions,
        "has_segment_or_scenario": bool(
            _children(tag, "segment") or _children(tag, "scenario")
        ),
    }


def _measure(tag):
    measures = _children(tag, "measure")

    if len(measures) != 1:
        raise ValueError("Expected one measure")

    return _qname(
        measures[0],
        normalize(measures[0].get_text(" ", strip=True)),
    )


def _parse_unit(tag):
    divisions = _children(tag, "divide")

    if divisions:
        if len(divisions) != 1:
            raise ValueError("Ambiguous divided unit")

        numerators = _children(divisions[0], "unitnumerator")
        denominators = _children(divisions[0], "unitdenominator")

        if (
            len(numerators) != 1
            or len(denominators) != 1
            or len(_children(tag, "measure")) != 2
        ):
            raise ValueError("Invalid divided unit")

        numerator = _measure(numerators[0])
        denominator = _measure(denominators[0])

        if numerator == (
            ISO4217_NAMESPACE,
            "USD",
        ) and denominator == (
            XBRLI_NAMESPACE,
            "shares",
        ):
            return "USD/shares"

        raise ValueError("Unsupported divided unit")

    measure = _measure(tag)

    if measure == (ISO4217_NAMESPACE, "USD"):
        return "USD"

    if measure == (XBRLI_NAMESPACE, "shares"):
        return "shares"

    raise ValueError("Unsupported inline unit")


def _numeric_value(raw_text, attributes):
    """Parse only presentations explicitly supported by this extractor.

    The caller must validate the namespace of a supplied format QName
    before invoking this function.
    """
    text = normalize(raw_text)

    if not text or len(text) > 128:
        raise ValueError("Empty or oversized inline numeric text")

    format_name = attributes.get("format", "").split(":")[-1]

    if format_name in DOT_FORMATS:
        if not DOT_NUMBER.fullmatch(text):
            raise ValueError("Unsupported dot-decimal numeric presentation")

        number_text = text.replace(",", "").replace(" ", "")
    elif format_name in COMMA_FORMATS:
        if not COMMA_NUMBER.fullmatch(text):
            raise ValueError("Unsupported comma-decimal numeric presentation")

        number_text = text.replace(".", "").replace(" ", "").replace(",", ".")
    elif not format_name:
        if not PLAIN_NUMBER.fullmatch(text):
            raise ValueError("Unsupported untransformed numeric presentation")

        number_text = text
    else:
        raise ValueError("Unsupported inline numeric transformation")

    scale_text = attributes.get("scale", "0")

    if not re.fullmatch(r"[+-]?\d{1,2}", scale_text):
        raise ValueError("Invalid inline numeric scale")

    scale = int(scale_text)

    if not -18 <= scale <= 18:
        raise ValueError("Inline numeric scale exceeds supported bounds")

    sign = attributes.get("sign", "")

    if sign not in {"", "-"}:
        raise ValueError("Unsupported inline numeric sign")

    if sign == "-" and number_text.startswith("-"):
        raise ValueError("Ambiguous double-negative inline presentation")

    try:
        with localcontext() as context:
            context.prec = 180
            value = Decimal(number_text) * (Decimal(10) ** scale)

            if sign == "-":
                value = -value

            if not value.is_finite():
                raise ValueError("Non-finite inline value")

            return format(value, "f"), scale
    except DecimalException:
        raise ValueError("Invalid inline numeric value") from None


def _hidden(tag):
    """Detect explicit inline/HTML hiding, not computed browser CSS."""
    current = tag

    while current is not None and getattr(current, "name", None):
        inline_hidden = _element_namespace(current) in IX_NAMESPACES and _local(
            current
        ) in {"hidden", "header"}
        style = str(current.get("style", ""))

        if (
            inline_hidden
            or current.has_attr("hidden")
            or re.search(
                r"(?:display\s*:\s*none|visibility\s*:\s*(?:hidden|collapse))",
                style,
                re.IGNORECASE,
            )
        ):
            return True

        current = current.parent

    return False


def _nil_value(tag):
    values = []

    for attribute, value in tag.attrs.items():
        if ":" not in attribute:
            continue

        prefix, local_name = attribute.split(":", 1)

        if local_name.lower() == "nil" and _namespace(tag, prefix) == XSI_NAMESPACE:
            values.append(str(value).strip())

    if len(values) > 1:
        raise ValueError("Ambiguous inline nil attributes")

    if not values:
        return False

    if values[0] in {"true", "1"}:
        return True

    if values[0] in {"false", "0"}:
        return False

    raise ValueError("Invalid inline nil attribute")


def _concept(tag, observation):
    namespace, local_name = _qname(tag, observation["source_concept"])
    observation["concept_namespace"] = namespace
    observation["concept_local_name"] = local_name

    if not US_GAAP_NAMESPACE.fullmatch(namespace):
        raise ValueError("Unsupported financial concept namespace")

    # Application comparison uses Company Facts' taxonomy key. The
    # original QName and exact namespace URI remain in the observation.
    observation["concept"] = f"us-gaap:{local_name}"


def _validate_format(tag, attributes, observation):
    value = attributes.get("format")

    if value is None:
        return

    namespace, local_name = _qname(tag, value)
    observation["format_namespace"] = namespace
    observation["format_local_name"] = local_name

    if namespace not in TRANSFORMATION_NAMESPACES:
        raise ValueError("Unsupported inline transformation namespace")

    if local_name not in DOT_FORMATS | COMMA_FORMATS:
        raise ValueError("Unsupported inline numeric transformation")


def extract_inline_facts(raw: bytes, report: dict) -> dict:
    if not isinstance(report, dict) or not report.get("document_id"):
        raise ValueError("Inline extraction requires application report metadata")

    soup = BeautifulSoup(raw, "lxml")
    elements = list(soup.find_all(True))
    contexts = {}
    units = {}
    issues = []
    observations = []

    for element in elements:
        kind = _local(element)

        if (
            kind not in {"context", "unit"}
            or _element_namespace(element) != XBRLI_NAMESPACE
        ):
            continue

        identifier = element.get("id")
        target = contexts if kind == "context" else units

        if not isinstance(identifier, str) or not identifier.strip():
            issues.append({"kind": kind, "reason": "missing_identifier"})
            continue

        if identifier in target:
            target[identifier] = None
            issues.append(
                {
                    "kind": kind,
                    "identifier": identifier,
                    "reason": "duplicate_identifier",
                }
            )
            continue

        try:
            target[identifier] = (
                _parse_context(element) if kind == "context" else _parse_unit(element)
            )
        except ValueError as exc:
            target[identifier] = None
            issues.append(
                {
                    "kind": kind,
                    "identifier": identifier,
                    "reason": str(exc),
                }
            )

    for ordinal, element in enumerate(elements):
        kind = _local(element)

        if (
            kind not in {"nonfraction", "fraction"}
            or _element_namespace(element) not in IX_NAMESPACES
        ):
            continue

        attributes = {
            key: str(element.get(key))
            for key in (
                "name",
                "contextref",
                "unitref",
                "format",
                "scale",
                "sign",
                "decimals",
                "id",
                "continuedat",
            )
            if element.get(key) is not None
        }

        # Preserve namespaced nil declarations using their source spelling.
        for key, value in element.attrs.items():
            if ":" in key and key.split(":", 1)[1].lower() == "nil":
                attributes[key] = str(value)

        context_ref = attributes.get("contextref")
        unit_ref = attributes.get("unitref")
        raw_text = element.get_text(" ", strip=True)

        observation = {
            "document_id": report["document_id"],
            "accession_number": report.get("accession_number"),
            "source_url": report.get("source_url"),
            "location": f"html-element-{ordinal}",
            "html_id": attributes.get("id"),
            "page": None,
            "source_concept": attributes.get("name"),
            "concept": attributes.get("name"),
            "context_ref": context_ref,
            "unit_ref": unit_ref,
            "raw_text": raw_text,
            "attributes": attributes,
            "hidden": _hidden(element),
            "visibility_scope": (
                "Explicit inline/HTML attributes only; "
                "computed stylesheet visibility is not audited"
            ),
            "status": "unresolved",
            "normalized_value": None,
        }

        # Keep independently valid scope even if numeric parsing fails.
        if context_ref in contexts and contexts[context_ref] is not None:
            observation["context"] = contexts[context_ref]

        if unit_ref in units and units[unit_ref] is not None:
            observation["unit"] = units[unit_ref]

        try:
            _concept(element, observation)

            if kind == "fraction":
                raise ValueError("Inline fractions are not supported")

            if _nil_value(element):
                raise ValueError("Inline fact is nil")

            if attributes.get("continuedat"):
                raise ValueError("Continued numeric facts are not supported")

            # Excluded/nested numeric content needs a dedicated text-value
            # algorithm. Do not concatenate it into a guessed number.
            if any(
                _element_namespace(child) in IX_NAMESPACES
                and _local(child) in {"exclude", "nonfraction", "fraction"}
                for child in element.find_all(True)
            ):
                raise ValueError("Nested or excluded numeric content unsupported")

            if "context" not in observation:
                raise ValueError("Inline fact has no unambiguous valid context")

            if "unit" not in observation:
                raise ValueError("Inline fact has no unambiguous valid unit")

            _validate_format(element, attributes, observation)
            value, scale = _numeric_value(raw_text, attributes)

            observation.update(
                status="parsed",
                normalized_value=value,
                scale=scale,
                validation_scope="Parsed observation; not reconciled",
            )
        except ValueError as exc:
            observation["reason"] = str(exc)

        observations.append(observation)

    return {
        "extraction_version": INLINE_EXTRACTION_VERSION,
        "document_id": report["document_id"],
        "content_sha256": sha256_bytes(raw),
        "observations": observations,
        "issues": issues,
        "parsed_count": sum(
            observation["status"] == "parsed" for observation in observations
        ),
        "unresolved_count": sum(
            observation["status"] != "parsed" for observation in observations
        ),
        "reconciliation_status": "not_performed",
    }
