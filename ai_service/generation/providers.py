"""Hosted Groq and explicitly enabled Ollama narrative generation.

The documented Groq configuration remains:
https://api.groq.com/openai/v1

The installed Groq SDK supplies /openai/v1 in its resource paths.
The adapter therefore passes the origin, not the API-prefix URL, to
the SDK. This prevents duplicated /openai/v1 request paths.

No credentials are required during import or provider construction.
Provider failures expose safe categories, not response bodies or secrets.
"""

import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from groq import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    Groq,
)

from ai_service.generation.context import (
    ContextError,
    build_messages,
    ensure_context_fits,
    provider_response_schema,
)
from core.config import Settings
from core.schemas import Synthesis

TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}

# Fallback is an explicit transient-failure policy, not a way around
# authentication, configuration, schema, output, or evidence validation.
FALLBACK_CATEGORIES = frozenset(
    {
        "timeout",
        "rate_limit",
        "provider_unavailable",
    }
)

# Retained for compatibility with callers importing these known categories.
# The allowlist above, not this incomplete denylist, controls fallback.
NON_FALLBACK_CATEGORIES = {
    "unsupported_provider",
    "invalid_provider_configuration",
    "context_budget_exceeded",
}


class ProviderError(RuntimeError):
    """Application-safe provider failure without sensitive payloads."""

    def __init__(
        self,
        category: str,
        *,
        provider: str | None = None,
        model: str | None = None,
        attempts: int = 0,
        fallback: dict | None = None,
    ):
        self.category = category
        self.provider = provider
        self.model = model
        self.attempts = attempts
        self.fallback = fallback
        super().__init__(category)


class _AttemptError(Exception):
    """Internal failure category and its retry eligibility."""

    def __init__(self, category: str, *, retryable: bool):
        self.category = category
        self.retryable = retryable
        super().__init__(category)


