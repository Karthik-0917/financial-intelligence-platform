"""Persisted hybrid retrieval with explicit source and policy validation."""

import math
import re
import time

import numpy as np
from rank_bm25 import BM25Okapi

from ai_service.retrieval.contracts import (
    validate_chunks,
    validate_index_manifest,
)
from core.config import COMPANIES, YEARS
from core.storage import digest, read_json, sha256_bytes

BM25_STATE_FIELDS = {
    "k1",
    "b",
    "epsilon",
    "corpus_size",
    "avgdl",
    "doc_freqs",
    "idf",
    "doc_len",
    "average_idf",
    "tokenizer",
}


def lexical(text):
    return re.findall(r"[a-z0-9]+", text.lower())


# --- Small section-intent query expansion (supplement, not replace) ---
def _expand_query(original: str) -> str:
    """Preserve original query, supplement with section intent terms for retrieval.
    No hardcoded diagnostic questions, only general intent keywords.
    """
    lower = original.lower()
    expansions = []

    # Cybersecurity -> Item 1C
    if "cybersecurity" in lower or "cyber security" in lower:
        expansions.append("Item 1C Cybersecurity risk management")

    # Risk factors -> Item 1A
    if "risk factor" in lower:
        expansions.append("Item 1A Risk Factors")

    # Business description -> Item 1 Business (add more context terms)
    if "business description" in lower:
        expansions.append(
            "Item 1 Business Company Background products services operations"
        )

    # Cloud business -> Business + MD&A + cloud terms
    if "cloud" in lower and "business" in lower:
        expansions.append(
            "Item 1 Business Item 7 Management Discussion cloud services Azure AWS"
        )

    # Supply chain risks -> Risk Factors + supply chain
    if "supply chain" in lower:
        expansions.append(
            "Item 1A Risk Factors supply chain suppliers manufacturing outsourcing partners"
        )

    # Climate-related risks
    if "climate" in lower:
        expansions.append("Item 1A Risk Factors climate environmental sustainability")

    # Competition risks
    if "competition" in lower or "competitive" in lower:
        expansions.append("Item 1A Risk Factors competition competitive market")

    # Generic risk -> ensure Risk Factors present if not already
    if (
        "risk" in lower
        and "risk factor" not in lower
        and "Item 1A" not in " ".join(expansions)
    ):
        expansions.append("Item 1A Risk Factors")

    # Generic business -> boost Item 1 Business when business mentioned without other specific intents
    if "business" in lower and not any(
        k in lower
        for k in [
            "risk",
            "cybersecurity",
            "supply chain",
            "climate",
            "competition",
            "cloud",
        ]
    ):
        if "Item 1 Business" not in " ".join(expansions):
            expansions.append("Item 1 Business")

    if expansions:
        # Preserve original, supplement
        return original + " " + " ".join(expansions)
    return original


def _get_intents(lower_query: str):
    """Extract general intents for section relevance boosting."""
    intents = set()
    if "cybersecurity" in lower_query or "cyber security" in lower_query:
        intents.add("cybersecurity")
    if "risk factor" in lower_query:
        intents.add("risk_factors")
    elif "risk" in lower_query:
        intents.add("risk")
    if "business description" in lower_query:
        intents.add("business_description")
        intents.add("business")
    elif "business" in lower_query:
        intents.add("business")
    if "cloud" in lower_query and "business" in lower_query:
        intents.add("cloud_business")
    elif "cloud" in lower_query:
        intents.add("cloud")
    if "supply chain" in lower_query:
        intents.add("supply_chain")
    if "climate" in lower_query:
        intents.add("climate")
    if "competition" in lower_query or "competitive" in lower_query:
        intents.add("competition")
    return intents


