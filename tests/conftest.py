"""Shared synthetic fixtures and local-environment isolation.

No fixture represents an actual financial observation or acquired filing.
Network blocking is enabled by the documented pytest/CI command.
"""

import pytest

from core.config import Settings


@pytest.fixture(autouse=True)
def isolate_provider_environment(monkeypatch, tmp_path):
    """Override Settings fields that could otherwise leak from local .env.

    Module-level Settings objects constructed by transport imports inherit
    these test values. Tests may override individual values afterward.
    """
    test_environment = {
        "APP_ENV": "test",
        "LLM_PROVIDER": "groq",
        "GROQ_API_KEY": "",
        "GROQ_BASE_URL": "https://api.groq.com/openai/v1",
        "GROQ_MODEL": "openai/gpt-oss-120b",
        "ENABLE_LLM_FALLBACK": "false",
        "OLLAMA_BASE_URL": "http://localhost:11434",
        "OLLAMA_MODEL": "",
        "LLM_REQUEST_TIMEOUT": "30",
        "LLM_TOTAL_TIMEOUT": "90",
        "LLM_MAX_RETRIES": "2",
        "LLM_RETRY_BACKOFF_SECONDS": "1",
        "LLM_RETRY_MAX_BACKOFF_SECONDS": "8",
        "LLM_MAX_OUTPUT_TOKENS": "2000",
        "LLM_TOKEN_SAFETY_MARGIN": "2048",
        "GROQ_CONTEXT_WINDOW_TOKENS": "131072",
        "OLLAMA_CONTEXT_WINDOW_TOKENS": "32768",
        "CONTEXT_CHAR_BUDGET": "24000",
        "SEC_CONTACT_EMAIL": "",
        "SEC_USER_AGENT": "",
        "EMBEDDING_MODEL": "BAAI/bge-base-en-v1.5",
        "RERANKER_MODEL": "BAAI/bge-reranker-base",
        "FAISS_TOP_K": "20",
        "BM25_TOP_K": "20",
        "RRF_K": "60",
        "RERANK_TOP_K": "8",
        "FINAL_CONTEXT_CHUNKS": "6",
        "CHUNK_SIZE": "700",
        "CHUNK_OVERLAP": "100",
        "MIN_RETRIEVAL_SCORE": "0",
        "ABSTENTION_THRESHOLD": "0.35",
        "REQUEST_TIMEOUT": "120",
        "AI_SERVICE_URL": "http://localhost:8001",
        "BACKEND_URL": "http://localhost:8000",
        "CORS_ORIGINS": '["http://localhost:8080"]',
        "DATA_DIR": str(tmp_path / "module-data"),
        "INDEX_DIR": str(tmp_path / "module-indexes"),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
    }

    for name, value in test_environment.items():
        monkeypatch.setenv(name, value)


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        index_dir=tmp_path / "indexes",
        sec_contact_email="",
        sec_user_agent="",
    )


@pytest.fixture
def report():
    from tests.financial_fixtures import synthetic_manifest

    return next(
        item
        for item in synthetic_manifest()
        if item["ticker"] == "AAPL" and item["fiscal_year"] == 2024
    )


@pytest.fixture
def raw_fact(report):
    return {
        "val": 100,
        "start": "2024-01-01",
        "end": report["period_end"],
        "fy": report["fiscal_year"],
        "fp": "FY",
        "form": "10-K",
        "accn": report["accession_number"],
    }


def wrap(facts, concept="Revenues", unit="USD", cik=320193):
    """Synthetic Company Facts envelope with explicit entity identity."""
    return {
        "cik": cik,
        "facts": {
            "us-gaap": {
                concept: {
                    "units": {
                        unit: facts,
                    },
                },
            },
        },
    }
