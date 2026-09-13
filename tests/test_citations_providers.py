import json
from types import SimpleNamespace

import httpx
import pytest
from groq import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
)
from pydantic import SecretStr, ValidationError

import ai_service.generation.providers as providers
from ai_service.citations.registry import Registry, validate_citations
from ai_service.generation.context import provider_response_schema
from ai_service.generation.providers import (
    GroqProvider,
    LLMProvider,
    OllamaProvider,
    ProviderError,
    configured_model,
    create_provider,
    synthesize,
)
from core.config import Settings
from core.schemas import Synthesis

FIXTURE_API_KEY = "fixture-not-a-real-api-key"
FIXTURE_CITATION_ID = "FIXTURE_EVIDENCE"
FIXTURE_MODEL = "fixture-hosted-model"
FIXTURE_LOCAL_MODEL = "fixture-local-model"


def fixture_synthesis():
    return Synthesis(
        claims=[
            {
                "text": "Supply chain disruptions may affect operations.",
                "citation_ids": [FIXTURE_CITATION_ID],
            }
        ]
    )


def fixture_evidence():
    return [
        {
            "application_metadata": {
                "evidence_id": FIXTURE_CITATION_ID,
                "company": "Fixture Corp",
                "ticker": "AMZN",
                "fiscal_year": 2024,
            },
            "untrusted_document_text": (
                "Supply chain disruptions may affect operations."
            ),
        }
    ]


def completion(content=None, finish_reason="stop"):
    if content is None:
        content = fixture_synthesis().model_dump_json()

    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason=finish_reason,
                message=SimpleNamespace(content=content),
            )
        ]
    )


def status_error(code):
    request = httpx.Request(
        "POST",
        "https://api.groq.com/openai/v1/chat/completions",
    )
    response = httpx.Response(
        code,
        request=request,
    )
    return APIStatusError(
        "Fixture provider error",
        response=response,
        body={"error": "fixture-sensitive-provider-body"},
    )


@pytest.fixture(autouse=True)
def block_live_groq_client(monkeypatch):
    def blocked_client(**kwargs):
        raise AssertionError("A test attempted to construct an unmocked Groq client")

    monkeypatch.setattr(
        providers,
        "Groq",
        blocked_client,
    )


@pytest.fixture
def sdk_stub(monkeypatch):
    """A mocked SDK client. It never performs a network request."""

    def install(outcomes):
        pending = list(outcomes)
        observed = {
            "clients": [],
            "requests": [],
            "closed_clients": 0,
        }

        class FakeClient:
            def __init__(self, **kwargs):
                observed["clients"].append(kwargs)
                self.chat = SimpleNamespace(
                    completions=SimpleNamespace(
                        create=self.create_completion,
                    )
                )

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                observed["closed_clients"] += 1
                return False

            def create_completion(self, **kwargs):
                observed["requests"].append(kwargs)

                if not pending:
                    raise AssertionError("Provider exceeded the mocked attempt count")

                outcome = pending.pop(0)

                if isinstance(outcome, Exception):
                    raise outcome

                return outcome

        monkeypatch.setattr(
            providers,
            "Groq",
            FakeClient,
        )
        return observed

    return install


@pytest.fixture
def fake_clock(monkeypatch):
    clock = {
        "now": 1000.0,
        "sleeps": [],
    }

    def monotonic():
        return clock["now"]

    def sleep(seconds):
        clock["sleeps"].append(seconds)
        clock["now"] += seconds

    monkeypatch.setattr(
        providers.time,
        "monotonic",
        monotonic,
    )
    monkeypatch.setattr(
        providers.time,
        "sleep",
        sleep,
    )
    return clock


def authorize_fixture(settings):
    settings.groq_api_key = SecretStr(FIXTURE_API_KEY)


def test_registry(settings):
    registry = Registry(settings.data_dir / "test.sqlite")
    records = registry.register(
        "fixture",
        [{"text": "Evidence fixture"}],
    )
    key = next(iter(records))

    assert registry.get(key)["text"] == "Evidence fixture"
    assert registry.get("unknown") is None

    response = Synthesis(
        claims=[
            {
                "text": "Claim",
                "citation_ids": [key],
            }
        ]
    )
    assert validate_citations(response, records) == [key]

    with pytest.raises(ValueError):
        validate_citations(response, {})

    with pytest.raises(ValueError):
        Synthesis(
            claims=[
                {
                    "text": "Claim",
                    "citation_ids": [],
                }
            ]
        )


