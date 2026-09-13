# Automated Financial Report Analysis using Retrieval-Augmented Generation (RAG)

## Financial Intelligence Platform

**AI-powered financial research, document intelligence and evidence-based analysis**

A financial research workspace for Apple, Microsoft, and Amazon original
Form 10-K filings for fiscal years 2022–2024.

The platform combines:

- SEC EDGAR primary-source documents.
- Validated Company Facts financial inputs.
- Python Decimal calculations.
- Hybrid FAISS and BM25 retrieval.
- Reciprocal Rank Fusion and cross-encoder reranking.
- Groq narrative synthesis.
- Application-controlled evidence and citations.
- Explicit abstention and financial availability states.
- Artifact-backed evaluation.

It is not a stock-price prediction tool or investment adviser.

## Verification status

The redesigned implementation was delivered in Response Mode.

**Not executed in this environment.**

Before the UI redesign, the user supplied local evidence of:

- Nine acquired and published filings.
- A matching index with 2,342 chunks and 768-dimensional embeddings.
- 87 accepted financial facts and 12 unresolved base-metric slots.
- Runtime financial analytics returning all nine company/year rows.
- 443 strict socket-blocked tests passing after the date-parser repair.
- 38 API/provider tests passing in a separate restricted-loopback Windows run.
- A successful frontend build before this redesign.

These are historical, user-observed results. They are not verification of the
new frontend, live narrative retrieval, Groq authentication, or evaluation.

See [verification](docs/verification.md).

## Supported corpus

| Company | Ticker | SEC CIK | Fiscal years |
|---|---|---|---|
| Apple | AAPL | 0000320193 | 2022, 2023, 2024 |
| Microsoft | MSFT | 0000789019 | 2022, 2023, 2024 |
| Amazon | AMZN | 0001018724 | 2022, 2023, 2024 |

Actual source identity comes from SEC metadata and filing validation.
Expected corpus slots are not proof of acquisition.

Original 10-K filings are selected; 10-K/A amendments are excluded.
Filing date and fiscal year remain separate.

## Architecture

Exactly three runtime application services:

~~~text
React frontend
    ↓
Public FastAPI backend
    ↓
Internal AI/RAG service
    ├─ validated financial store → Python calculations
    └─ scoped retrieval → reranking → evidence → Groq synthesis
~~~

The browser calls the public backend only.

Groq is an external hosted API. Optional Ollama is external to the
three-service Compose deployment.

### Offline document pipeline

~~~text
SEC submissions and official HTML/iXBRL
    → filing identity validation
    → text extraction and normalization
    → source-linked chunks
    → BGE embeddings
    → FAISS + persisted BM25
~~~

### Offline financial pipeline

~~~text
SEC Company Facts
    → exact annual fact resolution
    → unit, period, accession, and sign validation
    → inline-XBRL reconciliation
    → persisted financial store
~~~

Runtime queries do not fetch SEC data or rebuild indexes.

## Financial methodology

The resolver checks exact company, CIK, accession, form, fiscal focus, period,
concept, and unit.

Annual duration facts span 350–380 days. Instant facts have no start date.

Accepted facts require exact same-scope inline-XBRL agreement under the
implemented reconciliation policy. Conflicts and unresolved observations are
not silently overwritten.

The inline extractor supports selected namespace and numeric transformation
forms. It is not a complete XBRL processor or statement-layout auditor.

Company Facts values are already scaled.

CapEx uses a nonnegative outflow magnitude. Free cash flow is operating cash
flow minus CapEx.

Python Decimal arithmetic provides growth, CAGR, margins, and free cash flow.
The LLM does not perform authoritative financial arithmetic.

Charts use browser number precision for display. Exact source strings and
calculation inputs remain available for inspection.

## Known financial coverage gaps

The latest user-supplied artifact inspection reported:

- Apple cash unavailable in all three years because reconciliation was blocked.
- Amazon gross profit, liabilities, and CapEx unavailable in all three years
  under the current resolver.
- Amazon free cash flow and FCF margin consequently unavailable.
- FY2022 year-over-year growth unavailable because FY2021 is outside scope.

These observations do not establish that Amazon lacks the information in its
filings. Candidate mappings, original observations, and rejection reasons need
further source-level investigation.

The UI must display unavailable values with explanations, not zeros or
substitute metrics.

## Retrieval and generation

| Component | Default |
|---|---|
| Embedding model | BAAI/bge-base-en-v1.5 |
| Reranker | BAAI/bge-reranker-base |
| Dense candidates per scope group | 20 |
| Positive BM25 candidates per group | 20 |
| RRF constant | 60 |
| Rerank shortlist per group | 8 |
| Final context limit | 6 |
| Chunk target / overlap | 700 / 100 tokens |
| Reranker threshold | 0.35 |
| Hosted provider | Groq |
| Hosted model | openai/gpt-oss-120b |

