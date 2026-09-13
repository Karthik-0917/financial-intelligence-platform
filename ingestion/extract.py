import re
import unicodedata
from datetime import datetime

from bs4 import BeautifulSoup

SECTION = re.compile(r"^ITEM\s+(\d+[A-C]?)\s*[.\-–:]?\s*(.*)", re.IGNORECASE)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()


def filing_identity(raw: bytes) -> dict:
    soup = BeautifulSoup(raw, "lxml")
    wanted = {"documentfiscalyearfocus", "documentperiodenddate", "documenttype"}
    values = {}

    for tag in soup.find_all(attrs={"name": True}):
        key = str(tag.get("name")).split(":")[-1].lower()

        if key in wanted:
            values.setdefault(key, set()).add(normalize(tag.get_text(" ")))

    if any(len(values.get(key, set())) != 1 for key in wanted):
        raise ValueError("Missing or conflicting DEI filing identity")

    identity = {key: next(iter(value)) for key, value in values.items()}

    # Inline markup boundaries can introduce spaces around punctuation:
    # "September 28 , 2024". Normalize comma spacing only for the date
    # parser, without altering the source text or narrative extraction.
    period = re.sub(
        r"\s*,\s*",
        ", ",
        identity["documentperiodenddate"],
    )

    for pattern in ["%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%m/%d/%Y"]:
        try:
            identity["documentperiodenddate"] = (
                datetime.strptime(period, pattern).date().isoformat()
            )
            break
        except ValueError:
            continue
    else:
        raise ValueError("Unrecognized DEI period-end date format")

    return identity


def _clean_for_section_detection(text: str) -> str:
    """Clean table-pipe artifacts for section heading detection.
    AMZN filings have headings inside tables like " | Item 1. | Business"
    or " |  | Item 1A. | Risk Factors". Strip leading pipes/spaces and
    collapse pipe separators to spaces for robust matching.
    """
    cleaned = text.strip()
    while cleaned.startswith("|"):
        cleaned = cleaned[1:].strip()
    cleaned = cleaned.replace("|", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def extract_html(raw: bytes) -> list[dict]:
    soup = BeautifulSoup(raw, "lxml")

    for tag in soup.find_all(
        ["script", "style", "nav", "ix:header", "header", "footer"]
    ):
        tag.decompose()

    for tag in soup.select('[style*="display:none"], [style*="display: none"]'):
        tag.decompose()

    blocks, section, previous = [], "Front matter", None

    # Emit each leaf paragraph/div and each table once, preserving table rows.
    for n, tag in enumerate(
        soup.find_all(["p", "div", "table", "h1", "h2", "h3", "h4"])
    ):
        if tag.find_parent("table") or (
            tag.name != "table"
            and tag.find(["p", "div", "table", "h1", "h2", "h3", "h4"])
        ):
            continue

        if tag.name == "table":
            text = "\n".join(
                " | ".join(
                    normalize(cell.get_text(" ")) for cell in row.find_all(["td", "th"])
                )
                for row in tag.find_all("tr")
            )
        else:
            text = normalize(tag.get_text(" "))

        if not text or text == previous:
            continue

        previous = text
        # Robust section detection: clean pipe artifacts, try match at start,
        # fallback to search inside short texts (handles AMZN table TOC)
        cleaned = _clean_for_section_detection(text)
        match = SECTION.match(cleaned)
        if not match and len(cleaned) < 300:
            search_match = SECTION.search(cleaned)
            if search_match and search_match.start() < 30:
                match = search_match
        if match and len(cleaned) < 250:
            title = match.group(2).strip()
            title = title.lstrip("| ").strip()
            if title and len(title) < 120:
                section = f"Item {match.group(1).upper()} — {title}"
            else:
                section = f"Item {match.group(1).upper()} — "

        blocks.append(
            {
                "text": text,
                "section": section,
                "subsection": None,
                "page": None,
                "location": f"html-block-{n}",
                "table": tag.name == "table",
            }
        )

    if not blocks:
        raise ValueError("No extractable filing text")

    return blocks


def extract_pdf(raw: bytes) -> list[dict]:
    import fitz

    with fitz.open(stream=raw, filetype="pdf") as doc:
        return [
            {
                "text": normalize(page.get_text()),
                "page": i + 1,
                "location": f"pdf-page-{i + 1}",
                "section": "PDF page",
                "subsection": None,
                "table": False,
            }
            for i, page in enumerate(doc)
            if page.get_text().strip()
        ]
