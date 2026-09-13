import pytest

from ingestion.chunk import chunk_blocks


class WordTokenizer:
    def encode(self, text, **kwargs):
        return text.split()


def block(text, location, **changes):
    return {
        "text": text,
        "section": "Item 1",
        "subsection": None,
        "location": location,
        "page": None,
        "table": False,
        **changes,
    }


def metadata():
    return {"document_id": "synthetic-document"}


def test_preserves_original_punctuation_and_whitespace():
    source = "Revenue:  synthetic text.\nSecond line — unchanged."

    chunks = chunk_blocks(
        [block(source, "block-a")],
        metadata(),
        WordTokenizer(),
        100,
        10,
    )

    assert len(chunks) == 1
    assert chunks[0]["text"] == source
    assert chunks[0]["source_spans"] == [
        {
            "location": "block-a",
            "character_start": 0,
            "character_end": len(source),
            "page": None,
            "table": False,
        }
    ]


def test_all_contributing_block_locations_are_preserved():
    sources = [
        block("one two three", "block-a"),
        block("four five six", "block-b"),
        block("seven eight nine", "block-c"),
    ]

    chunks = chunk_blocks(
        sources,
        metadata(),
        WordTokenizer(),
        7,
        4,
    )

    assert len(chunks) >= 2

    locations = {span["location"] for span in chunks[1]["source_spans"]}

    assert "block-b" in locations
    assert "block-c" in locations


def test_exact_size_does_not_emit_overlap_only_tail():
    chunks = chunk_blocks(
        [block("one two three four five", "block-a")],
        metadata(),
        WordTokenizer(),
        5,
        2,
    )

    assert len(chunks) == 1


def test_chunks_stay_within_budget():
    source = " ".join(f"word{index}" for index in range(60))

    chunks = chunk_blocks(
        [block(source, "block-a")],
        metadata(),
        WordTokenizer(),
        10,
        2,
    )

    assert all(chunk["token_count"] <= 10 for chunk in chunks)
    assert len({chunk["chunk_id"] for chunk in chunks}) == len(chunks)
    assert "word59" in chunks[-1]["text"]


def test_section_page_and_table_boundaries_are_not_crossed():
    sources = [
        block("first section", "a"),
        block("second section", "b", section="Item 2"),
        block("PDF page one", "c", section="PDF", page=1),
        block("PDF page two", "d", section="PDF", page=2),
        block("Revenue | 100\nIncome | 20", "e", table=True),
        block("Narrative after table", "f"),
    ]

    chunks = chunk_blocks(
        sources,
        metadata(),
        WordTokenizer(),
        100,
        10,
    )

    assert len(chunks) == 6
    assert chunks[2]["page"] == 1
    assert chunks[3]["page"] == 2
    assert chunks[4]["table"] is True
    assert chunks[4]["source_spans"][0]["table_row_start"] == 1
    assert chunks[4]["source_spans"][0]["table_row_end"] == 2


def test_source_spans_refer_to_actual_block_substrings():
    sources = [
        block("alpha beta gamma delta", "a"),
        block("epsilon zeta eta theta", "b"),
    ]
    by_location = {item["location"]: item["text"] for item in sources}

    chunks = chunk_blocks(
        sources,
        metadata(),
        WordTokenizer(),
        5,
        2,
    )

    for chunk in chunks:
        for span in chunk["source_spans"]:
            original = by_location[span["location"]]
            excerpt = original[span["character_start"] : span["character_end"]]
            assert excerpt in chunk["text"]


@pytest.mark.parametrize("size,overlap", [(0, 0), (5, 5), (5, -1)])
def test_invalid_budgets_rejected(size, overlap):
    with pytest.raises(ValueError):
        chunk_blocks(
            [block("source", "a")],
            metadata(),
            WordTokenizer(),
            size,
            overlap,
        )