Embedding windows avoid sending an entire oversized source chunk through the
shorter model input window.

Relevance scores are not answer-confidence probabilities.

Supported numerical questions use the financial store directly. Narrative
questions use retrieval and synthesis. Mixed questions retain separate
financial and narrative responsibilities.

Base models remain defaults. No Base/Large benchmark result is claimed.

## Evidence and safety

Citation IDs are application-controlled and resolve to persisted evidence.

Evidence identifies a supporting passage or fact. A source identifies its
originating filing or SEC dataset.

Unknown and out-of-context citation IDs are rejected.
Retrieved documents are untrusted input, not application instructions.

Citation-ID validity is not semantic entailment. Narrative support is not
independently verified merely because IDs pass validation.

Technical execution metadata remains available but is secondary to the answer.

## Product pages

- **Overview:** research composer, company snapshot, coverage, capability state.
- **Research:** answer-first results, findings, calculations, and evidence.
- **Compare:** selected-year chart, exact values, availability, and source lineage.
- **Filings:** searchable inventory and filing provenance.
- **Financials:** income, margins, cash flow, and balance-sheet analysis.
- **Evidence:** persisted ID lookup and records opened during the session.
- **Evaluation:** actual artifacts, denominators, outcomes, and review limitations.
- **Methodology:** pipeline explanation and separate capability status.

Workspace search covers pages and loaded filing metadata.
It is not full-text corpus search.

Research and comparison retain in-session state during page navigation.
A browser reload does not preserve that state.

See [UI redesign](docs/ui-redesign.md).

## Installation

Python 3.12 and Node 22 are recommended.

For a new Windows installation:

~~~powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -e ".[ml]"
npm ci --prefix frontend
~~~

Existing users do not need to reinstall models or dependencies solely because
of this UI redesign. No new frontend dependency was introduced.

## Private environment

Create `.env` only if absent:

~~~powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
~~~

Edit the file privately.

~~~dotenv
LLM_PROVIDER=groq
GROQ_API_KEY=
GROQ_BASE_URL=https://api.groq.com/openai/v1
GROQ_MODEL=openai/gpt-oss-120b
ENABLE_LLM_FALLBACK=false

SEC_CONTACT_EMAIL=
SEC_USER_AGENT=
~~~

SEC acquisition requires a genuine contact and identifying User-Agent.
Public EDGAR APIs do not require an SEC API key.

For separate local Python services:

~~~dotenv
AI_SERVICE_URL=http://127.0.0.1:8001
BACKEND_URL=http://127.0.0.1:8000
~~~

Keep fallback disabled until an external Ollama server and suitable model are
deliberately configured.

Key presence is not proof of Groq authentication.

## Frontend configuration

By default, the browser uses same-origin `/api`.

Optional `frontend/.env.local` configuration:

~~~dotenv
VITE_API_BASE_URL=/api
DEV_API_PROXY_TARGET=http://127.0.0.1:8000
~~~

Vite exposes `VITE_*` values publicly at build time. Never put secrets in them.

The proxy target is used by the development server, not directly by the browser.
For a nonlocal development hostname, configure `DEV_ALLOWED_HOSTS` explicitly.

Production should normally retain same-origin `/api` behind nginx.
A different public API origin also requires compatible CORS and deployment
security policy; changing an environment variable alone is insufficient.

## Models and initial artifacts

Skip this section if compatible models and artifacts already exist.

Prepare the default public model repositories:

~~~powershell
$env:HF_HOME = Join-Path $PWD "models/huggingface"
$env:HF_HUB_CACHE = Join-Path $PWD "models/huggingface/hub"
$env:HF_HUB_OFFLINE = "0"
$env:TRANSFORMERS_OFFLINE = "0"

.\.venv\Scripts\python.exe -c "from huggingface_hub import snapshot_download; repos = ('BAAI/bge-base-en-v1.5', 'BAAI/bge-reranker-base'); [snapshot_download(repo_id=repo) for repo in repos]"

$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
~~~

Downloading models is not inference verification. Revisions are not fully
runtime-pinned by this command.

Stop services before publishing artifacts:

~~~powershell
.\.venv\Scripts\python.exe -m ingestion.pipeline
~~~

Index-only construction from a compatible published corpus:

~~~powershell
.\.venv\Scripts\python.exe -m ingestion.index
~~~

Inspect `data/processed/ingestion_run.json`.
Individual artifact writes are atomic; the complete publication is not one
filesystem transaction.

A UI or provider-only change does not justify rebuilding compatible artifacts.

## Run locally

Use separate terminals from the repository root.

AI service:

~~~powershell
$env:HF_HOME = Join-Path $PWD "models/huggingface"
$env:HF_HUB_CACHE = Join-Path $PWD "models/huggingface/hub"
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"

