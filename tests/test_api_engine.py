import pytest
from fastapi.testclient import TestClient

from ai_service.orchestrator import ResearchEngine
from core.schemas import Query
from tests.financial_fixtures import publish_synthetic_financials


def test_structured_without_llm(settings):
    publish_synthetic_financials(settings)

    result = ResearchEngine(settings).query(
        Query(question="What was Apple's revenue in 2024?")
    )

    assert not result.abstained
    assert result.provider is None
    assert result.grounded
    assert result.evidence[0]["concept"] == "Revenues"
    assert result.facts[0]["value"] == "100"


@pytest.mark.parametrize(
    "question",
    [
        "What was Apple's revenue in 2024?",
        "What was Apple's revenue in 2030?",
        "What was Tesla's revenue in 2024?",
        "What will Apple's stock price be in 2027?",
        "What risks did Amazon identify in 2024?",
    ],
)
def test_unavailable_abstains(settings, question):
    result = ResearchEngine(settings).query(Query(question=question))

    assert result.abstained and not result.grounded
    assert result.abstention_reason


def test_backend_endpoints(settings, monkeypatch):
    import backend.app.main as module

    monkeypatch.setattr(module, "settings", settings)

    with TestClient(module.app) as client:
        assert client.get("/api/health").status_code == 200
        assert len(client.get("/api/companies").json()) == 3
        assert len(client.get("/api/reports").json()) == 9
        assert client.get("/api/analytics").json()["rows"] == []
        assert client.get("/api/evaluation").json()["status"] == "completed"
        assert client.get("/api/evidence/unknown").status_code == 404
        assert client.post("/api/research", json={"question": "x"}).status_code == 422

        async def mock(path, body=None):
            return ResearchEngine(settings).query(Query(**body)).model_dump()

        monkeypatch.setattr(module, "internal", mock)

        for endpoint in ["research", "compare"]:
            response = client.post(
                "/api/" + endpoint,
                json={"question": "What was Apple's revenue in 2030?"},
            )
            assert response.status_code == 200
            assert response.json()["abstained"]
            assert response.headers["X-Request-ID"]


def test_internal_api(settings, monkeypatch):
    import ai_service.main as module

    monkeypatch.setattr(module, "settings", settings)

    with TestClient(module.app) as client:
        assert client.get("/internal/health").status_code == 200
        assert not client.get("/internal/status").json()["index_present"]

        response = client.post(
            "/internal/rag/query",
            json={"question": "What was Apple's revenue in 2030?"},
        )

        assert response.json()["abstained"]


def test_narrative_unknown_citation_abstains(settings, monkeypatch):
    from types import SimpleNamespace

    import ai_service.orchestrator as module
    from core.schemas import Synthesis

    engine = ResearchEngine(settings)
    engine.store.data["corpus_version"] = "fixture"
    engine.retriever = SimpleNamespace(
        manifest={"corpus_version": "fixture"},
        retrieve=lambda *args: (
            [
                {
                    "text": "Supply risks exist.",
                    "ticker": "AMZN",
                    "fiscal_year": 2024,
                }
            ],
            {},
        ),
    )
    monkeypatch.setattr(
        module,
        "synthesize",
        lambda *args: (
            Synthesis(
                claims=[
                    {
                        "text": "Supply risks exist.",
                        "citation_ids": ["unknown"],
                    }
                ]
            ),
            {
                "provider": "fixture",
                "model": "fixture",
                "fallback_used": False,
            },
        ),
    )

    answer = engine.query(Query(question="What risks did Amazon identify in 2024?"))

    assert answer.abstained
    assert "citation" in answer.abstention_reason.lower()
