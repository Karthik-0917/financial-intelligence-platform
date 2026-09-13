
# Automated Financial Report Analysis using Retrieval-Augmented Generation (RAG)

## Financial Intelligence Platform

> **AI-powered financial research, document intelligence, and evidence-based analysis for SEC filings.**

A full-stack financial intelligence platform that combines **Retrieval-Augmented Generation (RAG)**, structured SEC financial data, deterministic financial calculations, hybrid search, cross-encoder reranking, and application-controlled evidence to analyze annual reports from **Apple, Microsoft, and Amazon**.

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![React](https://img.shields.io/badge/React-TypeScript-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Backend-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![RAG](https://img.shields.io/badge/AI-RAG-7B61FF)](#retrieval-pipeline)
[![FAISS](https://img.shields.io/badge/Retrieval-FAISS-0468FF)](#retrieval-pipeline)
[![SEC EDGAR](https://img.shields.io/badge/Data-SEC%20EDGAR-003968)](https://www.sec.gov/edgar)
[![CI](https://img.shields.io/github/actions/workflow/status/Karthik-0917/financial-intelligence-platform/ci.yml?label=CI)](https://github.com/Karthik-0917/financial-intelligence-platform/actions)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## Table of Contents

- [Overview](#overview)
- [Why This Project](#why-this-project)
- [Key Features](#key-features)
- [Supported Corpus](#supported-corpus)
- [Product Walkthrough](#product-walkthrough)
- [Architecture](#architecture)
- [Data Pipeline](#data-pipeline)
- [Financial Data Pipeline](#financial-data-pipeline)
- [Financial Calculation Methodology](#financial-calculation-methodology)
- [Retrieval Pipeline](#retrieval-pipeline)
- [Evidence and Citation Architecture](#evidence-and-citation-architecture)
- [Query Responsibilities](#query-responsibilities)
- [Technology Stack](#technology-stack)
- [Project Structure](#project-structure)
- [Installation](#installation)
- [Environment Configuration](#environment-configuration)
- [Models and Initial Artifacts](#models-and-initial-artifacts)
- [Running Locally](#running-locally)
- [API](#api)
- [Evaluation](#evaluation)
- [Verification](#verification)
- [Docker Deployment](#docker-deployment)
- [Data Coverage and Limitations](#data-coverage-and-limitations)
- [Security and Responsible Use](#security-and-responsible-use)
- [Documentation](#documentation)
- [Future Improvements](#future-improvements)
- [Author](#author)
- [License](#license)

---

# Overview

Financial reports contain large amounts of structured and unstructured information distributed across financial statements, tables, business descriptions, risk factors, management discussions, cybersecurity disclosures, and other filing sections.

This project combines two complementary approaches:

- **Structured financial analysis** for exact numerical metrics and calculations.
- **Retrieval-Augmented Generation (RAG)** for narrative questions requiring contextual evidence from filings.

The system deliberately separates these responsibilities so that the LLM is **not responsible for authoritative financial arithmetic, source identity, or financial fact selection**.

### Core Principles

- SEC EDGAR as the primary filing source
- Structured financial facts validated before use
- Python-based deterministic financial calculations
- Hybrid dense + lexical retrieval
- Reciprocal Rank Fusion
- Cross-encoder reranking
- Application-controlled evidence and citation IDs
- Explicit handling of unavailable financial data
- Abstention for unsupported questions
- Artifact-backed evaluation
- No stock-price prediction or investment advice

---

# Why This Project

Traditional financial dashboards are effective at displaying numbers but often provide limited context behind those numbers.

General-purpose LLM applications can summarize financial documents, but they may introduce problems such as:

- Unsupported numerical claims
- Hallucinated sources
- Incorrect financial calculations
- Poor fiscal-year scoping
- Retrieval of irrelevant filing sections
- Confusion between unavailable and zero-valued metrics

This project addresses those problems by separating **financial computation**, **document retrieval**, **evidence management**, and **language generation**.

The result is a financial research workflow where:

```text
Financial Facts → Deterministic Calculation
                         │
                         ▼
Narrative Question → Retrieval → Evidence → LLM Synthesis
                         │
                         ▼
                 Citation Validation
                         │
                         ▼
                  Final Research Answer
````

---

# Key Features

## Financial Research

Analyze financial metrics including:

* Revenue
* Operating cash flow
* Free cash flow
* Margins
* Growth
* CAGR
* Company comparisons
* Fiscal-year performance

Numerical answers are calculated from the validated financial store rather than generated by the LLM.

---

## RAG-Based Document Intelligence

Retrieve supporting evidence from SEC filings for narrative questions involving:

* Business descriptions
* Risk factors
* Cybersecurity
* Supply chain
* Cloud services
* Climate-related risks
* Competition
* Management discussion
* Other supported filing sections

---

## Evidence-First Answers

Research results expose supporting evidence associated with application-controlled citation IDs.

The application validates citation references against persisted evidence rather than allowing the model to invent arbitrary sources.

---

## Company Comparison

Compare supported companies for a selected fiscal year using:

* Exact financial values
* Availability states
* Deterministic calculations
* Company ranking
* Source lineage

---

## SEC Filing Intelligence

The platform maintains filing metadata including:

* Company
* Ticker
* SEC CIK
* Form type
* Filing date
* Fiscal year
* SEC accession information
* Source provenance

---

## Explicit Abstention

The system does not silently fabricate missing information.

Unsupported or unavailable requests can return an explicit abstention instead of a speculative answer.

---

# Supported Corpus

The current corpus contains original annual **Form 10-K filings** for:

| Company   | Ticker | SEC CIK    | Fiscal Years     |
| --------- | ------ | ---------- | ---------------- |
| Apple     | AAPL   | 0000320193 | 2022, 2023, 2024 |
| Microsoft | MSFT   | 0000789019 | 2022, 2023, 2024 |
| Amazon    | AMZN   | 0001018724 | 2022, 2023, 2024 |

**9 annual filings** are included in the supported corpus.

Original 10-K filings are selected while 10-K/A amendments are excluded.

Filing date and fiscal year are maintained as separate concepts.

Source identity is derived from SEC metadata and filing validation.

---

# Product Walkthrough

The platform provides a dedicated financial research workspace rather than a single chat interface.

## Overview

The Overview page provides:

* Financial Intelligence workspace
* Company coverage
* Financial snapshots
* Revenue performance
* High-level analytics
* Capability status
* Research entry point

## Research

The Research workspace provides:

* Research question input
* Answer-first results
* Key findings
* Financial calculations
* Supporting evidence
* Citation references
* Provider and execution information

## Compare

The Compare workspace provides:

* Fiscal-year selection
* Company selection
* Metric selection
* Exact values
* Availability states
* Comparative visualization
* Source lineage

## Filings

The Filings page provides:

* Filing inventory
* Company information
* Fiscal-year coverage
* Filing dates
* SEC provenance

## Financials

The Financials page provides:

* Revenue
* Margins
* Cash flow
* Balance-sheet metrics
* Financial availability
* Metric-specific analysis

## Evidence

The Evidence page provides:

* Evidence ID lookup
* Supporting passages
* Filing metadata
* Source provenance
* Opened evidence records

## Evaluation

The Evaluation page provides:

* Evaluation status
* Actual evaluation artifacts
* Denominators
* Outcome metrics
* Review limitations

## Methodology

The Methodology page documents:

* Financial-data methodology
* Retrieval architecture
* Evidence validation
* Citation controls
* Abstention behavior
* System capabilities

---

# Architecture

The application uses three runtime services.

```text
┌──────────────────────────────────────┐
│            React Frontend            │
│          TypeScript + Vite           │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│          Public FastAPI API          │
│     Research / Compare / Data        │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│             AI / RAG Service         │
│                                      │
│  ┌────────────────────────────────┐  │
│  │     Structured Financials      │  │
│  │     Python Calculations        │  │
│  └────────────────────────────────┘  │
│                                      │
│  ┌────────────────────────────────┐  │
│  │       Hybrid Retrieval         │  │
│  │       FAISS + BM25             │  │
│  │       RRF + Reranking          │  │
│  └────────────────────────────────┘  │
│                                      │
│  ┌────────────────────────────────┐  │
│  │    Evidence + Generation       │  │
│  │    Groq / Optional Ollama      │  │
│  └────────────────────────────────┘  │
└──────────────────────────────────────┘
```

### Runtime Responsibilities

| Service         | Responsibility                                             |
| --------------- | ---------------------------------------------------------- |
| React Frontend  | User interface and research workflow                       |
| FastAPI Backend | Public API, financial analytics, application orchestration |
| AI/RAG Service  | Retrieval, evidence selection, narrative generation        |

The browser communicates with the public backend only.

The AI/RAG service is intended to remain internal to the application deployment.

---

# Data Pipeline

## Document Ingestion

```text
SEC EDGAR
    │
    ▼
SEC submissions + official HTML/iXBRL
    │
    ▼
Filing identity validation
    │
    ▼
Text extraction & normalization
    │
    ▼
Section detection
    │
    ▼
Source-linked chunks
    │
    ▼
BGE embeddings
    │
    ├──────────────► FAISS
    │
    └──────────────► BM25
```

The ingestion pipeline preserves relationships between:

* Filing
* Section
* Chunk
* Source span
* Evidence

This allows retrieved content to be traced back to the originating filing.

Runtime queries do not fetch SEC data or rebuild indexes.

---

# Financial Data Pipeline

Structured financial data is obtained from SEC Company Facts and reconciled against filing information.

```text
SEC Company Facts
       │
       ▼
Exact annual fact resolution
       │
       ▼
Unit / period / accession validation
       │
       ▼
Inline-XBRL reconciliation
       │
       ▼
Persisted financial store
       │
       ▼
Python Decimal calculations
       │
       ▼
API / UI
```

The financial resolver validates:

* Company
* SEC CIK
* Filing accession
* Form
* Fiscal year
* Period
* Financial concept
* Unit

Annual duration facts are restricted to the implemented annual-duration window.

Conflicting or unresolved observations are not silently overwritten.

Company Facts values are already scaled and are not re-scaled during calculation.

---

# Financial Calculation Methodology

The LLM does **not** perform authoritative financial arithmetic.

Financial calculations are implemented using Python `Decimal` arithmetic.

Supported calculations include:

* Year-over-year growth
* CAGR
* Margins
* Free cash flow
* Free cash flow margin
* Company comparisons

## Free Cash Flow

```text
Free Cash Flow = Operating Cash Flow − CapEx
```

CapEx is represented as a non-negative outflow magnitude.

## Example: FY2024 Operating Cash Flow

| Company   | Operating Cash Flow |
| --------- | ------------------: |
| Microsoft |            $118.55B |
| Apple     |            $118.25B |
| Amazon    |            $115.88B |

The ranking is produced by the deterministic financial calculation layer.

---

# Retrieval Pipeline

Narrative questions use the RAG pipeline.

```text
User Question
      │
      ▼
Query Classification / Scope
      │
      ▼
Query Expansion
      │
      ▼
Dense Retrieval ──────────┐
                          │
BM25 Retrieval ───────────┤
                          ▼
                 Reciprocal Rank Fusion
                          │
                          ▼
                 Cross-Encoder Reranking
                          │
                          ▼
                    Evidence Selection
                          │
                          ▼
                    Groq Synthesis
                          │
                          ▼
                   Citation Validation
                          │
                          ▼
                  Narrative Validation
                          │
                          ▼
                     Final Answer
```

## Retrieval Configuration

| Component              | Default                  |
| ---------------------- | ------------------------ |
| Embedding Model        | `BAAI/bge-base-en-v1.5`  |
| Reranker               | `BAAI/bge-reranker-base` |
| Dense Candidates       | 20                       |
| BM25 Candidates        | 20                       |
| RRF Constant           | 60                       |
| Rerank Shortlist       | 8                        |
| Final Evidence Context | 6                        |
| Chunk Target           | 700 tokens               |
| Chunk Overlap          | 100 tokens               |
| Reranker Threshold     | 0.35                     |
| Hosted Provider        | Groq                     |
| Hosted Model           | `openai/gpt-oss-120b`    |

Relevance scores are retrieval scores and should not be interpreted as answer-confidence probabilities.

Embedding windows are used to avoid sending oversized source chunks through shorter model input windows.

---

# Evidence and Citation Architecture

Evidence is controlled by the application.

```text
Retrieved Chunk
      │
      ▼
Evidence Registry
      │
      ▼
EVIDENCE_XXXX
      │
      ▼
LLM Citation Reference
      │
      ▼
Application Validation
      │
      ▼
Persisted Evidence Record
```

Citation IDs are generated and resolved by the application.

The LLM does not determine the final source identity.

Unknown or out-of-context citation IDs are rejected.

Retrieved documents are treated as untrusted input rather than application instructions.

Citation-ID validity confirms that a citation exists and belongs to the allowed evidence context. It does **not**, by itself, establish semantic entailment.

---

# Query Responsibilities

The system separates different types of questions.

## Structured Questions

Example:

```text
What was Apple's revenue in FY2024?
```

These requests use the validated financial store and deterministic calculations.

## Narrative Questions

Example:

```text
What cybersecurity risks did Microsoft disclose in FY2024?
```

These requests use:

* Query processing
* Retrieval
* Reranking
* Evidence selection
* LLM synthesis
* Citation validation

## Mixed Questions

Questions combining financial metrics and narrative explanation retain separate responsibilities for:

* Financial facts
* Calculations
* Narrative evidence
* Final synthesis

---

# Technology Stack

## Frontend

* React
* TypeScript
* Vite
* CSS

## Backend

* Python
* FastAPI
* Pydantic

## AI / RAG

* Retrieval-Augmented Generation
* FAISS
* BM25
* Reciprocal Rank Fusion
* BGE embeddings
* BGE cross-encoder reranking
* Groq
* Optional Ollama

## Financial Data

* SEC EDGAR
* SEC Company Facts
* Inline XBRL
* Python `Decimal`

## Infrastructure

* Docker
* Docker Compose
* Nginx

## Development & Quality

* Pytest
* Ruff
* Black
* GitHub Actions

---

# Project Structure

```text
financial-intelligence-platform/
│
├── ai_service/
│   ├── generation/
│   ├── retrieval/
│   ├── providers/
│   └── main.py
│
├── backend/
│   └── app/
│
├── core/
│   ├── config.py
│   ├── storage.py
│   └── ...
│
├── ingestion/
│   ├── extract.py
│   ├── index.py
│   └── pipeline.py
│
├── evaluation/
│   ├── questions.json
│   ├── prepare.py
│   ├── run.py
│   └── results/
│
├── indexes/
│   ├── chunks.json
│   ├── manifest.json
│   └── ...
│
├── data/
│   └── processed/
│
├── frontend/
│   ├── src/
│   └── package.json
│
├── tests/
│
├── configs/
│
├── docs/
│
├── Dockerfile.python
├── docker-compose.yml
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

# Installation

## Prerequisites

Recommended:

* Python 3.12
* Node.js 22
* npm
* Git
* Docker Desktop (optional)

## Create Python Environment

```powershell
py -3.12 -m venv .venv
```

Activate the environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

Upgrade pip:

```powershell
python -m pip install --upgrade pip
```

Install development dependencies:

```powershell
python -m pip install -e ".[dev]"
```

Install CPU PyTorch:

```powershell
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
```

Install ML dependencies:

```powershell
python -m pip install -e ".[ml]"
```

Install frontend dependencies:

```powershell
npm ci --prefix frontend
```

---

# Environment Configuration

Create a private `.env` file:

```powershell
if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
}
```

Configure the required environment variables privately:

```dotenv
LLM_PROVIDER=groq

GROQ_API_KEY=
GROQ_BASE_URL=https://api.groq.com/openai/v1
GROQ_MODEL=openai/gpt-oss-120b

ENABLE_LLM_FALLBACK=false

SEC_CONTACT_EMAIL=
SEC_USER_AGENT=
```

SEC acquisition requires a genuine contact identity and identifying User-Agent.

Public EDGAR APIs do not require an SEC API key.

**Never commit `.env` or API keys to the repository.**

---

# Frontend Configuration

By default, the frontend uses the same-origin `/api` path.

Optional configuration:

```dotenv
VITE_API_BASE_URL=/api
DEV_API_PROXY_TARGET=http://127.0.0.1:8000
```

Never place secrets in `VITE_*` environment variables because they are exposed to the browser at build time.

The development proxy target is used by the Vite development server and is not directly exposed as the browser API origin.

---

# Models and Initial Artifacts

If compatible models and processed artifacts are already present, this section can be skipped.

Prepare the default public model repositories:

```powershell
$env:HF_HOME = Join-Path $PWD "models/huggingface"
$env:HF_HUB_CACHE = Join-Path $PWD "models/huggingface/hub"
$env:HF_HUB_OFFLINE = "0"
$env:TRANSFORMERS_OFFLINE = "0"

python -c "from huggingface_hub import snapshot_download; repos = ('BAAI/bge-base-en-v1.5', 'BAAI/bge-reranker-base'); [snapshot_download(repo_id=repo) for repo in repos]"
```

After model preparation:

```powershell
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
```

Downloading models is not equivalent to inference verification. Model revisions should be deliberately pinned for reproducible production deployments.

---

# Rebuilding Data and Indexes

Stop dependent services before rebuilding published artifacts.

Run the full ingestion pipeline:

```powershell
python -m ingestion.pipeline
```

For index-only construction from an already compatible published corpus:

```powershell
python -m ingestion.index
```

Inspect:

```text
data/processed/ingestion_run.json
```

Artifact writes are performed atomically at the individual artifact level. Complete multi-file publication is not one filesystem transaction.

A UI or provider-only change does not require rebuilding compatible data and indexes.

---

# Running Locally

Use separate terminals from the repository root.

## 1. AI / RAG Service

```powershell
$env:HF_HOME = Join-Path $PWD "models/huggingface"
$env:HF_HUB_CACHE = Join-Path $PWD "models/huggingface/hub"
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"

python -m uvicorn ai_service.main:app --host 127.0.0.1 --port 8001
```

## 2. Backend

```powershell
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

## 3. Frontend

```powershell
npm run dev --prefix frontend -- --port 5173
```

Open:

```text
http://localhost:5173
```

FastAPI documentation:

```text
http://127.0.0.1:8000/docs
```

---

# Public API

| Method | Endpoint                      | Purpose                          |
| ------ | ----------------------------- | -------------------------------- |
| GET    | `/api/health`                 | Health check                     |
| GET    | `/api/system/status`          | System status                    |
| GET    | `/api/companies`              | Supported companies              |
| GET    | `/api/reports`                | Filing inventory                 |
| POST   | `/api/research`               | Financial and narrative research |
| POST   | `/api/compare`                | Company comparison               |
| GET    | `/api/evidence/{evidence_id}` | Evidence lookup                  |
| GET    | `/api/analytics`              | Financial analytics              |
| GET    | `/api/evaluation`             | Evaluation status/results        |

## Internal AI Endpoints

```text
/internal/health
/internal/status
/internal/rag/query
/internal/rag/compare
```

The internal AI endpoints are intended for service-to-service communication.

---

# Evaluation

The repository contains an artifact-backed evaluation workflow.

## Prepare Evaluation References

```powershell
python -m evaluation.prepare
```

## Run Evaluation

```powershell
python -m evaluation.run --dataset evaluation/resolved.json
```

The evaluation framework distinguishes between:

* Structured financial correctness
* Unsupported-question abstention
* False abstention
* Citation-ID validity
* Routing agreement
* Retrieval quality
* Semantic groundedness
* Narrative correctness
* Completeness

Metrics are only reported when the corresponding evaluation path and denominator support them.

## Completed Evaluation Results

| Metric                                    | Result |
| ----------------------------------------- | -----: |
| Structured regression correctness         |   100% |
| Unsupported abstention correctness        |   100% |
| Citation-ID validity                      |   100% |
| Routing type agreement                    |   100% |
| False abstention on structured references |     0% |

The evaluation intentionally does not fabricate retrieval or semantic-grounding scores when those components have not been independently scored.

---

# Verification

Run static checks:

```powershell
python -m pip check
python -m ruff check .
python -m black --check .
npm run build --prefix frontend
```

Run the automated test suite:

```powershell
python -m pytest -q --disable-socket --allow-unix-socket
```

The repository also uses GitHub Actions for automated quality checks.

---

# Docker Deployment

The deployment retains three application services and a production Nginx frontend.

Validate the Docker Compose configuration:

```powershell
docker compose config --quiet
```

Build and start:

```powershell
docker compose up --build -d
```

Check running services:

```powershell
docker compose ps
```

Compatible data, indexes, model caches, and writable evidence storage must be mounted according to the deployment documentation.

The AI service should not be exposed directly to the public internet.

---

# Data Coverage and Limitations

The platform intentionally reports unavailable metrics instead of replacing them with zeros or unrelated substitute values.

Current known coverage limitations include:

* Some Apple cash values remain unavailable under the current reconciliation policy.
* Some Amazon financial metrics remain unavailable under the current resolver.
* Amazon free cash flow and FCF margin may therefore be unavailable.
* FY2022 year-over-year growth requires FY2021 data, which is outside the current corpus scope.
* HTML extraction and inline-XBRL transformation support are not complete implementations of every possible filing structure.
* Citation-ID validation does not establish semantic entailment.
* Model revisions and dependencies are not fully pinned.
* Multi-file artifact publication is non-transactional.
* Browser cancellation does not guarantee provider-side cancellation.
* Evidence-session search is not equivalent to full corpus search.
* Some frontend validation remains partial rather than generated directly from a shared schema.
* Responsive and accessibility behavior should be independently verified for production deployment.
* The application does not implement mandatory authentication and should be deployed within an appropriate trusted perimeter.

These limitations are surfaced explicitly rather than silently masked.

---

# Security and Responsible Use

This project is designed for financial research and document analysis.

It is **not**:

* A stock-price prediction system
* An automated trading system
* An investment adviser
* A substitute for professional financial analysis

The system is designed to avoid presenting unsupported financial values as facts and uses explicit availability and abstention states where appropriate.

API credentials must remain outside the repository.

Retrieved documents are treated as untrusted data and are not treated as application instructions.

---

# Documentation

Additional technical documentation is available in the `docs/` directory:

* [Architecture](docs/architecture.md)
* [Ingestion](docs/ingestion.md)
* [Retrieval](docs/retrieval.md)
* [Financial Metrics](docs/financial-metrics.md)
* [Citations](docs/citations.md)
* [Evaluation](docs/evaluation.md)
* [Deployment](docs/deployment.md)
* [Troubleshooting](docs/troubleshooting.md)
* [UI Redesign](docs/ui-redesign.md)
* [Verification](docs/verification.md)

---

# Future Improvements

Potential future improvements include:

* Expanding the supported company and fiscal-year corpus
* Broader XBRL concept reconciliation
* More extensive retrieval benchmarking
* Independent semantic-grounding evaluation
* Additional financial statement metrics
* Improved responsive and accessibility coverage
* Stronger schema sharing between frontend and backend
* Authentication and role-based access control for deployed environments
* Reproducible model and dependency pinning
* Expanded automated browser testing

---

# Author

## Karthik Neduri

**B.Tech Computer Science and Engineering**

AI / ML • RAG • LLM Applications • Python • FastAPI

GitHub:
[https://github.com/Karthik-0917](https://github.com/Karthik-0917)

---

# License

This project is licensed under the **MIT License**. See [`LICENSE`](LICENSE).

SEC EDGAR is the primary data source. This project does not imply ownership of SEC filings or affiliation with the U.S. Securities and Exchange Commission.

Downloaded model repositories have their own licenses and usage conditions. Refer to the corresponding model cards and license files before redistribution or deployment.

```