.\.venv\Scripts\python.exe -m uvicorn ai_service.main:app --host 127.0.0.1 --port 8001
~~~

Backend:

~~~powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
~~~

Frontend:

~~~powershell
npm run dev --prefix frontend -- --port 5173
~~~

Open `http://localhost:5173`.

The backend schema documentation is at `http://127.0.0.1:8000/docs`.

## Public API

| Method | Endpoint |
|---|---|
| GET | `/api/health` |
| GET | `/api/system/status` |
| GET | `/api/companies` |
| GET | `/api/reports` |
| POST | `/api/research` |
| POST | `/api/compare` |
| GET | `/api/evidence/{evidence_id}` |
| GET | `/api/analytics` |
| GET | `/api/evaluation` |

Internal endpoints remain `/internal/health`, `/internal/status`,
`/internal/rag/query`, and `/internal/rag/compare`.

Liveness is not retrieval readiness.
Configured is not authenticated.
Built is not loaded.
Available data is not complete coverage.
No evaluation artifact means no measured evaluation score.

## Verification commands

~~~powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m black --check .
npm run build --prefix frontend
~~~

Windows requires the documented test split because asyncio uses a loopback
socket pair:

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q `
    --ignore=tests/test_api_correlation.py `
    --ignore=tests/test_api_engine.py `
    --ignore=tests/test_provider_trace_status.py `
    --disable-socket `
    --allow-unix-socket `
    --tb=short

.\.venv\Scripts\python.exe -m pytest -q `
    tests/test_api_correlation.py `
    tests/test_api_engine.py `
    tests/test_provider_trace_status.py `
    --allow-hosts=127.0.0.1,::1 `
    --allow-unix-socket `
    --tb=short
~~~

The API group allows loopback connections; it is not identical to strict
socket blocking. Provider and HTTP mocks remain required.

There is no new frontend browser/unit-test framework in this redesign.
Type checking, production build, and the manual browser matrix are required.

## Evaluation

Prepare actual references:

~~~powershell
.\.venv\Scripts\python.exe -m evaluation.prepare
~~~

Run structured evaluation:

~~~powershell
.\.venv\Scripts\python.exe -m evaluation.run --dataset evaluation/resolved.json
~~~

Retrieval labels require genuine artifact-bound review. See
[evaluation](docs/evaluation.md) before running reviewed retrieval or
potentially paid generation modes.

No evaluation score or manual-review completion is claimed by this redesign.

## Docker

The existing deployment retains exactly three services and a production nginx
frontend. It does not use the Vite development server in production.

~~~powershell
docker compose config --quiet
docker compose up --build -d
docker compose ps
~~~

Compatible data, indexes, model caches, and writable evidence storage must be
mounted as described in [deployment](docs/deployment.md).

Do not publish the AI service directly or bake secrets into images.

## Final Screenshots — Add After Local Verification

Capture genuine screenshots after testing the redesigned application locally.

Recommended captures:

- Overview with actual corpus coverage.
- Deterministic research with source evidence.
- Narrative research with its actual provider outcome.
- Comparison showing correct fiscal-year scope.
- Financials with an explicit missing metric.
- Evidence provenance.
- Actual evaluation state.

Do not use historical screenshots as proof of this redesign.
No new screenshots were captured in this environment.

## Limitations

- Financial coverage gaps remain under investigation.
- HTML extraction and inline transformation support are incomplete.
- Computed CSS visibility and statement layout are not independently audited.
- Semantic grounding is not established by citation-ID validation.
- Model revisions and dependencies are not fully pinned.
- Multi-file publication is nontransactional.
- Browser cancellation does not guarantee server/provider cancellation.
- Retry behavior can incur another provider charge after a lost response.
- Evidence session search is not full-corpus search.
- Some frontend validation remains partial rather than a generated schema.
- Responsive, accessibility, and live API compatibility need local verification.
- No mandatory authentication was added; deploy within a trusted perimeter.

## Documentation

[Architecture](docs/architecture.md) ·
[Ingestion](docs/ingestion.md) ·
[Retrieval](docs/retrieval.md) ·
[Financial metrics](docs/financial-metrics.md) ·
[Citations](docs/citations.md) ·
[Evaluation](docs/evaluation.md) ·
[Deployment](docs/deployment.md) ·
[Troubleshooting](docs/troubleshooting.md) ·
[UI redesign](docs/ui-redesign.md) ·
[Verification](docs/verification.md)

## License and attribution

Project license: MIT; see `LICENSE`.

Author identity has not been supplied.

SEC EDGAR is the primary data source. This project does not imply ownership
of SEC filings or affiliation with the SEC.

Downloaded model repositories have their own license and usage conditions.
Consult the actual model cards and license files for the downloaded revisions
before redistribution or deployment. No new license verification was performed
during this redesign.