class LLMProvider(ABC):
    name: str

    @property
    @abstractmethod
    def model(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def generate(
        self,
        question: str,
        evidence: list[dict],
        calculations: list[dict],
    ) -> Synthesis:
        raise NotImplementedError


def configured_model(settings: Settings, provider: str | None = None) -> str:
    selected = provider or settings.llm_provider

    if selected == "groq":
        return settings.groq_model

    if selected == "ollama":
        return settings.ollama_model

    raise ProviderError("unsupported_provider")


def _validate_base_url(url: str, *, require_https: bool) -> str:
    try:
        if (
            not isinstance(url, str)
            or not url
            or any(character.isspace() for character in url)
            or "\\" in url
            or any(ord(character) < 32 or ord(character) == 127 for character in url)
        ):
            raise ValueError("Invalid endpoint")

        parsed = urlsplit(url)
        valid_scheme = (
            parsed.scheme == "https"
            if require_https
            else parsed.scheme in {"http", "https"}
        )

        if (
            not valid_scheme
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or "?" in url
            or "#" in url
        ):
            raise ValueError("Invalid endpoint")

        # Access validates port syntax and range.
        _ = parsed.port
    except (TypeError, ValueError):
        raise ProviderError("invalid_provider_configuration") from None

    return url.rstrip("/")


def _groq_sdk_base_url(url: str) -> str:
    """Convert a configured Groq API endpoint to the SDK origin.

    Accepted forms:
    - https://api.groq.com
    - https://api.groq.com/
    - https://api.groq.com/openai/v1
    - https://api.groq.com/openai/v1/

    Explicit alternate HTTPS origins remain supported for server-configured
    gateways exposing the same API prefix. Arbitrary path prefixes are
    rejected rather than silently rewritten or sent to a guessed endpoint.

    There is no network request, credential access, SDK introspection, or
    endpoint probing here.
    """
    validated = _validate_base_url(url, require_https=True)
    parsed = urlsplit(validated)

    if parsed.path not in {"", "/openai/v1"}:
        raise ProviderError("invalid_provider_configuration")

    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def _http_failure(status_code: int) -> _AttemptError:
    if status_code in {401, 403}:
        return _AttemptError("authentication", retryable=False)

    if status_code == 404:
        return _AttemptError("model_or_endpoint_unavailable", retryable=False)

    if status_code == 429:
        return _AttemptError("rate_limit", retryable=True)

    if status_code == 408:
        return _AttemptError("timeout", retryable=True)

    if status_code in TRANSIENT_STATUS_CODES:
        return _AttemptError("provider_unavailable", retryable=True)

    if status_code in {400, 405, 409, 413, 415, 422}:
        return _AttemptError("invalid_request", retryable=False)

    return _AttemptError("provider_http_error", retryable=False)


def _parse_synthesis(content: Any) -> Synthesis:
    if not isinstance(content, str) or not content.strip():
        raise _AttemptError("malformed_response", retryable=False)

    try:
        return Synthesis.model_validate_json(content)
    except ValueError:
        raise _AttemptError(
            "structured_output_validation_failed",
            retryable=False,
        ) from None


def _run_with_retries(
    operation: Callable[[float], Synthesis],
    settings: Settings,
    *,
    deadline: float,
    provider: str,
    model: str,
) -> Synthesis:
    """Bound retries within a shared application deadline.

    Transport timeouts are not forced process cancellation.
    Responses arriving after the deadline are rejected.
    """
    for attempt_index in range(settings.llm_max_retries + 1):
        remaining = deadline - time.monotonic()

        if remaining <= 0:
            raise ProviderError(
                "timeout",
                provider=provider,
                model=model,
                attempts=attempt_index,
            )

        timeout = min(settings.llm_request_timeout, remaining)

        try:
            result = operation(timeout)
        except _AttemptError as exc:
            attempts = attempt_index + 1

            if not exc.retryable or attempt_index >= settings.llm_max_retries:
                raise ProviderError(
                    exc.category,
                    provider=provider,
                    model=model,
                    attempts=attempts,
                ) from None

            delay = min(
                settings.llm_retry_backoff_seconds * (2**attempt_index),
                settings.llm_retry_max_backoff_seconds,
            )
            remaining = deadline - time.monotonic()

            if remaining <= delay:
                raise ProviderError(
                    exc.category,
                    provider=provider,
                    model=model,
                    attempts=attempts,
                ) from None

            if delay > 0:
                time.sleep(delay)
        else:
            if time.monotonic() > deadline:
                raise ProviderError(
                    "timeout",
                    provider=provider,
                    model=model,
                    attempts=attempt_index + 1,
                )
            return result

    raise ProviderError(
        "provider_unavailable",
        provider=provider,
        model=model,
    )


def _generation_deadline(settings: Settings) -> float:
    return time.monotonic() + min(
        settings.llm_total_timeout,
        settings.request_timeout,
    )


def _validate_generation_context(
    settings: Settings,
    question: str,
    evidence: list[dict],
    calculations: list[dict],
    *,
    provider: str,
    model: str,
) -> None:
    try:
        ensure_context_fits(
            settings,
            question,
            evidence,
            calculations,
            provider=provider,
        )
    except ContextError:
        raise ProviderError(
            "context_budget_exceeded",
            provider=provider,
            model=model,
        ) from None


class GroqProvider(LLMProvider):
    name = "groq"

    def __init__(
        self,
        settings: Settings,
        *,
        deadline: float | None = None,
    ):
        self.s = settings
        self.deadline = deadline

    @property
    def model(self) -> str:
        return self.s.groq_model

    def generate(
        self,
        question: str,
        evidence: list[dict],
        calculations: list[dict],
    ) -> Synthesis:
        api_key = self.s.groq_api_key.get_secret_value().strip()

        if not api_key:
            raise ProviderError(
                "missing_api_key",
                provider=self.name,
                model=self.model,
            )

        if not self.model.strip():
            raise ProviderError(
                "invalid_provider_configuration",
                provider=self.name,
                model=self.model,
            )

        try:
            base_url = _groq_sdk_base_url(self.s.groq_base_url)
        except ProviderError:
            raise ProviderError(
                "invalid_provider_configuration",
                provider=self.name,
                model=self.model,
            ) from None

        _validate_generation_context(
            self.s,
            question,
            evidence,
            calculations,
            provider=self.name,
            model=self.model,
        )

        messages = build_messages(question, evidence, calculations)
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "financial_synthesis",
                "strict": True,
                "schema": provider_response_schema(),
            },
        }

        deadline = (
            self.deadline if self.deadline is not None else _generation_deadline(self.s)
        )

        def operation(timeout: float) -> Synthesis:
            try:
                with Groq(
                    api_key=api_key,
                    base_url=base_url,
                    timeout=timeout,
                    max_retries=0,
                ) as client:
                    response = client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        response_format=response_format,
                        max_completion_tokens=self.s.llm_max_output_tokens,
                        stream=False,
                    )
            except APITimeoutError:
                raise _AttemptError("timeout", retryable=True) from None
            except APIConnectionError:
                raise _AttemptError(
                    "provider_unavailable",
                    retryable=True,
                ) from None
            except APIStatusError as exc:
                raise _http_failure(exc.status_code) from None
            except APIError:
                raise _AttemptError(
                    "provider_response_error",
                    retryable=False,
                ) from None
            except (TypeError, ValueError):
                raise _AttemptError(
                    "provider_response_or_configuration_error",
                    retryable=False,
                ) from None

            try:
                choice = response.choices[0]
                finish_reason = choice.finish_reason
                content = choice.message.content
            except (AttributeError, IndexError, KeyError, TypeError):
                raise _AttemptError(
                    "malformed_response",
                    retryable=False,
                ) from None

            if finish_reason == "length":
                raise _AttemptError("output_token_limit", retryable=False)

            if finish_reason != "stop":
                raise _AttemptError(
                    "incomplete_or_refused_response",
                    retryable=False,
                )

            return _parse_synthesis(content)

        return _run_with_retries(
            operation,
            self.s,
            deadline=deadline,
            provider=self.name,
            model=self.model,
        )


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(
        self,
        settings: Settings,
        *,
        deadline: float | None = None,
    ):
        self.s = settings
        self.deadline = deadline

    @property
    def model(self) -> str:
        return self.s.ollama_model

    def generate(
        self,
        question: str,
        evidence: list[dict],
        calculations: list[dict],
    ) -> Synthesis:
        if not self.model.strip():
            raise ProviderError(
                "missing_ollama_model",
                provider=self.name,
                model=self.model,
            )

        try:
            base_url = _validate_base_url(
                self.s.ollama_base_url,
                require_https=False,
            )
        except ProviderError:
            raise ProviderError(
                "invalid_provider_configuration",
                provider=self.name,
                model=self.model,
            ) from None

        _validate_generation_context(
            self.s,
            question,
            evidence,
            calculations,
            provider=self.name,
            model=self.model,
        )

        payload = {
            "model": self.model,
            "stream": False,
            "format": provider_response_schema(),
            "messages": build_messages(question, evidence, calculations),
            "options": {
                "temperature": 0,
                "num_predict": self.s.llm_max_output_tokens,
                "num_ctx": self.s.ollama_context_window_tokens,
            },
        }

        deadline = (
            self.deadline if self.deadline is not None else _generation_deadline(self.s)
        )

        def operation(timeout: float) -> Synthesis:
            try:
                with httpx.Client(
                    timeout=timeout,
                    follow_redirects=False,
                ) as client:
                    response = client.post(base_url + "/api/chat", json=payload)

                response.raise_for_status()
                body = response.json()
            except httpx.TimeoutException:
                raise _AttemptError("timeout", retryable=True) from None
            except httpx.HTTPStatusError as exc:
                raise _http_failure(exc.response.status_code) from None
            except httpx.TransportError:
                raise _AttemptError(
                    "provider_unavailable",
                    retryable=True,
                ) from None
            except (TypeError, ValueError):
                raise _AttemptError(
                    "malformed_response",
                    retryable=False,
                ) from None

            if not isinstance(body, dict) or body.get("done") is not True:
                raise _AttemptError(
                    "incomplete_or_refused_response",
                    retryable=False,
                )

            if body.get("done_reason") == "length":
                raise _AttemptError("output_token_limit", retryable=False)

            try:
                content = body["message"]["content"]
            except (KeyError, TypeError):
                raise _AttemptError("malformed_response", retryable=False) from None

            return _parse_synthesis(content)

        return _run_with_retries(
            operation,
            self.s,
            deadline=deadline,
            provider=self.name,
            model=self.model,
        )