def _section_relevance_boost(intents, section: str) -> float:
    """Small ranking preference, NOT hard filter. Returns additive boost."""
    if not section:
        return 0.0
    sec = section.lower()
    boost = 0.0

    # Risk factors intent -> boost Item 1A / Risk Factors (stronger after AMZN fix)
    if (
        "risk_factors" in intents
        or "risk" in intents
        or "supply_chain" in intents
        or "climate" in intents
        or "competition" in intents
    ):
        if "risk factor" in sec or "item 1a" in sec:
            boost += 0.25

    # Cybersecurity intent -> boost Item 1C
    if "cybersecurity" in intents:
        if "item 1c" in sec or "cybersecurity" in sec:
            boost += 0.30

    # Business description intent -> boost Item 1 Business (but not 1A/1B/1C) – increased
    if "business_description" in intents or "business" in intents:
        if "item 1" in sec and "business" in sec:
            # Ensure not Item 1A/1B/1C
            if "item 1a" not in sec and "item 1b" not in sec and "item 1c" not in sec:
                boost += 0.35
        elif sec.strip().startswith("item 1") and "business" in sec:
            boost += 0.25
        elif "item 1" in sec and sec.strip() in {
            "item 1",
            "item 1 —",
            "item 1 — business",
        }:
            boost += 0.20

    # Cloud business intent -> boost Business and MD&A (stronger)
    if "cloud_business" in intents or "cloud" in intents:
        if (
            "business" in sec
            and "item 1" in sec
            and "item 1a" not in sec
            and "item 1b" not in sec
            and "item 1c" not in sec
        ):
            boost += 0.25
        if (
            "item 7" in sec
            or "md&a" in sec
            or "management" in sec
            and "discussion" in sec
        ):
            boost += 0.20
        if "cloud" in sec:
            boost += 0.15

    # Supply chain intent already covered by risk_factors boost, but add extra
    if "supply_chain" in intents:
        if "supply chain" in sec or "supplier" in sec:
            boost += 0.10

    # Penalize obviously wrong sections as preference (stronger penalty)
    if "front matter" in sec or sec.strip() == "front matter":
        # Penalize front matter for risk/business intents, but keep as fallback
        if intents & {
            "risk_factors",
            "risk",
            "business_description",
            "cybersecurity",
            "cloud_business",
            "supply_chain",
            "climate",
            "competition",
            "business",
            "cloud",
        }:
            boost -= 0.35

    return boost


def _is_relevant_section_for_intent(intent, section_lower):
    """Check if section is relevant for intent."""
    if not section_lower:
        return False
    if intent in {"risk_factors", "risk", "supply_chain", "climate", "competition"}:
        return "risk factor" in section_lower or "item 1a" in section_lower
    if intent == "cybersecurity":
        return "item 1c" in section_lower or "cybersecurity" in section_lower
    if intent in {"business_description", "business"}:
        return (
            "item 1" in section_lower
            and "business" in section_lower
            and "item 1a" not in section_lower
            and "item 1b" not in section_lower
            and "item 1c" not in section_lower
        )
    if intent in {"cloud_business", "cloud"}:
        return (
            (
                "business" in section_lower
                and "item 1" in section_lower
                and "item 1a" not in section_lower
            )
            or "item 7" in section_lower
            or "md&a" in section_lower
            or "management" in section_lower
        )
    return False


def _is_wrong_section_for_intent(intent, section_lower):
    """Obviously wrong sections that should not be sole evidence when relevant exists."""
    if not section_lower:
        return False
    # Front matter is wrong for all our targeted intents when relevant exists
    if "front matter" in section_lower:
        if intent in {
            "risk_factors",
            "risk",
            "business_description",
            "business",
            "cybersecurity",
            "cloud_business",
            "supply_chain",
            "climate",
            "competition",
            "cloud",
        }:
            return True
    return False


def rrf(rankings, k=60):
    if k <= 0:
        raise ValueError("RRF constant must be positive")

    scores = {}

    for ranking in rankings:
        seen = set()

        for rank, identifier in enumerate(ranking, 1):
            if identifier not in seen:
                scores[identifier] = scores.get(identifier, 0) + 1 / (k + rank)
                seen.add(identifier)

    return sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))


def matches(chunk, tickers, years):
    return (
        chunk["ticker"] in tickers
        and chunk["fiscal_year"] in years
        and chunk["filing_type"] == "10-K"
    )


def windows(text, tokenizer, size=380):
    if size < 1:
        raise ValueError("Model window size must be positive")

    ids = tokenizer.encode(text, add_special_tokens=False)

    return [
        tokenizer.decode(ids[index : index + size], skip_special_tokens=True)
        for index in range(0, len(ids), size)
    ] or [""]