def test_citation_requires_evidence_text():
    response = Synthesis(
        claims=[
            {
                "text": "Claim",
                "citation_ids": [FIXTURE_CITATION_ID],
            }
        ]
    )

    with pytest.raises(ValueError, match="no evidence text"):
        validate_citations(
            response,
            {
                FIXTURE_CITATION_ID: {
                    "text": "",
                }
            },
        )


def test_malformed_schema():
    with pytest.raises(ValueError):
        Synthesis.model_validate_json('{"answer":"invented"}')


def test_provider_abstraction_is_abstract():
    with pytest.raises(TypeError):
        LLMProvider()


def test_groq_initialization_does_not_require_key(settings):
    assert settings.groq_api_key.get_secret_value() == ""

    provider = GroqProvider(settings)

    assert isinstance(provider, LLMProvider)
    assert provider.name == "groq"
    assert provider.model == settings.groq_model


@pytest.mark.parametrize(
    "provider_name, expected_type",
    [
        ("groq", GroqProvider),
        ("ollama", OllamaProvider),
    ],
)
def test_provider_selection(settings, provider_name, expected_type):
    settings.llm_provider = provider_name

    provider = create_provider(settings)

    assert isinstance(provider, expected_type)
    assert isinstance(provider, LLMProvider)
    assert provider.name == provider_name


def test_invalid_provider_configuration_is_rejected():
    with pytest.raises(
        ValidationError,
        match="LLM_PROVIDER must be groq or ollama",
    ):
        Settings(
            _env_file=None,
            llm_provider="invalid",
        )


def test_factory_rejects_invalid_provider_even_without_settings_validation(
    settings,
):
    with pytest.raises(
        ProviderError,
        match="unsupported_provider",
    ):
        create_provider(
            settings,
            provider="invalid",
        )


def test_missing_groq_api_key(settings):
    with pytest.raises(ProviderError) as error:
        GroqProvider(settings).generate(
            "Explain the supplied risks.",
            fixture_evidence(),
            [],
        )

    assert error.value.category == "missing_api_key"
    assert error.value.provider == "groq"
    assert error.value.attempts == 0


def test_groq_key_is_masked_in_settings(settings):
    authorize_fixture(settings)

    assert FIXTURE_API_KEY not in repr(settings)
    assert FIXTURE_API_KEY not in settings.model_dump_json()


def test_successful_groq_response(settings, sdk_stub):
    authorize_fixture(settings)
    observed = sdk_stub([completion()])

    result = GroqProvider(settings).generate(
        "Explain the supplied risks.",
        fixture_evidence(),
        [],
    )

    assert result == fixture_synthesis()
    assert len(observed["requests"]) == 1
    assert observed["closed_clients"] == 1

    request = observed["requests"][0]
    client_configuration = observed["clients"][0]

    assert request["model"] == settings.groq_model
    assert request["stream"] is False
    assert request["max_completion_tokens"] == settings.llm_max_output_tokens
    assert request["response_format"]["type"] == "json_schema"
    assert request["response_format"]["json_schema"]["strict"] is True
    assert client_configuration["max_retries"] == 0

    serialized_prompt = json.dumps(request["messages"])
    assert FIXTURE_CITATION_ID in serialized_prompt
    assert FIXTURE_API_KEY not in serialized_prompt


def test_groq_model_and_base_url_configuration(settings, sdk_stub):
    authorize_fixture(settings)
    settings.groq_model = FIXTURE_MODEL
    settings.groq_base_url = "https://gateway.example/openai/v1"

    observed = sdk_stub([completion()])

    result, metadata = synthesize(
        settings,
        "Explain the supplied risks.",
        fixture_evidence(),
        [],
    )

    assert result == fixture_synthesis()
    assert observed["requests"][0]["model"] == FIXTURE_MODEL

    # Preserve the documented API endpoint in application configuration.
    assert settings.groq_base_url == "https://gateway.example/openai/v1"

    # The SDK adds /openai/v1 in its resource paths, so its constructor
    # receives only the origin. Request-path behavior is covered by
    # test_groq_endpoint_adapter.py using the real SDK and MockTransport.
    assert observed["clients"][0]["base_url"] == "https://gateway.example"

    assert metadata["provider"] == "groq"
    assert metadata["model"] == FIXTURE_MODEL
    assert metadata["fallback_used"] is False
    assert metadata["fallback"] is None


def test_environment_model_and_base_url_configuration(monkeypatch):
    monkeypatch.setenv("GROQ_MODEL", FIXTURE_MODEL)
    monkeypatch.setenv(
        "GROQ_BASE_URL",
        "https://gateway.example/openai/v1",
    )

    configured = Settings(_env_file=None)

    assert configured.groq_model == FIXTURE_MODEL
    assert configured.groq_base_url == ("https://gateway.example/openai/v1")


