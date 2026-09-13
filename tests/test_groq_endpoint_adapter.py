"""Offline regressions for Groq SDK URL construction and fallback policy.

The real installed SDK builds requests against httpx.MockTransport.
No real credential, socket, model weight, or provider request is needed.

A synthetic HTTP 400 deliberately ends the generation attempt after request
construction. It does not pretend to be a successful narrative response.
"""

import json
from types import SimpleNamespace

import httpx
import pytest
from groq import Groq as SDKGroq
from pydantic import SecretStr

from ai_service.generation import providers


@pytest.mark.parametrize(
    "configured",
    [
        "https://api.groq.com",
        "https://api.groq.com/",
        "https://api.groq.com/openai/v1",
        "https://api.groq.com/openai/v1/",
    ],
)
def test_normalizes_documented_groq_endpoint(configured):
    assert providers._groq_sdk_base_url(configured) == "https://api.groq.com"


@pytest.mark.parametrize(
    "configured",
    [
        "http://api.groq.com/openai/v1",
        "https://user:secret@api.groq.com/openai/v1",
        "https://api.groq.com/openai/v1?token=secret",
        "https://api.groq.com/openai/v1#fragment",
        "https://api.groq.com/openai/v1?",
        "https://api.groq.com/openai/v1#",
        "https://api.groq.com/openai/v1/openai/v1",
        "https://api.groq.com/v1",
        "https://api.groq.com/custom/openai/v1",
        "https://api.groq.com:invalid/openai/v1",
        "https://api.groq.com\\openai\\v1",
        " https://api.groq.com/openai/v1",
        "https://api.groq.com/openai/v1\n",
        "",
    ],
)
def test_rejects_ambiguous_or_unsafe_groq_configuration(configured):
    with pytest.raises(providers.ProviderError) as caught:
        providers._groq_sdk_base_url(configured)

    assert caught.value.category == "invalid_provider_configuration"
    assert str(caught.value) == "invalid_provider_configuration"


def test_preserves_explicit_https_gateway_origin():
    assert (
        providers._groq_sdk_base_url("https://gateway.example:8443/openai/v1")
        == "https://gateway.example:8443"
    )


def test_ollama_base_validation_does_not_strip_api_prefixes():
    assert (
        providers._validate_base_url(
            "http://127.0.0.1:11434",
            require_https=False,
        )
        == "http://127.0.0.1:11434"
    )


@pytest.mark.parametrize(
    "configured",
    [
        "https://api.groq.com",
        "https://api.groq.com/openai/v1",
    ],
)
def test_real_sdk_model_listing_has_one_api_prefix(configured):
    captured = []

    def handle(request):
        captured.append((request.method, request.url.host, request.url.path))
        return httpx.Response(200, json={"object": "list", "data": []})

    with SDKGroq(
        api_key="offline-dummy-key",
        base_url=providers._groq_sdk_base_url(configured),
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handle)),
    ) as client:
        client.models.list()

    assert captured == [("GET", "api.groq.com", "/openai/v1/models")]


def test_provider_generation_uses_normalized_sdk_endpoint(monkeypatch):
    captured = []
    constructed = []
    schema = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def handle(request):
        captured.append(
            (
                request.method,
                request.url.host,
                request.url.path,
                json.loads(request.content),
            )
        )
        return httpx.Response(
            400,
            json={
                "error": {
                    "message": "Synthetic offline transport response",
                    "type": "invalid_request_error",
                }
            },
        )

    def client_factory(**kwargs):
        constructed.append(kwargs.copy())
        return SDKGroq(
            **kwargs,
            http_client=httpx.Client(transport=httpx.MockTransport(handle)),
        )

    monkeypatch.setattr(providers, "Groq", client_factory)
    monkeypatch.setattr(
        providers,
        "_validate_generation_context",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        providers,
        "build_messages",
        lambda *args: [{"role": "user", "content": "Offline routing test"}],
    )
    monkeypatch.setattr(providers, "provider_response_schema", lambda: schema)

    settings = SimpleNamespace(
        groq_api_key=SecretStr("offline-dummy-key"),
        groq_model="openai/gpt-oss-120b",
        groq_base_url="https://api.groq.com/openai/v1",
        llm_max_output_tokens=128,
        llm_total_timeout=30,
        request_timeout=30,
        llm_request_timeout=10,
        llm_max_retries=0,
        llm_retry_backoff_seconds=0,
        llm_retry_max_backoff_seconds=0,
    )

    with pytest.raises(providers.ProviderError) as caught:
        providers.GroqProvider(settings).generate("Offline routing test", [], [])

    assert caught.value.category == "invalid_request"
    assert caught.value.attempts == 1
    assert len(constructed) == 1
    assert constructed[0]["base_url"] == "https://api.groq.com"
    assert constructed[0]["max_retries"] == 0
    assert len(captured) == 1

    method, host, path, payload = captured[0]
    assert (method, host, path) == (
        "POST",
        "api.groq.com",
        "/openai/v1/chat/completions",
    )
    assert payload["model"] == "openai/gpt-oss-120b"
    assert payload["stream"] is False
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["strict"] is True
    assert payload["response_format"]["json_schema"]["schema"] == schema
    assert "offline-dummy-key" not in str(caught.value)


