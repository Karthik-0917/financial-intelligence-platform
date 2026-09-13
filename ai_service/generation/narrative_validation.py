"""Conservative screening of generated prose, not semantic verification.

Financial values must be rendered by the existing application financial
path. Neither citations nor matching source numbers exempt generated prose.
Reference recognition covers bounded identifiers only. False negatives and
false positives remain possible; accepted narrative is semantics-unverified.
No source text is copied, rewritten, fetched, or used to authorize a quantity.
"""

import re
import unicodedata
from enum import Enum


class NarrativeCategory(str, Enum):
    QUALITATIVE_OR_REFERENCE = "qualitative_or_reference"
    QUANTITATIVE = "quantitative"
    AMBIGUOUS = "ambiguous"
    PROHIBITED_EXTERNAL_REFERENCE = "prohibited_external_reference"


POLICY_VERSION = "conservative-narrative-v1"

EXTERNAL = re.compile(
    r"\b[a-z][a-z0-9+.-]*\s*:\s*//|(?<!\w)//\s*[\w[]|"
    r"\bwww\s*\.|\]\s*\([^)]*\)|"
    r"\b(?:[a-z0-9-]+\.)+(?:com|org|net|gov|edu|io|co|invalid)\b"
)
QUANTITY = re.compile(
    r"[%‰‱]|\b(?:percent(?:age)?s?|percentage\s+points?|basis\s+points?|bps|"
    r"dollars?|euros?|rupees?|usd|eur|inr|gbp|jpy|"
    r"hundred|thousand|million|billion|trillion|"
    r"doubled?|doubling|tripled?|tripling|halved?|halving|"
    r"twice|thrice|\w+fold|half|halves|quarter|quarters|"
    r"thirds|fourths|ratio|ratios)\b|"
    r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|\d+(?:\.\d+)?)\s+times\b|"
    r"\d\s*[:/]\s*\d|\d\s*[–—]\s*\d"
)
NUMBER_WORD = re.compile(
    r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
    r"eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|"
    r"eighty|ninety|dozen|dozens)\b"
)
FINANCIAL = re.compile(
    r"\b(?:revenue|revenues|sales|income|profit|profits|margin|margins|"
    r"cash|assets|liabilities|equity|eps|earnings|capex|"
    r"capital\s+expenditure|free\s+cash\s+flow)\b"
)
COMPARISON = re.compile(
    r"\b(?:highest|lowest|largest|smallest|record[ -]high|record[ -]low|"
    r"majority|minority|more\s+than|less\s+than|greater\s+than|"
    r"exceeded|outpaced|outstripped)\b"
)
MEASURED_CHANGE = re.compile(
    r"\b(?:increased|decreased|grew|rose|fell|declined|"
    r"higher|lower|growth|increase|decrease)\b"
)
REFERENCE = re.compile(
    r"(?<![\w.])(?:"
    r"(?P<fy>fy\s*(?:19|20)\d{2})(?!\w)|"
    r"(?P<year>(?:19|20)\d{2})(?=\s+(?:form\s+)?10-k\b)|"
    r"(?P<form>(?:form\s+)?10-k)(?![\w-])|"
    r"(?P<item>items?\s+\d{1,2}[a-z]?)(?![\w-]|\.\d)|"
    r"(?P<covid>covid-19)(?![\w-])"
    r")"
)
TEMPORAL = re.compile(
    r"\b(?:in|during|for|since|through|between|and|to|"
    r"fiscal\s+year|fiscal\s+years)\s+((?:19|20)\d{2})(?![\w.])"
)


def classify_narrative(text, *, allowed_years=()):
    """Classify prose without altering it or accepting model-supplied labels.

    allowed_years must come from application scope and cited evidence metadata,
    never from numbers found in document text. Matching a year is necessary
    but not sufficient: its syntactic context must also be a reference.
    """
    if not isinstance(text, str) or not text.strip():
        return NarrativeCategory.AMBIGUOUS
    if any(unicodedata.category(char) in {"Cf", "Cs"} for char in text):
        return NarrativeCategory.AMBIGUOUS
    if any(unicodedata.category(char) == "Cc" and char not in "\n\r\t" for char in text):
        return NarrativeCategory.AMBIGUOUS

    if any(char.isnumeric() and not char.isdecimal() for char in text):
        return NarrativeCategory.AMBIGUOUS

    analysis = unicodedata.normalize("NFKC", text).casefold()
    analysis = re.sub(r"\s+", " ", analysis)
    if EXTERNAL.search(analysis):
        return NarrativeCategory.PROHIBITED_EXTERNAL_REFERENCE
    if any(unicodedata.category(char) == "Sc" for char in analysis):
        return NarrativeCategory.QUANTITATIVE
    if QUANTITY.search(analysis):
        return NarrativeCategory.QUANTITATIVE
    if NUMBER_WORD.search(analysis):
        return NarrativeCategory.AMBIGUOUS
    if COMPARISON.search(analysis):
        return NarrativeCategory.AMBIGUOUS

    # Unmeasured financial changes are ambiguous even when modal or split
    # across sentences. Risk language such as "may affect revenue" remains
    # eligible; this is deliberately not a general grammatical classifier.
    if FINANCIAL.search(analysis) and MEASURED_CHANGE.search(analysis):
        return NarrativeCategory.AMBIGUOUS

    years = {year for year in allowed_years if type(year) is int}
    spans = []
    for match in REFERENCE.finditer(analysis):
        if match.lastgroup in {"fy", "year"}:
            year = int(re.search(r"\d{4}", match.group()).group())
            if year not in years:
                return NarrativeCategory.AMBIGUOUS
        spans.append(match.span())
    for match in TEMPORAL.finditer(analysis):
        if int(match.group(1)) not in years:
            return NarrativeCategory.AMBIGUOUS
        spans.append(match.span(1))

    # Account for numeric characters by position; never remove digits from
    # claim text. Unexplained identifiers, quantities and notation fail closed.
    for position, char in enumerate(analysis):
        if char.isnumeric() and not any(start <= position < end for start, end in spans):
            return NarrativeCategory.AMBIGUOUS
    return NarrativeCategory.QUALITATIVE_OR_REFERENCE


def validate_narrative(synthesis, registry, requested_years):
    """Reject the whole synthesis on any unsafe/ambiguous generated claim.

    Call after validate_citations. No financial record can exempt prose from
    this check. Evidence URLs are metadata and are deliberately not screened.
    """
    combined = " ".join(claim.text for claim in synthesis.claims)
    combined = unicodedata.normalize("NFKC", combined).casefold()
    if FINANCIAL.search(combined) and MEASURED_CHANGE.search(combined):
        raise ValueError(
            "Narrative contained numeric claims or URLs; use application facts"
        )
    for claim in synthesis.claims:
        cited_years = {
            registry[identifier].get("fiscal_year")
            for identifier in claim.citation_ids
            if identifier in registry
        }
        category = classify_narrative(
            claim.text,
            allowed_years=set(requested_years) & cited_years,
        )
        if category != NarrativeCategory.QUALITATIVE_OR_REFERENCE:
            # Keep the existing safe public reason and rejection-trace flow.
            raise ValueError(
                "Narrative contained numeric claims or URLs; use application facts"
            )