@pytest.mark.parametrize(
    "url",
    [
        "http://api.groq.com/openai/v1",
        "https://user:password@example.com/openai/v1",
        "https://api.groq.com/openai/v1?token=fixture",
        "https://api.groq.com/openai/v1#fragment",
        "not-a-url",
    ],
)
def test_invalid_groq_base_url_is_rejected(settings, url):
    authorize_fixture(settings)
    settings.groq_base_url = url

    with pytest.raises(ProviderError) as error:
        GroqProvider(settings).generate(
            "Explain the supplied risks.",
            fixture_evidence(),
            [],
        )

    assert error.value.category == "invalid_provider_configuration"


def test_transport_schema_preserves_local_validation():
    schema = provider_response_schema()

    assert schema["additionalProperties"] is False
    assert schema["$defs"]["Claim"]["additionalProperties"] is False

    text_schema = schema["$defs"]["Claim"]["properties"]["text"]
    assert "minLength" not in text_schema

    with pytest.raises(ValidationError):
        Synthesis(
            claims=[
                {
                    "text": "",
                    "citation_ids": [FIXTURE_CITATION_ID],
                }
            ]
        )


@pytest.mark.parametrize(
    "content, expected_category",
    [
        ("not JSON", "structured_output_validation_failed"),
        ('{"claims":[]}', "structured_output_validation_failed"),
        (
            '{"claims":[{"text":"Claim","citation_ids":[]}]}',
            "structured_output_validation_failed",
        ),
        (
            '{"answer":"An unsupported response object"}',
            "structured_output_validation_failed",
        ),
        ("", "malformed_response"),
    ],
)
def test_invalid_structured_output_does_not_retry(
    settings,
    sdk_stub,
    fake_clock,
    content,
    expected_category,
):
    authorize_fixture(settings)
    observed = sdk_stub([completion(content=content)])

    with pytest.raises(ProviderError) as error:
        GroqProvider(settings).generate(
            "Explain the supplied risks.",
            fixture_evidence(),
            [],
        )

    assert error.value.category == expected_category
    assert error.value.attempts == 1
    assert len(observed["requests"]) == 1
    assert fake_clock["sleeps"] == []


def test_truncated_completion_is_rejected(settings, sdk_stub):
    authorize_fixture(settings)
    observed = sdk_stub([completion(finish_reason="length")])

    with pytest.raises(ProviderError) as error:
        GroqProvider(settings).generate(
            "Explain the supplied risks.",
            fixture_evidence(),
            [],
        )

    assert error.value.category == "output_token_limit"
    assert len(observed["requests"]) == 1


def test_missing_completion_choices_is_rejected(settings, sdk_stub):
    authorize_fixture(settings)
    observed = sdk_stub([SimpleNamespace(choices=[])])

    with pytest.raises(ProviderError) as error:
        GroqProvider(settings).generate(
            "Explain the supplied risks.",
            fixture_evidence(),
            [],
        )

    assert error.value.category == "malformed_response"
    assert len(observed["requests"]) == 1


@pytest.mark.parametrize(
    "error_type",
    [APITimeoutError, APIConnectionError],
)
def test_transient_connection_errors_retry(
    settings,
    sdk_stub,
    fake_clock,
    error_type,
):
    authorize_fixture(settings)
    request = httpx.Request(
        "POST",
        "https://api.groq.com/openai/v1/chat/completions",
    )
    observed = sdk_stub(
        [
            error_type(request=request),
            completion(),
        ]
    )

    result = GroqProvider(settings).generate(
        "Explain the supplied risks.",
        fixture_evidence(),
        [],
    )

    assert result == fixture_synthesis()
    assert len(observed["requests"]) == 2
    assert fake_clock["sleeps"] == [1]


def test_rate_limit_then_success(settings, sdk_stub, fake_clock):
    authorize_fixture(settings)
    observed = sdk_stub(
        [
            status_error(429),
            completion(),
        ]
    )

    result = GroqProvider(settings).generate(
        "Explain the supplied risks.",
        fixture_evidence(),
        [],
    )

    assert result == fixture_synthesis()
    assert len(observed["requests"]) == 2
    assert fake_clock["sleeps"] == [1]