def persist_bm25(chunks):
    tokens = [lexical(chunk["text"]) for chunk in chunks]
    groups = {}

    for ticker, year in sorted(
        {(chunk["ticker"], chunk["fiscal_year"]) for chunk in chunks}
    ):
        indices = [
            index
            for index, chunk in enumerate(chunks)
            if matches(chunk, [ticker], [year])
        ]

        if not any(tokens[index] for index in indices):
            raise ValueError("Source group has no searchable lexical tokens")

        model = BM25Okapi([tokens[index] for index in indices])
        state = {
            key: value for key, value in model.__dict__.items() if key != "tokenizer"
        }
        state["tokenizer"] = None
        groups[f"{ticker}:{year}"] = {
            "indices": indices,
            "state": state,
        }

    return {"tokens": tokens, "groups": groups, "format_version": 1}


def _restore_bm25(group, indices, tokens):
    if not isinstance(group, dict) or group.get("indices") != indices:
        raise ValueError("BM25 group alignment mismatch")

    state = group.get("state")

    if not isinstance(state, dict) or set(state) != BM25_STATE_FIELDS:
        raise ValueError("Unsupported persisted BM25 state")

    count = len(indices)

    if (
        state["tokenizer"] is not None
        or state["corpus_size"] != count
        or not isinstance(state["doc_freqs"], list)
        or len(state["doc_freqs"]) != count
        or state["doc_len"] != [len(tokens[index]) for index in indices]
        or not isinstance(state["idf"], dict)
    ):
        raise ValueError("Malformed persisted BM25 state")

    for name in ("k1", "b", "epsilon", "avgdl", "average_idf"):
        value = state[name]

        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError("Non-finite BM25 parameter")

    if state["avgdl"] <= 0 or state["k1"] <= 0 or not 0 <= state["b"] <= 1:
        raise ValueError("Invalid BM25 configuration")

    for frequencies in state["doc_freqs"]:
        if not isinstance(frequencies, dict) or any(
            not isinstance(term, str) or type(frequency) is not int or frequency <= 0
            for term, frequency in frequencies.items()
        ):
            raise ValueError("Invalid persisted BM25 frequencies")

    if any(
        not isinstance(term, str)
        or isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        for term, value in state["idf"].items()
    ):
        raise ValueError("Invalid persisted BM25 IDF")

    model = BM25Okapi.__new__(BM25Okapi)
    model.__dict__.update(state)
    return model


