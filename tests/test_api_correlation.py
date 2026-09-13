"""Offline ASGI and transport tests. No running servers or external calls."""

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from core.schemas import Query
from tests.financial_fixtures import publish_synthetic_financials


def test_query_scope_limits():
    with pytest.raises(ValidationError):
        Query(
            question="What was revenue?",
            tickers=["AAPL"] * 4,
        )

    with pytest.raises(ValidationError):
        Query(question="     ")

    query = Query(
        question="  What was revenue?  ",
        tickers=["AAPL", "AAPL"],
        years=[2024, 2023, 2024],
    )

    assert query.question == "What was revenue?"
    assert query.tickers == ["AAPL"]
    assert query.years == [2023, 2024]


def test_internal_header_body_and_evidence_share_request_id(
    settings,
    monkeypatch,
):
    import ai_service.main as module

    publish_synthetic_financials(settings)
    monkeypatch.setattr(module, "settings", settings)
    request_id = "a" * 32

    with TestClient(module.app) as client:
        response = client.post(
            "/internal/rag/query",
            headers={"X-Request-ID": request_id},
            json={"question": "What was Apple's revenue in FY2024?"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert response.headers["X-Request-ID"] == request_id
    assert payload["request_id"] == request_id
    assert not payload["abstained"]
    assert all(
        item["evidence_id"].startswith(f"EVIDENCE_{request_id}_")
        for item in payload["evidence"]
    )


def test_invalid_private_request_id_is_replaced(settings, monkeypatch):
    import ai_service.main as module

    monkeypatch.setattr(module, "settings", settings)

    with TestClient(module.app) as client:
        response = client.post(
            "/internal/rag/query",
            headers={"X-Request-ID": "not-a-valid-request-id"},
            json={"question": "What was Apple's revenue in FY2030?"},
        )

    assert response.status_code == 200
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    assert len(response.headers["X-Request-ID"]) == 32


def test_public_backend_owns_request_id(settings, monkeypatch):
    import backend.app.main as module
    from ai_service.orchestrator import ResearchEngine

    monkeypatch.setattr(module, "settings", settings)

    async def mock_internal(path, body=None):
        return ResearchEngine(settings).query(Query(**body)).model_dump()

    monkeypatch.setattr(module, "internal", mock_internal)

    with TestClient(module.app) as client:
        response = client.post(
            "/api/research",
            headers={"X-Request-ID": "b" * 32},
            json={"question": "What was Apple's revenue in FY2030?"},
        )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != "b" * 32
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


def test_mismatched_upstream_request_id_rejected(settings, monkeypatch):
    import backend.app.main as module

    monkeypatch.setattr(module, "settings", settings)

    async def mock_internal(path, body=None):
        return {"request_id": "c" * 32}

    monkeypatch.setattr(module, "internal", mock_internal)

    with TestClient(module.app) as client:
        response = client.post(
            "/api/research",
            json={"question": "What was Apple's revenue in FY2024?"},
        )

    assert response.status_code == 502
    assert "mismatched request identifier" in response.json()["detail"]


@pytest.mark.parametrize(
    "upstream_status,expected_status",
    [(503, 503), (504, 504), (422, 422), (302, 502), (500, 502)],
)
def test_safe_upstream_status_mapping(
    settings,
    monkeypatch,
    upstream_status,
    expected_status,
):
    import backend.app.main as module

    original_client = httpx.AsyncClient

    def handler(request):
        assert len(request.headers["X-Request-ID"]) == 32
        return httpx.Response(
            upstream_status,
            text="synthetic private upstream diagnostic",
        )

    def client_factory(**kwargs):
        return original_client(
            **kwargs,
            transport=httpx.MockTransport(handler),
        )

    monkeypatch.setattr(module, "settings", settings)
    monkeypatch.setattr(module.httpx, "AsyncClient", client_factory)

    with TestClient(module.app) as client:
        response = client.get("/api/system/status")

    assert response.status_code == expected_status
    assert "private upstream diagnostic" not in response.text
    assert response.headers["X-Request-ID"]


def test_upstream_size_limit(settings, monkeypatch):
    import backend.app.main as module

    original_client = httpx.AsyncClient

    def client_factory(**kwargs):
        return original_client(
            **kwargs,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=b"x" * 100)
            ),
        )

    monkeypatch.setattr(module, "settings", settings)
    monkeypatch.setattr(module, "MAX_UPSTREAM_BYTES", 20)
    monkeypatch.setattr(module.httpx, "AsyncClient", client_factory)

    with TestClient(module.app) as client:
        response = client.get("/api/system/status")

    assert response.status_code == 502
    assert "supported size" in response.json()["detail"]