def test_retry_limit_and_exponential_backoff(
    settings,
    sdk_stub,
    fake_clock,
):
    authorize_fixture(settings)
    observed = sdk_stub(
        [
            status_error(503),
            status_error(503),
            status_error(503),
        ]
    )

    with pytest.raises(ProviderError) as error:
        GroqProvider(settings).generate(
            "Explain the supplied risks.",
            fixture_evidence(),
            [],
        )

    assert error.value.category == "provider_unavailable"
    assert error.value.attempts == 3
    assert len(observed["requests"]) == 3
    assert fake_clock["sleeps"] == [1, 2]


def test_retry_backoff_is_capped(settings, sdk_stub, fake_clock):
    authorize_fixture(settings)
    settings.llm_retry_max_backoff_seconds = 1

    observed = sdk_stub(
        [
            status_error(503),
            status_error(503),
            status_error(503),
        ]
    )

    with pytest.raises(ProviderError):
        GroqProvider(settings).generate(
            "Explain the supplied risks.",
            fixture_evidence(),
            [],
        )

    assert len(observed["requests"]) == 3
    assert fake_clock["sleeps"] == [1, 1]


def test_zero_retries_means_one_attempt(settings, sdk_stub, fake_clock):
    authorize_fixture(settings)
    settings.llm_max_retries = 0
    observed = sdk_stub([status_error(429)])

    with pytest.raises(ProviderError) as error:
        GroqProvider(settings).generate(
            "Explain the supplied risks.",
            fixture_evidence(),
            [],
        )

    assert error.value.category == "rate_limit"
    assert error.value.attempts == 1
    assert len(observed["requests"]) == 1
    assert fake_clock["sleeps"] == []


def test_total_budget_prevents_additional_retry(
    settings,
    sdk_stub,
    fake_clock,
):
    authorize_fixture(settings)
    settings.llm_total_timeout = 1
    observed = sdk_stub([status_error(503)])

    with pytest.raises(ProviderError):
        GroqProvider(settings).generate(
            "Explain the supplied risks.",
            fixture_evidence(),
            [],
        )

    assert len(observed["requests"]) == 1
    assert observed["clients"][0]["timeout"] == 1
    assert fake_clock["sleeps"] == []


@pytest.mark.parametrize(
    "status_code, category",
    [
        (400, "invalid_request"),
        (401, "authentication"),
        (403, "authentication"),
        (404, "model_or_endpoint_unavailable"),
        (422, "invalid_request"),
    ],
)
def test_permanent_http_error_does_not_retry(
    settings,
    sdk_stub,
    fake_clock,
    status_code,
    category,
):
    authorize_fixture(settings)
    observed = sdk_stub([status_error(status_code)])

    with pytest.raises(ProviderError) as error:
        GroqProvider(settings).generate(
            "Explain the supplied risks.",
            fixture_evidence(),
            [],
        )

    assert error.value.category == category
    assert error.value.attempts == 1
    assert len(observed["requests"]) == 1
    assert fake_clock["sleeps"] == []
    assert "fixture-sensitive-provider-body" not in str(error.value)
    assert FIXTURE_API_KEY not in str(error.value)


def test_fallback_disabled(settings, monkeypatch):
    assert settings.enable_llm_fallback is False
    fallback_calls = []

    def fail(*args):
        raise ProviderError(
            "provider_unavailable",
            provider="groq",
            model=settings.groq_model,
            attempts=3,
        )

    def unexpected_fallback(*args):
        fallback_calls.append(True)
        raise AssertionError("Fallback should be disabled")

    monkeypatch.setattr(GroqProvider, "generate", fail)
    monkeypatch.setattr(
        OllamaProvider,
        "generate",
        unexpected_fallback,
    )

    with pytest.raises(
        ProviderError,
        match="provider_unavailable",
    ):
        synthesize(
            settings,
            "Explain the supplied risks.",
            fixture_evidence(),
            [],
        )

    assert fallback_calls == []


def test_fallback_enabled(settings, monkeypatch):
    settings.enable_llm_fallback = True
    settings.ollama_model = FIXTURE_LOCAL_MODEL
    deadlines = []

    def fail(self, question, evidence, calculations):
        deadlines.append(self.deadline)
        raise ProviderError(
            "timeout",
            provider="groq",
            model=self.model,
            attempts=3,
        )

    def local_success(self, question, evidence, calculations):
        deadlines.append(self.deadline)
        return fixture_synthesis()

    monkeypatch.setattr(GroqProvider, "generate", fail)
    monkeypatch.setattr(
        OllamaProvider,
        "generate",
        local_success,
    )

    result, metadata = synthesize(
        settings,
        "Explain the supplied risks.",
        fixture_evidence(),
        [],
    )

    assert result == fixture_synthesis()
    assert metadata["provider"] == "ollama"
    assert metadata["model"] == FIXTURE_LOCAL_MODEL
    assert metadata["fallback_used"] is True
    assert metadata["fallback"]["original_provider"] == "groq"
    assert metadata["fallback"]["failure_category"] == "timeout"
    assert metadata["fallback"]["primary_attempts"] == 3
    assert deadlines[0] == deadlines[1]


