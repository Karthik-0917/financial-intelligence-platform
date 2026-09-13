"""Shared public/private API contracts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

QuestionType = Literal[
    "FACT",
    "COMPARISON",
    "CALCULATION",
    "MULTI_DOCUMENT",
    "EXPLANATION",
    "RISK",
    "UNSUPPORTED",
]


class Query(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    question: str = Field(min_length=5, max_length=2000)
    tickers: list[Literal["AAPL", "MSFT", "AMZN"]] = Field(
        default_factory=list,
        max_length=3,
    )
    years: list[Literal[2022, 2023, 2024]] = Field(
        default_factory=list,
        max_length=3,
    )

    @field_validator("tickers")
    @classmethod
    def unique_tickers(cls, value):
        return list(dict.fromkeys(value))

    @field_validator("years")
    @classmethod
    def unique_years(cls, value):
        return sorted(set(value))


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4000)
    citation_ids: list[str] = Field(min_length=1, max_length=12)


class Synthesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claims: list[Claim] = Field(min_length=1, max_length=12)


class Response(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    answer: str = ""
    question_type: QuestionType = "UNSUPPORTED"
    key_findings: list[dict] = Field(default_factory=list, max_length=12)
    calculations: list[dict] = Field(default_factory=list, max_length=100)
    facts: list[dict] = Field(default_factory=list, max_length=200)
    citation_ids: list[str] = Field(default_factory=list, max_length=200)
    evidence: list[dict] = Field(default_factory=list, max_length=200)
    grounded: bool = False
    grounding_status: str = "not_validated"
    abstained: bool = False
    abstention_reason: str | None = None
    provider: str | None = None
    model: str | None = None
    fallback_used: bool = False
    fallback: dict | None = None
    latency_ms: float = Field(default=0, ge=0, allow_inf_nan=False)
    trace: dict = Field(default_factory=dict)
