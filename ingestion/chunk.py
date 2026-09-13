"""Source-preserving, tokenizer-budgeted chunks.

Chunk text is sliced from extracted source text, not reconstructed by
tokenizer.decode(). Every contributing block retains its character span.

Chunks do not cross section, subsection, PDF-page, or table boundaries.
Overlap is bounded by the configured token count. A terminal overlap-only
chunk is never emitted.

The source is the normalized extraction output, not raw HTML byte offsets.
"""

import re

from core.storage import digest

CHUNK_POLICY_VERSION = "source-spans-v2"


def _count(tokenizer, text):
    return len(tokenizer.encode(text, add_special_tokens=False))


def _prefix_end(text, start, tokenizer, budget):
    """Find a nonempty source prefix that fits the actual tokenizer."""
    remaining = text[start:]

    if _count(tokenizer, remaining) <= budget:
        return len(text)

    low, high = start + 1, len(text)
    best = start

    while low <= high:
        middle = (low + high) // 2

        if _count(tokenizer, text[start:middle]) <= budget:
            best = middle
            low = middle + 1
        else:
            high = middle - 1

    if best == start:
        raise ValueError("A source character exceeds the chunk token budget")

    # Prefer a nearby whitespace boundary instead of splitting a word.
    # A candidate boundary is rechecked because token counts are not
    # mathematically monotonic under every possible tokenizer.
    minimum = start + max(1, (best - start) // 2)
    boundaries = [
        start + match.end()
        for match in re.finditer(r"\s+", text[start:best])
        if start + match.end() >= minimum
    ]

    for boundary in reversed(boundaries):
        if _count(tokenizer, text[start:boundary]) <= budget:
            return boundary

    if _count(tokenizer, text[start:best]) > budget:
        raise ValueError("Unable to satisfy chunk tokenizer budget")

    return best


def _overlap_start(text, start, end, tokenizer, budget):
    if budget == 0:
        return end

    low, high = start + 1, end
    best = end

    while low <= high:
        middle = (low + high) // 2

        if _count(tokenizer, text[middle:end]) <= budget:
            best = middle
            high = middle - 1
        else:
            low = middle + 1

    # Prefer starting at a word boundary when that still fits.
    if best > 0 and best < end:
        if not text[best - 1].isspace() and not text[best].isspace():
            match = re.search(r"\s+", text[best:end])

            if match:
                best += match.end()
            else:
                best = end

    if _count(tokenizer, text[best:end]) > budget:
        return end

    return best


def _scope(block):
    is_table = bool(block.get("table"))

    return (
        block["section"],
        block.get("subsection"),
        block.get("page"),
        block["location"] if is_table else None,
        is_table,
    )


def _source_spans(records, start, end):
    spans = []

    for record in records:
        left = max(start, record["start"])
        right = min(end, record["end"])

        if left >= right:
            continue

        local_start = left - record["start"]
        local_end = right - record["start"]
        block = record["block"]

        span = {
            "location": block["location"],
            "character_start": local_start,
            "character_end": local_end,
            "page": block.get("page"),
            "table": bool(block.get("table")),
        }

        if block.get("table"):
            source = block["text"]
            span["table_row_start"] = source[:local_start].count("\n") + 1
            span["table_row_end"] = (
                source[: max(local_start, local_end - 1)].count("\n") + 1
            )
            span["starts_mid_row"] = local_start > 0 and source[local_start - 1] != "\n"
            span["ends_mid_row"] = (
                local_end < len(source) and source[local_end - 1] != "\n"
            )

        spans.append(span)

    return spans


def _chunk_group(group, metadata, tokenizer, size, overlap):
    records = []
    parts = []
    cursor = 0

    for block in group:
        if parts:
            parts.append("\n")
            cursor += 1

        text = block["text"]
        records.append(
            {
                "block": block,
                "start": cursor,
                "end": cursor + len(text),
            }
        )
        parts.append(text)
        cursor += len(text)

    source = "".join(parts)
    first = group[0]
    chunks = []
    start = 0

    while start < len(source):
        end = _prefix_end(source, start, tokenizer, size)
        text = source[start:end]
        spans = _source_spans(records, start, end)

        if text.strip() and spans:
            locations = list(dict.fromkeys(span["location"] for span in spans))
            identity = {
                "policy": CHUNK_POLICY_VERSION,
                "document_id": metadata["document_id"],
                "section": first["section"],
                "subsection": first.get("subsection"),
                "page": first.get("page"),
                "source_spans": spans,
                "text": text,
            }

            chunks.append(
                {
                    **metadata,
                    "text": text,
                    "section": first["section"],
                    "subsection": first.get("subsection"),
                    "page": first.get("page"),
                    "table": bool(first.get("table")),
                    "location": ", ".join(locations),
                    "source_spans": spans,
                    "chunk_id": digest(identity)[:24],
                    "chunk_policy_version": CHUNK_POLICY_VERSION,
                    "token_count": _count(tokenizer, text),
                    "overlap_policy": "Up to configured tokens of source text",
                }
            )

        if end == len(source):
            break

        next_start = _overlap_start(
            source,
            start,
            end,
            tokenizer,
            overlap,
        )

        if next_start <= start:
            raise ValueError("Chunking did not advance through source text")

        start = next_start

    return chunks


def chunk_blocks(blocks, metadata, tokenizer, size=700, overlap=100):
    if type(size) is not int or type(overlap) is not int or not 0 <= overlap < size:
        raise ValueError("Invalid chunk size or overlap")

    if not isinstance(metadata, dict) or not metadata.get("document_id"):
        raise ValueError("Chunking requires an application document identifier")

    chunks = []
    group = []
    scope = None

    for block in blocks:
        if (
            not isinstance(block, dict)
            or not isinstance(block.get("text"), str)
            or not isinstance(block.get("section"), str)
            or not isinstance(block.get("location"), str)
            or not block["location"]
        ):
            raise ValueError("Extracted block lacks text or source provenance")

        if not block["text"].strip():
            continue

        current = _scope(block)

        if group and current != scope:
            chunks.extend(_chunk_group(group, metadata, tokenizer, size, overlap))
            group = []

        scope = current
        group.append(block)

    if group:
        chunks.extend(_chunk_group(group, metadata, tokenizer, size, overlap))

    identifiers = [chunk["chunk_id"] for chunk in chunks]

    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Duplicate chunk identity; inspect source locations")

    return chunks