def create_provider(
    settings: Settings,
    *,
    provider: str | None = None,
    deadline: float | None = None,
) -> LLMProvider:
    selected = provider or settings.llm_provider

    if selected == "groq":
        return GroqProvider(settings, deadline=deadline)

    if selected == "ollama":
        return OllamaProvider(settings, deadline=deadline)

    raise ProviderError("unsupported_provider")


def synthesize(
    settings: Settings,
    question: str,
    evidence: list[dict],
    calculations: list[dict],
) -> tuple[Synthesis, dict[str, Any]]:
    """Generate and report the actual provider used.

    Primary and fallback providers share one deadline. Explicitly enabled
    fallback is permitted only for timeout, rate limiting, or temporary
    provider unavailability. It does not bypass application validation.
    """
    deadline = _generation_deadline(settings)
    primary = create_provider(settings, deadline=deadline)

    try:
        output = primary.generate(question, evidence, calculations)
    except ProviderError as exc:
        if (
            primary.name != "groq"
            or not settings.enable_llm_fallback
            or exc.category not in FALLBACK_CATEGORIES
        ):
            raise

        fallback_metadata = {
            "original_provider": primary.name,
            "original_model": primary.model,
            "failure_category": exc.category,
            "primary_attempts": exc.attempts,
            "fallback_provider": "ollama",
            "fallback_model": settings.ollama_model,
        }

        fallback_provider = create_provider(
            settings,
            provider="ollama",
            deadline=deadline,
        )

        try:
            output = fallback_provider.generate(question, evidence, calculations)
        except ProviderError as final:
            fallback_metadata["fallback_failure_category"] = final.category
            fallback_metadata["fallback_attempts"] = final.attempts

            raise ProviderError(
                "primary_and_fallback_failed",
                provider=fallback_provider.name,
                model=fallback_provider.model,
                attempts=final.attempts,
                fallback=fallback_metadata,
            ) from None

        return output, {
            "provider": fallback_provider.name,
            "model": fallback_provider.model,
            "fallback_used": True,
            "fallback": fallback_metadata,
        }

    return output, {
        "provider": primary.name,
        "model": primary.model,
        "fallback_used": False,
        "fallback": None,
    }
