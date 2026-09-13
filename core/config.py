from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        validate_assignment=True,
    )

    app_env: str = "development"

    llm_provider: str = "groq"
    groq_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "openai/gpt-oss-120b"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = ""
    enable_llm_fallback: bool = False

    llm_request_timeout: float = 30
    llm_total_timeout: float = 90
    llm_max_retries: int = 2
    llm_retry_backoff_seconds: float = 1
    llm_retry_max_backoff_seconds: float = 8
    llm_max_output_tokens: int = 2000
    llm_token_safety_margin: int = 2048

    groq_context_window_tokens: int = 131072
    ollama_context_window_tokens: int = 32768
    context_char_budget: int = 24000

    sec_contact_email: str = ""
    sec_user_agent: str = ""

    embedding_model: str = "BAAI/bge-base-en-v1.5"
    reranker_model: str = "BAAI/bge-reranker-base"

    faiss_top_k: int = 20
    bm25_top_k: int = 20
    rrf_k: int = 60
    rerank_top_k: int = 8
    final_context_chunks: int = 6

    chunk_size: int = 700
    chunk_overlap: int = 100

    min_retrieval_score: float = 0.0
    abstention_threshold: float = 0.25

    request_timeout: float = 120
    ai_service_url: str = "http://localhost:8001"
    backend_url: str = "http://localhost:8000"
    cors_origins: list[str] = ["http://localhost:8080"]

    data_dir: Path = Path("data")
    index_dir: Path = Path("indexes")

    @model_validator(mode="after")
    def valid(self):
        if self.llm_provider not in {"groq", "ollama"}:
            raise ValueError("LLM_PROVIDER must be groq or ollama")

        if not self.groq_model.strip():
            raise ValueError("GROQ_MODEL must not be empty")

        if not 0 <= self.chunk_overlap < self.chunk_size:
            raise ValueError("Chunk overlap must be smaller than size")

        if not 0 <= self.abstention_threshold <= 1:
            raise ValueError("Threshold must be in [0, 1]")

        if (
            min(
                self.faiss_top_k,
                self.bm25_top_k,
                self.rrf_k,
                self.rerank_top_k,
                self.final_context_chunks,
            )
            < 1
        ):
            raise ValueError("Retrieval sizes must be positive")

        if (
            min(
                self.request_timeout,
                self.llm_request_timeout,
                self.llm_total_timeout,
            )
            <= 0
        ):
            raise ValueError("Request timeouts must be positive")

        if not 0 <= self.llm_max_retries <= 5:
            raise ValueError("LLM_MAX_RETRIES must be between zero and five")

        if self.llm_retry_backoff_seconds < 0:
            raise ValueError("LLM_RETRY_BACKOFF_SECONDS must not be negative")

        if self.llm_retry_max_backoff_seconds < self.llm_retry_backoff_seconds:
            raise ValueError(
                "Maximum retry backoff must be at least the initial backoff"
            )

        if self.context_char_budget < 1:
            raise ValueError("CONTEXT_CHAR_BUDGET must be positive")

        if self.llm_max_output_tokens < 1:
            raise ValueError("LLM_MAX_OUTPUT_TOKENS must be positive")

        if self.llm_token_safety_margin < 0:
            raise ValueError("LLM_TOKEN_SAFETY_MARGIN must not be negative")

        reserved_tokens = self.llm_max_output_tokens + self.llm_token_safety_margin

        if self.groq_context_window_tokens <= reserved_tokens:
            raise ValueError(
                "Groq context window must exceed output and safety reserves"
            )

        if self.ollama_context_window_tokens <= reserved_tokens:
            raise ValueError(
                "Ollama context window must exceed output and safety reserves"
            )

        return self


COMPANIES = [
    {"company": "Apple", "ticker": "AAPL", "cik": "0000320193"},
    {"company": "Microsoft", "ticker": "MSFT", "cik": "0000789019"},
    {"company": "Amazon", "ticker": "AMZN", "cik": "0001018724"},
]

YEARS = [2022, 2023, 2024]
