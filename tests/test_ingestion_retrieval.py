import pytest
from rank_bm25 import BM25Okapi

from ai_service.retrieval.hybrid import lexical, matches, rrf
from evaluation.metrics import retrieval_metrics
from ingestion.chunk import chunk_blocks
from ingestion.download_reports import SECClient
from ingestion.extract import extract_html, filing_identity, normalize


class Tokenizer:
    def encode(self, text, **kwargs):
        return text.split()

    def decode(self, tokens, **kwargs):
        return " ".join(tokens)


def test_normalize():
    assert normalize(" A\u00a0B\n C  ") == "A B C"


def test_extract_sections_tables():
    blocks = extract_html(
        b"<html><script>evil</script><div><p>Item 1A. Risk Factors</p><p>Supply risks.</p><table><tr><td>Revenue</td><td>100</td></tr></table></div></html>"
    )
    assert len(blocks) == 3
    assert blocks[1]["section"].startswith("Item 1A")
    assert blocks[2]["text"] == "Revenue | 100"
    assert blocks[0]["page"] is None
    assert "evil" not in str(blocks)


def test_dei():
    raw = b'<ix:nonNumeric name="dei:DocumentFiscalYearFocus">2024</ix:nonNumeric><ix:nonNumeric name="dei:DocumentPeriodEndDate">2024-09-28</ix:nonNumeric><ix:nonNumeric name="dei:DocumentType">10-K</ix:nonNumeric>'
    assert filing_identity(raw)["documentfiscalyearfocus"] == "2024"
    with pytest.raises(ValueError):
        filing_identity(b"<html>no DEI</html>")


def test_chunking(report):
    blocks = [
        dict(text=" ".join(str(i) for i in range(30)), section="A", location="a"),
        dict(text="new section here", section="B", location="b"),
    ]
    chunks = chunk_blocks(blocks, report, Tokenizer(), 10, 2)
    assert all(len(c["text"].split()) <= 10 for c in chunks)
    assert len({c["chunk_id"] for c in chunks}) == len(chunks)
    assert chunks[-1]["text"] == "new section here"
    assert chunks[0]["text"].split()[-2:] == chunks[1]["text"].split()[:2]


def test_sec_identity_required(settings):
    with pytest.raises(ValueError):
        SECClient(settings)


def test_rrf_deduplication():
    scores = dict(rrf([[1, 1, 2], [2, 3]], 60))
    assert scores[1] == 1 / 61
    assert scores[2] == 1 / 63 + 1 / 61
    assert len(scores) == 3
    assert rrf([]) == []


def test_filter():
    assert matches(
        dict(ticker="MSFT", fiscal_year=2024, filing_type="10-K"), ["MSFT"], [2024]
    )
    assert not matches(
        dict(ticker="AMZN", fiscal_year=2024, filing_type="10-K"), ["MSFT"], [2024]
    )


def test_bm25():
    tokens = [lexical(t) for t in ["revenue margin", "supply risk", "cloud computing"]]
    scores = BM25Okapi(tokens).get_scores(lexical("supply risk"))
    assert scores.argmax() == 1


def test_retrieval_metric_denominators():
    m = retrieval_metrics(["a", "b", "c"], ["b", "d"])
    assert m["recall_at_5"] == 0.5
    assert m["precision_at_5"] == 0.2
    assert m["mrr"] == 0.5
    assert retrieval_metrics([], []) is None


def test_manifest_rejects_partial_and_duplicates():
    from ingestion.validate import validate_manifest

    with pytest.raises(ValueError):
        validate_manifest([])
    with pytest.raises(ValueError):
        validate_manifest([{"ticker": "AAPL", "fiscal_year": 2024}] * 9)