@pytest.mark.parametrize(
    "category",
    [
        "authentication",
        "missing_api_key",
        "invalid_provider_configuration",
        "context_budget_exceeded",
        "model_or_endpoint_unavailable",
        "invalid_request",
        "malformed_response",
        "structured_output_validation_failed",
        "output_token_limit",
        "incomplete_or_refused_response",
        "provider_response_error",
        "provider_http_error",
        "unknown_citation_id",
    ],
)
def test_nontransient_failures_do_not_trigger_fallback(monkeypatch, category):
    constructed = []
    failure = providers.ProviderError(
        category,
        provider="groq",
        model="primary-model",
        attempts=1,
    )

    def generate(*args):
        raise failure

    primary = SimpleNamespace(
        name="groq",
        model="primary-model",
        generate=generate,
    )

    def factory(settings, *, provider=None, deadline=None):
        constructed.append(provider)
        assert provider is None
        return primary

    monkeypatch.setattr(providers, "create_provider", factory)
    settings = SimpleNamespace(
        enable_llm_fallback=True,
        llm_total_timeout=30,
        request_timeout=30,
        ollama_model="fallback-model",
    )

    with pytest.raises(providers.ProviderError) as caught:
        providers.synthesize(settings, "Offline test", [], [])

    assert caught.value is failure
    assert constructed == [None]


@pytest.mark.parametrize("category", ["timeout", "rate_limit", "provider_unavailable"])
@pytest.mark.parametrize("enabled", [False, True])
def test_transient_fallback_requires_explicit_enablement(
    monkeypatch,
    category,
    enabled,
):
    constructed = []
    output = object()
    failure = providers.ProviderError(
        category,
        provider="groq",
        model="primary-model",
        attempts=2,
    )

    def primary_generate(*args):
        raise failure

    primary = SimpleNamespace(
        name="groq",
        model="primary-model",
        generate=primary_generate,
    )
    fallback = SimpleNamespace(
        name="ollama",
        model="fallback-model",
        generate=lambda *args: output,
    )

    def factory(settings, *, provider=None, deadline=None):
        constructed.append((provider, deadline))
        return fallback if provider == "ollama" else primary

    monkeypatch.setattr(providers, "create_provider", factory)
    settings = SimpleNamespace(
        enable_llm_fallback=enabled,
        llm_total_timeout=30,
        request_timeout=30,
        ollama_model="fallback-model",
    )

    if not enabled:
        with pytest.raises(providers.ProviderError) as caught:
            providers.synthesize(settings, "Offline test", [], [])
        assert caught.value is failure
        assert len(constructed) == 1
        return

    result, metadata = providers.synthesize(settings, "Offline test", [], [])

    assert result is output
    assert [provider for provider, _ in constructed] == [None, "ollama"]
    assert constructed[0][1] == constructed[1][1]
    assert metadata["provider"] == "ollama"
    assert metadata["model"] == "fallback-model"
    assert metadata["fallback_used"] is True
    assert metadata["fallback"]["failure_category"] == category
    assert metadata["fallback"]["primary_attempts"] == 2