class Encoder:
    def __init__(self, model, *, local_only=False):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(
            model,
            device="cpu",
            local_files_only=local_only,
        )
        self.tokenizer = self.model.tokenizer

    def documents(self, texts):
        vectors = []

        for text in texts:
            encoded = self.model.encode(
                windows(text, self.tokenizer),
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            mean = np.mean(encoded, axis=0)
            norm = np.linalg.norm(mean)

            if not np.isfinite(mean).all() or not np.isfinite(norm) or norm <= 0:
                raise ValueError("Invalid document embedding")

            vectors.append(mean / norm)

        return np.asarray(vectors, dtype="float32")

    def query(self, text):
        prefixed = "Represent this sentence for searching relevant passages: " + text
        tokens = self.tokenizer.encode(prefixed, add_special_tokens=True)

        if len(tokens) > self.model.max_seq_length:
            raise ValueError("Question exceeds encoder input limit; narrow it")

        return self.model.encode(
            [prefixed],
            normalize_embeddings=True,
        ).astype("float32")


class HybridRetriever:
    def __init__(self, settings):
        self.settings = settings
        root = settings.index_dir
        manifest = read_json(root / "manifest.json")

        if not manifest:
            raise ValueError("Missing persisted index. Run offline ingestion.")

        sources = read_json(
            settings.data_dir / "processed/corpus_manifest.json",
            [],
        )
        validate_index_manifest(manifest, sources, settings)

        chunks = read_json(root / "chunks.json")
        lexical_data = read_json(root / "bm25.json")

        if digest(chunks) != manifest.get("chunks_sha256") or digest(
            lexical_data
        ) != manifest.get("bm25_sha256"):
            raise ValueError("Corrupt chunk or BM25 checksum")

        # Hash bytes before passing them to FAISS deserialization.
        raw_index = (root / "dense.faiss").read_bytes()

        if sha256_bytes(raw_index) != manifest.get("faiss_sha256"):
            raise ValueError("Corrupt FAISS checksum")

        validate_chunks(chunks, sources, settings.chunk_size)

        if len(chunks) != manifest["chunk_count"]:
            raise ValueError("Corrupt index/chunk count")

        if (
            not isinstance(lexical_data, dict)
            or lexical_data.get("format_version") != 1
            or lexical_data.get("tokens")
            != [lexical(chunk["text"]) for chunk in chunks]
            or not isinstance(lexical_data.get("groups"), dict)
        ):
            raise ValueError("Corrupt BM25 token data")

        import faiss

        index = faiss.deserialize_index(np.frombuffer(raw_index, dtype="uint8").copy())

        if (
            not isinstance(index, faiss.IndexFlatIP)
            or index.ntotal != len(chunks)
            or index.d != manifest["embedding_dimension"]
        ):
            raise ValueError("Corrupt or incompatible FAISS index")

        self.groups = {}
        expected_keys = set()

        for source in sources:
            ticker = source["ticker"]
            year = source["fiscal_year"]
            key = f"{ticker}:{year}"
            expected_keys.add(key)
            indices = [
                position
                for position, chunk in enumerate(chunks)
                if matches(chunk, [ticker], [year])
            ]
            model = _restore_bm25(
                lexical_data["groups"].get(key),
                indices,
                lexical_data["tokens"],
            )
            self.groups[(ticker, year)] = (indices, model)

        if set(lexical_data["groups"]) != expected_keys:
            raise ValueError("Unexpected BM25 company/year groups")

        self.manifest = manifest
        self.chunks = chunks
        self.index = index
        self.lexical_data = lexical_data
        self.encoder = None
        self.reranker = None

    def _rerank(self, query, candidates):
        import torch

        tokenizer = self.reranker.tokenizer
        query_tokens = tokenizer.encode(query, add_special_tokens=False)
        special = tokenizer.num_special_tokens_to_add(pair=True)
        window_size = min(350, 512 - len(query_tokens) - special)

        if window_size < 32:
            raise ValueError("Question leaves insufficient reranker context; narrow it")

        ranked = []

        for position, score in candidates:
            pairs = [
                (query, part)
                for part in windows(
                    self.chunks[position]["text"],
                    tokenizer,
                    window_size,
                )
            ]
            logits = np.asarray(
                self.reranker.predict(
                    pairs,
                    activation_fn=torch.nn.Identity(),
                )
            )

            if logits.size != len(pairs) or not np.isfinite(logits).all():
                raise ValueError("Invalid reranker output")

            raw = float(logits.max())
            relevance = 1 / (1 + math.exp(-max(-60, min(60, raw))))

            ranked.append(
                {
                    **self.chunks[position],
                    "retrieval_score": float(score),
                    "reranker_score": relevance,
                    "reranker_logit": raw,
                }
            )

        return sorted(
            ranked,
            key=lambda chunk: (-chunk["reranker_score"], chunk["chunk_id"]),
        )

    def retrieve(self, query, tickers, years):
        tickers = list(dict.fromkeys(tickers))
        years = list(dict.fromkeys(years))
        supported = {company["ticker"] for company in COMPANIES}

        if (
            not isinstance(query, str)
            or not query.strip()
            or not tickers
            or not years
            or not set(tickers).issubset(supported)
            or not set(years).issubset(YEARS)
        ):
            raise ValueError("Invalid retrieval question or company/year scope")

        scopes = [(ticker, year) for ticker in tickers for year in years]
        limit = self.settings.final_context_chunks

        if len(scopes) > limit:
            raise ValueError(
                "Requested company/year coverage exceeds the final context "
                "limit; narrow the request"
            )

        # Small section-intent expansion - preserve original, supplement
        expanded_query = _expand_query(query)
        intents = _get_intents(query.lower())

        trace = {
            "groups": [],
            "latency_ms": {},
            "score_semantics": ("Reranker relevance, not calibrated answer confidence"),
            "final_context_limit": limit,
            "original_query": query,
            "expanded_query": expanded_query,
            "detected_intents": sorted(intents),
        }
        started = time.perf_counter()

        if self.encoder is None:
            self.encoder = Encoder(
                self.settings.embedding_model,
                local_only=True,
            )

        # Use expanded query for dense retrieval (supplement, not replace)
        vector = np.asarray(self.encoder.query(expanded_query), dtype="float32")

        if (
            vector.shape != (1, self.index.d)
            or not np.isfinite(vector).all()
            or not np.allclose(np.linalg.norm(vector, axis=1), 1, atol=1e-4)
        ):
            raise ValueError("Invalid query embedding")

        dense_scores, dense_ids = self.index.search(
            np.ascontiguousarray(vector),
            self.index.ntotal,
        )
        dense_map = dict(
            zip(
                dense_ids[0].tolist(),
                dense_scores[0].tolist(),
                strict=True,
            )
        )

        if not all(math.isfinite(score) for score in dense_map.values()):
            raise ValueError("Non-finite dense retrieval scores")

        candidates = []

        for ticker, year in scopes:
            allowed, bm25 = self.groups[(ticker, year)]
            dense = sorted(
                allowed,
                key=lambda position: (-dense_map[position], position),
            )[: self.settings.faiss_top_k]
            # Use expanded query for BM25 as well
            scores = np.asarray(bm25.get_scores(lexical(expanded_query)))

            if scores.shape != (len(allowed),) or not np.isfinite(scores).all():
                raise ValueError("Invalid BM25 scores")

            sparse_positions = sorted(
                range(len(allowed)),
                key=lambda position: (-float(scores[position]), position),
            )[: self.settings.bm25_top_k]
            sparse = [
                allowed[position]
                for position in sparse_positions
                if scores[position] > 0
            ]
            fused = [
                (position, score)
                for position, score in rrf(
                    [dense, sparse],
                    self.settings.rrf_k,
                )
                if score >= self.settings.min_retrieval_score
            ]
            shortlist = fused[: self.settings.rerank_top_k]
            candidates.append(shortlist)
            sparse_map = {
                allowed[position]: float(scores[position])
                for position in sparse_positions
            }

            trace["groups"].append(
                {
                    "ticker": ticker,
                    "fiscal_year": year,
                    "faiss": [
                        [self.chunks[position]["chunk_id"], dense_map[position]]
                        for position in dense
                    ],
                    "bm25": [
                        [self.chunks[position]["chunk_id"], sparse_map[position]]
                        for position in sparse
                    ],
                    "rrf": [
                        [self.chunks[position]["chunk_id"], score]
                        for position, score in fused
                    ],
                    "rerank_candidates": [
                        self.chunks[position]["chunk_id"] for position, _ in shortlist
                    ],
                }
            )

        trace["latency_ms"]["retrieval"] = (time.perf_counter() - started) * 1000

        if self.reranker is None:
            from sentence_transformers import CrossEncoder

            self.reranker = CrossEncoder(
                self.settings.reranker_model,
                device="cpu",
                max_length=512,
                local_files_only=True,
            )

        started = time.perf_counter()
        # Use expanded query for reranking too (preserves intent terms)
        ranked = [self._rerank(expanded_query, group) for group in candidates]
        trace["latency_ms"]["reranking"] = (time.perf_counter() - started) * 1000

        # Apply small section relevance boost (ranking preference, not hard filter)
        # and re-sort
        boosted_ranked = []
        for group in ranked:
            boosted_group = []
            for chunk in group:
                section = chunk.get("section", "")
                boost = _section_relevance_boost(intents, section)
                # Store original score for trace
                orig_score = chunk["reranker_score"]
                new_score = float(max(0.0, min(1.0, orig_score + boost)))
                # Copy chunk with boosted score
                boosted_chunk = {
                    **chunk,
                    "reranker_score_original": orig_score,
                    "reranker_score": new_score,
                    "section_boost": boost,
                }
                boosted_group.append(boosted_chunk)
            # Re-sort after boost
            boosted_group = sorted(
                boosted_group,
                key=lambda c: (-c["reranker_score"], c["chunk_id"]),
            )
            boosted_ranked.append(boosted_group)

        ranked = boosted_ranked

        trace["reranked"] = [
            [
                {
                    "chunk_id": chunk["chunk_id"],
                    "score": chunk["reranker_score"],
                    "original_score": chunk.get(
                        "reranker_score_original", chunk["reranker_score"]
                    ),
                    "boost": chunk.get("section_boost", 0.0),
                    "section": chunk.get("section", ""),
                }
                for chunk in group
            ]
            for group in ranked
        ]

        threshold = self.settings.abstention_threshold
        eligible = [
            [chunk for chunk in group if chunk["reranker_score"] >= threshold]
            for group in ranked
        ]

        # C) Prevent wrong-section being sole evidence when relevant section exists
        # Check ranked (not just eligible) for relevant existence, then filter Front matter from eligible
        # This handles case where relevant exists but below threshold, we still want to avoid Front matter sole evidence
        for idx, (eligible_group, ranked_group) in enumerate(
            zip(eligible, ranked, strict=True)
        ):
            if not eligible_group:
                continue
            # Check if any relevant section exists in ranked (broader than eligible)
            has_relevant_in_ranked = False
            for intent in intents:
                for chunk in ranked_group:
                    sec_lower = chunk.get("section", "").lower()
                    if _is_relevant_section_for_intent(intent, sec_lower):
                        has_relevant_in_ranked = True
                        break
                if has_relevant_in_ranked:
                    break
            # Also check eligible for relevant (original logic)
            has_relevant_in_eligible = False
            for intent in intents:
                for chunk in eligible_group:
                    sec_lower = chunk.get("section", "").lower()
                    if _is_relevant_section_for_intent(intent, sec_lower):
                        has_relevant_in_eligible = True
                        break
                if has_relevant_in_eligible:
                    break

            has_relevant = has_relevant_in_ranked or has_relevant_in_eligible

            if has_relevant:
                filtered = []
                for chunk in eligible_group:
                    sec_lower = chunk.get("section", "").lower()
                    is_wrong = any(
                        _is_wrong_section_for_intent(intent, sec_lower)
                        for intent in intents
                    )
                    if not is_wrong:
                        filtered.append(chunk)
                # Only apply filter if it still leaves evidence
                if filtered:
                    if len(filtered) != len(eligible_group):
                        trace.setdefault("wrong_section_filtered", []).append(
                            {
                                "group_index": idx,
                                "original_count": len(eligible_group),
                                "filtered_count": len(filtered),
                                "had_relevant_in_ranked": has_relevant_in_ranked,
                                "had_relevant_in_eligible": has_relevant_in_eligible,
                            }
                        )
                    eligible[idx] = filtered
                # If filtering would empty group but relevant exists in ranked, try to promote relevant from ranked
                elif has_relevant_in_ranked:
                    # Find relevant chunks in ranked that are above a lower threshold (0.15) to salvage
                    promoted = []
                    for chunk in ranked_group:
                        sec_lower = chunk.get("section", "").lower()
                        if any(
                            _is_relevant_section_for_intent(intent, sec_lower)
                            for intent in intents
                        ):
                            # Allow lower threshold for relevant sections when Front matter is only alternative
                            if chunk["reranker_score"] >= 0.15:
                                promoted.append(chunk)
                    if promoted:
                        eligible[idx] = promoted[: self.settings.rerank_top_k]
                        trace.setdefault("wrong_section_filtered", []).append(
                            {
                                "group_index": idx,
                                "original_count": len(eligible_group),
                                "filtered_count": len(promoted),
                                "promoted_relevant": True,
                            }
                        )

        if any(not group for group in eligible):
            raise ValueError(
                "Insufficient evidence for one or more requested company/year groups"
            )

        selected, seen = [], set()

        for rank in range(self.settings.rerank_top_k):
            for group in eligible:
                if rank >= len(group):
                    continue

                chunk = group[rank]
                key = (
                    chunk["ticker"],
                    chunk["fiscal_year"],
                    chunk["text"],
                )

                if key not in seen:
                    selected.append(chunk)
                    seen.add(key)

                if len(selected) == limit:
                    break

            if len(selected) == limit:
                break

        if {(chunk["ticker"], chunk["fiscal_year"]) for chunk in selected} != set(
            scopes
        ):
            raise ValueError("Selected evidence lost requested scope coverage")

        trace["selected_chunk_ids"] = [chunk["chunk_id"] for chunk in selected]
        return selected, trace
