"""Private AI transport with correlated requests and local readiness."""

import logging
from contextlib import asynccontextmanager
from threading import Lock

from fastapi import FastAPI, HTTPException

from ai_service.orchestrator import ResearchEngine
from ai_service.readiness import (
    build_status,
)
from ai_service.readiness import (
    provider_configuration as describe_provider_configuration,
)
from ai_service.routing import classify
from core.config import Settings
from core.request_context import RequestContextMiddleware
from core.schemas import Query, Response

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s %(message)s",
)

settings = Settings()
lock = Lock()


@asynccontextmanager
async def lifespan(app):
    app.state.engine = ResearchEngine(settings)
    yield


app = FastAPI(
    title="Financial Intelligence Internal AI",
    lifespan=lifespan,
)
app.add_middleware(
    RequestContextMiddleware,
    service="ai-service",
    accept_request_id=True,
)


def provider_configuration():
    return describe_provider_configuration(settings)


@app.get("/internal/health")
def health():
    return {
        "status": "ok",
        "service": "ai-service",
        "health_scope": "liveness_and_static_provider_configuration",
        **provider_configuration(),
    }


@app.get("/internal/status")
def status():
    return build_status(settings, app.state.engine)


def _needs_rag_lock(body: Query) -> bool:
    """Financial-only queries are deterministic and should not block on RAG lock."""
    try:
        route = classify(body)
        return route.path in {"rag", "mixed"}
    except Exception:
        return True


@app.post("/internal/rag/query", response_model=Response)
@app.post("/internal/rag/compare", response_model=Response)
def query(body: Query):
    needs_lock = _needs_rag_lock(body)

    if not needs_lock:
        return app.state.engine.query(body)

    if not lock.acquire(blocking=False):
        acquired = lock.acquire(blocking=True, timeout=3)
        if not acquired:
            raise HTTPException(
                status_code=503,
                detail="Research worker busy; retry shortly",
                headers={"Retry-After": "2"},
            )

    try:
        return app.state.engine.query(body)
    finally:
        if lock.locked():
            lock.release()