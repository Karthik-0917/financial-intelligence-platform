"""Public API transport.

The browser accesses this service only. Retrieval and generation remain
inside the private AI service. Financial analytics read validated local
artifacts and do not invoke a language model.
"""

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import FastAPI, HTTPException
from fastapi import Path as APIPath
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from ai_service.citations.registry import Registry
from ai_service.financial.store import FinancialStore
from core.config import COMPANIES, Settings
from core.request_context import RequestContextMiddleware, get_request_id
from core.schemas import Query, Response
from core.storage import read_json

settings = Settings()
MAX_UPSTREAM_BYTES = 2 * 1024 * 1024


@asynccontextmanager
async def lifespan(app):
    app.state.client = httpx.AsyncClient(
        base_url=settings.ai_service_url,
        timeout=httpx.Timeout(
            settings.request_timeout + 15,
            connect=min(10, settings.request_timeout),
        ),
        limits=httpx.Limits(
            max_connections=10,
            max_keepalive_connections=5,
        ),
        follow_redirects=False,
    )
    try:
        yield
    finally:
        await app.state.client.aclose()


app = FastAPI(
    title="Financial Intelligence Platform",
    version="0.1.0",
    lifespan=lifespan,
)

if "*" in settings.cors_origins:
    raise ValueError("Configure explicit frontend CORS origins, not '*'")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID", "Retry-After"],
)
app.add_middleware(
    RequestContextMiddleware,
    service="backend",
    accept_request_id=False,
)


async def internal(path, body=None):
    """Bound upstream reads and avoid exposing upstream response bodies."""
    method = "POST" if body is not None else "GET"
    kwargs = {"json": body} if body is not None else {}

    try:
        async with app.state.client.stream(
            method,
            path,
            headers={"X-Request-ID": get_request_id()},
            **kwargs,
        ) as response:
            if response.status_code == 503:
                raise HTTPException(
                    503,
                    "AI service unavailable or busy; retry shortly",
                    headers={"Retry-After": "2"},
                )

            if response.status_code in {408, 504}:
                raise HTTPException(504, "AI service timed out")

            if response.status_code in {400, 422}:
                raise HTTPException(
                    422,
                    "AI service rejected the research request",
                )

            if response.status_code != 200:
                raise HTTPException(502, "Unexpected AI service response")

            content = bytearray()

            async for chunk in response.aiter_bytes():
                if len(content) + len(chunk) > MAX_UPSTREAM_BYTES:
                    raise HTTPException(
                        502,
                        "AI service response exceeded the supported size",
                    )
                content.extend(chunk)

        payload = json.loads(content)

        if not isinstance(payload, dict):
            raise HTTPException(502, "Invalid AI service response")

        return payload
    except httpx.TimeoutException:
        raise HTTPException(504, "AI service timed out") from None
    except httpx.HTTPError:
        raise HTTPException(503, "AI service unavailable") from None
    except (ValueError, UnicodeError):
        raise HTTPException(502, "Invalid AI service response") from None


def _research_response(payload):
    try:
        result = Response.model_validate(payload)
    except ValidationError:
        raise HTTPException(
            502,
            "AI service returned an invalid research response",
        ) from None

    if result.request_id != get_request_id():
        raise HTTPException(
            502,
            "AI service returned a mismatched request identifier",
        )

    if result.abstained and result.grounded:
        raise HTTPException(
            502,
            "AI service returned inconsistent answer validation",
        )

    evidence_ids = [item.get("evidence_id") for item in result.evidence]

    if any(not isinstance(identifier, str) for identifier in evidence_ids):
        raise HTTPException(502, "AI service returned invalid evidence identifiers")

    if len(set(evidence_ids)) != len(evidence_ids):
        raise HTTPException(502, "AI service returned duplicate evidence identifiers")

    prefix = f"EVIDENCE_{result.request_id}_"

    if any(not identifier.startswith(prefix) for identifier in evidence_ids):
        raise HTTPException(502, "AI service returned cross-request evidence")

    if any(identifier not in evidence_ids for identifier in result.citation_ids):
        raise HTTPException(502, "AI service returned unknown citation identifiers")

    return result


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "backend",
        "health_scope": "liveness",
    }


@app.get("/api/system/status")
async def status():
    payload = await internal("/internal/status")

    if payload.get("status_scope") != "local_readiness":
        raise HTTPException(502, "AI service returned an invalid status response")

    return payload


@app.get("/api/companies")
def companies():
    return COMPANIES


@app.get("/api/reports")
def reports():
    try:
        manifest = read_json(settings.data_dir / "processed/corpus_manifest.json")

        if manifest is None:
            manifest = read_json(
                Path("configs/corpus.expected.json"),
                [],
            )

        if not isinstance(manifest, list) or any(
            not isinstance(report, dict) for report in manifest
        ):
            raise ValueError("Invalid report manifest")

        return manifest
    except (OSError, ValueError):
        raise HTTPException(503, "Report manifest is unavailable or invalid") from None


@app.post("/api/research", response_model=Response)
async def research(body: Query):
    payload = await internal("/internal/rag/query", body.model_dump())
    return _research_response(payload)


@app.post("/api/compare", response_model=Response)
async def compare(body: Query):
    payload = await internal("/internal/rag/compare", body.model_dump())
    return _research_response(payload)


@app.get("/api/evidence/{evidence_id}")
def evidence(
    evidence_id: Annotated[str, APIPath(min_length=1, max_length=100)],
):
    try:
        record = Registry(settings.data_dir / "processed/evidence.sqlite").get(
            evidence_id
        )
    except (OSError, ValueError):
        raise HTTPException(503, "Evidence store is unavailable") from None

    if not record:
        raise HTTPException(404, "Evidence not found")

    return record


@app.get("/api/analytics")
def analytics():
    try:
        return FinancialStore(settings).analytics()
    except (OSError, ValueError):
        raise HTTPException(
            503,
            "Financial artifacts failed validation; inspect offline ingestion",
        ) from None


@app.get("/api/evaluation")
def evaluation():
    try:
        result = read_json(
            Path("evaluation/results/latest.json"),
            {"status": "not_yet_evaluated", "metrics": None},
        )

        if not isinstance(result, dict):
            raise ValueError("Invalid evaluation artifact")

        return result
    except (OSError, ValueError):
        raise HTTPException(
            503,
            "Evaluation artifact is unavailable or invalid",
        ) from None