def test_both_providers_fail(settings, monkeypatch):
    settings.enable_llm_fallback = True
    settings.ollama_model = FIXTURE_LOCAL_MODEL

    def hosted_failure(*args):
        raise ProviderError(
            "rate_limit",
            provider="groq",
            model=settings.groq_model,
            attempts=3,
        )

    def local_failure(*args):
        raise ProviderError(
            "provider_unavailable",
            provider="ollama",
            model=settings.ollama_model,
            attempts=3,
        )

    monkeypatch.setattr(
        GroqProvider,
        "generate",
        hosted_failure,
    )
    monkeypatch.setattr(
        OllamaProvider,
        "generate",
        local_failure,
    )

    with pytest.raises(ProviderError) as error:
        synthesize(
            settings,
            "Explain the supplied risks.",
            fixture_evidence(),
            [],
        )

    assert error.value.category == "primary_and_fallback_failed"
    assert error.value.provider == "ollama"
    assert error.value.fallback["original_provider"] == "groq"
    assert error.value.fallback["failure_category"] == "rate_limit"
    assert error.value.fallback["fallback_failure_category"] == ("provider_unavailable")


@pytest.mark.parametrize(
    "category",
    [
        "context_budget_exceeded",
        "invalid_provider_configuration",
    ],
)
def test_unsafe_fallback_categories_are_not_forwarded(
    settings,
    monkeypatch,
    category,
):
    settings.enable_llm_fallback = True

    def fail(*args):
        raise ProviderError(
            category,
            provider="groq",
            model=settings.groq_model,
        )

    def unexpected_fallback(*args):
        raise AssertionError("Fallback should not receive unsafe context")

    monkeypatch.setattr(GroqProvider, "generate", fail)
    monkeypatch.setattr(
        OllamaProvider,
        "generate",
        unexpected_fallback,
    )

    with pytest.raises(ProviderError) as error:
        synthesize(
            settings,
            "Explain the supplied risks.",
            fixture_evidence(),
            [],
        )

    assert error.value.category == category


def test_ollama_primary_provider_metadata(settings, monkeypatch):
    settings.llm_provider = "ollama"
    settings.ollama_model = FIXTURE_LOCAL_MODEL

    monkeypatch.setattr(
        OllamaProvider,
        "generate",
        lambda *args: fixture_synthesis(),
    )

    result, metadata = synthesize(
        settings,
        "Explain the supplied risks.",
        fixture_evidence(),
        [],
    )

    assert result == fixture_synthesis()
    assert metadata["provider"] == "ollama"
    assert metadata["model"] == FIXTURE_LOCAL_MODEL
    assert metadata["fallback_used"] is False
    assert metadata["fallback"] is None
    assert configured_model(settings) == FIXTURE_LOCAL_MODEL


def test_ollama_missing_model(settings):
    with pytest.raises(ProviderError) as error:
        OllamaProvider(settings).generate(
            "Explain the supplied risks.",
            fixture_evidence(),
            [],
        )

    assert error.value.category == "missing_ollama_model"
    assert error.value.provider == "ollama"


def test_ollama_http_response_is_validated(settings, monkeypatch):
    settings.ollama_model = FIXTURE_LOCAL_MODEL
    calls = []

    class FakeHTTPClient:
        def __init__(self, **kwargs):
            self.configuration = kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def post(self, url, json):
            calls.append(
                {
                    "url": url,
                    "payload": json,
                }
            )
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={
                    "done": True,
                    "done_reason": "stop",
                    "message": {
                        "content": fixture_synthesis().model_dump_json(),
                    },
                },
            )

    monkeypatch.setattr(
        providers.httpx,
        "Client",
        FakeHTTPClient,
    )

    result = OllamaProvider(settings).generate(
        "Explain the supplied risks.",
        fixture_evidence(),
        [],
    )

    assert result == fixture_synthesis()
    assert len(calls) == 1
    assert calls[0]["url"] == "http://localhost:11434/api/chat"
    assert calls[0]["payload"]["model"] == FIXTURE_LOCAL_MODEL
    assert calls[0]["payload"]["stream"] is False
    assert calls[0]["payload"]["options"]["num_ctx"] == (
        settings.ollama_context_window_tokens
    )
