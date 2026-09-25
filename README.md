# TRACE — Telemetry Root-cause Autonomous Critique Engine

[![Tests](https://img.shields.io/badge/Tests-156%2F156%20Passing-brightgreen.svg)]()
[![Benchmark](https://img.shields.io/badge/Root--Cause%20Accuracy-89.5%25%20(vs%2073.7%25%20Baseline)-blue.svg)]()
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)]()
[![Frontend](https://img.shields.io/badge/Frontend-Next.js%2014%20(TypeScript%20%2B%20Tailwind)-black.svg)]()
[![License](https://img.shields.io/badge/License-MIT-purple.svg)]()

TRACE is an autonomous incident investigation engine that ingests multi-modal observability telemetry (metrics, logs, traces, database locks, alerts, and CI/CD deployment events) and determines the true root cause of complex distributed system outages.

Unlike naive single-shot LLM prompts that fall prey to hallucination and recency bias, TRACE implements a **deterministic state machine, multi-factor hypothesis ranking, and a self-critique/falsification engine** with code-driven trend-differential verification.

---

## 1. Problem

During major microservice outages, site reliability engineers (SREs) face alert storms spanning hundreds of noisy logs, cascading error spikes, and simultaneous deployment events. 

Single-shot LLM prompts consistently fail in realistic environments because:
1. **Recency Bias**: LLMs disproportionately blame the most recent deployment commit, even when telemetry shows an underlying continuous memory leak or datastore lock contention preceded the release.
2. **Ungrounded Hallucinations**: LLMs cite plausible-sounding causes without linking claims back to verified database telemetry records.
3. **No Self-Critique**: Naive LLMs generate a single explanation without actively attempting to formulate testable hypotheses or search for contradicting telemetry.

TRACE solves this by separating **hypothesis generation and interpretation** (powered by Gemini) from **deterministic scoring, timeline alignment, and slope trend-differential verification** (implemented in pure Python).

---

## 2. Live Demo & Modes

- **Live Frontend**: [https://trace-rca-engine.vercel.app](https://trace-rca-engine.vercel.app)
- **Live Backend API**: [https://trace-rca-engine.onrender.com/docs](https://trace-rca-engine.onrender.com/docs) *(Swagger UI)*

TRACE provides two distinct execution paths:

1. **Demo Replay (Verified Reference Incident)**:
   - Replays a pre-computed reference investigation (`bad_deployment_db_exhaustion`, seed=1) generated with `MockLLMProvider`.
   - Streams the 8 state transitions progressively with **synthetic telemetry stored in the database and available for inspection**.
   - Zero LLM API quota consumption; guaranteed 100% reliable evaluation for demonstration purposes.
2. **Custom Incident Live Run**:
   - Generates a new synthetic incident into the telemetry store (e.g. Memory Leak, Dependency Cascade, or DB Saturation) and runs the live orchestrator pipeline end-to-end with the active LLM provider.

---

## 3. Architecture

```mermaid
flowchart TD
    subgraph Client ["Next.js 14 Web Frontend"]
        UI[Investigation UI: 3 Screens]
        Modal[Evidence Modal Inspector]
    end

    subgraph API ["FastAPI REST Layer"]
        Router[API Routers: Incidents, Investigations, Evidence]
        RateLimit[Token-Bucket Rate Limiter]
        CORS[Environment-Aware CORS]
    end

    subgraph Core ["TRACE Core Engine"]
        Orchestrator[Autonomous Orchestrator State Machine]
        TimelineEngine[Timeline Alignment Engine]
        RetrievalEngine[Multi-Modal Retrieval: Entity, Temporal, Semantic]
        HypothesisEngine[Candidate Hypothesis Generator]
        ScoringEngine[Deterministic Heuristic Scoring Engine]
        FalsificationEngine[Falsification & Self-Critique Engine]
        TrendCheck[Deterministic Slope Trend-Differential Check]
    end

    subgraph Intelligence ["LLM Layer"]
        Gemini[Google Gemini 2.5 Flash / Flash Lite]
    end

    subgraph Storage ["Database Layer"]
        DB[(PostgreSQL + pgvector / SQLite Fallback)]
        GT[(Ground Truth Table - ISOLATED)]
    end

    UI -->|REST / Polling| Router
    Router --> RateLimit
    RateLimit --> Orchestrator
    Orchestrator --> TimelineEngine
    Orchestrator --> RetrievalEngine
    Orchestrator --> HypothesisEngine
    Orchestrator --> ScoringEngine
    Orchestrator --> FalsificationEngine
    FalsificationEngine --> TrendCheck
    FalsificationEngine --> Gemini
    RetrievalEngine --> DB
    ScoringEngine --> DB
    TrendCheck --> DB
```

---

## 4. Investigation Flow

TRACE executes an 8-state deterministic state machine managed by `InvestigationStateMachine`:

| State | Action Executed |
| :--- | :--- |
| `INIT` | Initialized investigation record and execution context. |
| `INGESTING` | Discovers symptoms, establishes incident time bounds, and constructs unified chronological timeline. |
| `HYPOTHESES_GENERATED` | Generates candidate hypotheses across deployments, databases, dependency graphs, and resource trends. |
| `HYPOTHESES_RANKED` | Computes composite multi-factor baseline scores; applies bounded top-N cutoff. |
| `INVESTIGATING_HYPOTHESIS` | Deep telemetry retrieval across entity topology and upstream/downstream services. |
| `CRITIQUING_HYPOTHESIS` | Formulates falsification questions, runs deterministic slope checks, and evaluates evidence contradictions. |
| `RCA_GENERATED` | Leading hypothesis clears validation threshold; synthesizes evidence-grounded executive narrative. |
| `INCONCLUSIVE` | Triggered if confidence is < 70% or all leading candidates are refuted by telemetry. |

---

## 5. AI Architecture — Explicit Boundaries

One of the foundational design principles of TRACE is strictly defining where LLMs are used versus where deterministic code is enforced:

### Where the LLM IS Used:
* **Candidate Proposal**: Synthesizing descriptive candidate titles from raw error patterns.
* **Evidence Interpretation**: Evaluating whether a specific retrieved log snippet contradicts or supports an inquiry.
* **Falsification Inquiries**: Generating testable questions (*"Did upstream API gateways experience timeouts before the deployment finished?"*).
* **Executive RCA Synthesis**: Writing human-readable markdown summaries grounded strictly in cited UUIDs.

### Where the LLM IS NOT Used (Deterministic Code):
* **Hypothesis Scoring**: Composite scoring formula combining recency, metric anomaly z-score, database lock duration, and service topology distance.
* **Falsification Verdict Logic**: Contradiction score penalties and status transitions are calculated strictly in code.
* **Trend-Differential Verification**: Linear regression slope computation of metric time series (`memory_mb`, `cpu_pct`) before vs after deployments.
* **Confidence Calibration**: Direct algebraic calculation based on verified evidence count, citation density, and contradiction penalties.

---

## 6. Evidence Model & Ground Truth Isolation

### UUID-Grounded Citations
The displayed citations link to stored telemetry records in the database (timestamp, service, severity, message, metric values, database locks). In the UI, clicking any citation pill opens the underlying stored record for inspection; citation existence does not by itself establish causal relevance.

### Strict Ground Truth Isolation
* **Zero Runtime Leakage**: Runtime orchestrator and retrieval queries are prohibited from joining or querying the `ground_truths` table.
* **Hermetic Evaluation**: The ground truth is evaluated only in the evaluation harness (`app/eval/`) after the investigation state machine has concluded and persisted its final state.

---

## 7. Synthetic Incident Generator

TRACE features a deterministic, seeded synthetic incident generator covering 3 complex failure archetypes:

1. **`bad_deployment_db_exhaustion`**: A service deployment introduces an unindexed query regression that saturates connection pools and causes HTTP 504 cascades.
2. **`dependency_failure_cascade`**: A downstream microservice suffers internal thread pool exhaustion, cascading timeouts upstream through the service topology.
3. **`memory_leak_masked_deployment`**: A service suffers a steady memory leak and GC pause lockups over hours. An innocent routine configuration deployment occurs minutes before the crash, acting as an intentional red herring.

---

## 8. Verified Benchmark & Evaluation

Every statistic below comes directly from recorded benchmark evaluation runs across **19 seeded synthetic incidents across three archetypes** (`data/benchmark/results.json`, `data/benchmark/report.md`):

> **Scope Note**: This benchmark evaluates causal reasoning, distractor handling, and trend verification on seeded synthetic incident topologies with hidden ground truth. It isolates specific failure modes under controlled conditions and does not establish measured accuracy across arbitrary real-world production environments.

### Overall Benchmark Results (19 Incidents)

| System | Incidents Evaluated | Root Cause Accuracy | Correct / Total |
| :--- | :---: | :---: | :---: |
| **TRACE (Full Engine)** | **19** | **89.5%** | **17 / 19** |
| **Naive LLM Baseline** | 19 | 73.7% | 14 / 19 |
| **Performance Delta** | — | **+15.8%** | **+3 Incidents** |

### Breakdown by Incident Archetype

| Incident Type | Scenarios | TRACE Accuracy | Naive Baseline | Delta |
| :--- | :---: | :---: | :---: | :---: |
| `bad_deployment_db_exhaustion` | 7 | **100.0%** (7/7) | 100.0% (7/7) | +0.0% |
| `dependency_failure_cascade` | 7 | **100.0%** (7/7) | 100.0% (7/7) | +0.0% |
| `memory_leak_masked_deployment` | 5 | **60.0%** (3/5) | 0.0% (0/5) | **+60.0%** |

### Benchmark Analysis & Findings
1. On standard deployment saturation and dependency cascades, both TRACE and the naive single-shot baseline achieved 100% (7/7 each) due to clear causal log/metric signatures.
2. On the **Memory Leak with Masked Deployment** scenario (`memory_leak_masked_deployment`):
   - The naive single-shot LLM baseline scored **0.0% (0/5)**: due to window truncation and prompt recency bias, the baseline reported "system operating normally" (4/5) or cited an unrelated low-inventory warning (1/5).
   - TRACE achieved **60.0% (3/5)** by utilizing multi-modal retrieval and deterministic trend-differential verification (`trend_differential_check.py`) to verify that the memory growth slope preceded the deployment release.
   - TRACE misattributed the root cause in 2 edge cases (`bench-mem-02` and `bench-mem-04`), detailed in the failure analysis below.

---

## 9. Failure Analysis — Unsolved Edge Cases

Honest analysis of the two memory-leak benchmark runs where TRACE did not confirm the true ground-truth root cause:

### 1. `bench-mem-02` (Misattributed to Deployment Distractor)
* **Outcome**: TRACE failed, predicting `"Bad deployment to checkout-service (v2.16.0)"` with **76.0% confidence** (Baseline failed, predicting `"System operating normally"` with 100.0% confidence).
* **Analysis**: In this seed's specific metric noise and timing, the coincidental deployment candidate accumulated sufficient baseline score and survived the critique threshold, resulting in misattribution to the deployment distractor rather than the underlying memory leak.

### 2. `bench-mem-04` (Misattributed to Downstream Dependency)
* **Outcome**: TRACE failed, predicting `"Downstream dependency failure in payment-service"` with **86.0% confidence** (Baseline failed, predicting `"No critical root cause or failure detected"` with 95.0% confidence).
* **Analysis**: Long stop-the-world GC pauses from the heap exhaustion triggered connection timeouts to `payment-service`. TRACE's candidate scoring ranked the payment cascade hypothesis highest, and self-critique failed to refute it, misdiagnosing the downstream symptom as the root cause.

---

## 10. Engineering Trade-offs & Scope Decisions

* **Synthetic Generator vs Real Docker Microservices**: Synthetic telemetry generation allowed deterministic seeding, rapid CI test runs (<2.5 minutes for 156 tests), and 100% reproducible benchmark scenarios.
* **Dual-Engine DB Support (PostgreSQL / SQLite)**: Native support for PostgreSQL with pgvector for production deployments, paired with a transparent fallback for local zero-dependency development.
* **FastEmbed in-process Embeddings**: FastEmbed runs ONNX models locally in-process with cosine similarity calculation in Python, eliminating external vector database dependencies.

---

## 11. Local Setup

### Prerequisites
* Python 3.11+
* Node.js 18+
* Google Gemini API Key (optional for Mock mode, required for live LLM mode)

### 1. Backend Setup
```bash
cd services/api
python -m venv .venv
# On Windows: .venv\Scripts\activate | On Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Set GEMINI_API_KEY in .env

# Run FastAPI backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### 2. Frontend Setup
```bash
cd services/web
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

### 3. Run Full Test Suite
```bash
cd services/api
python -m pytest tests/ -v
# 156 / 156 tests passing
```

---

## 12. Deployment

### Backend (Render / Railway)
1. Create a new Web Service pointing to `services/api`.
2. Set Environment Variables:
   * `GEMINI_API_KEY`: Your Gemini API Key
   * `GEMINI_MODEL`: `gemini-2.5-flash`
   * `CORS_ORIGINS`: `https://your-frontend.vercel.app`
   * `DATABASE_URL`: Managed PostgreSQL connection string (or omit to use local SQLite volume)
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT --app-dir .`

### Frontend (Vercel)
1. Import repository on Vercel with Root Directory set to `services/web`.
2. Set Environment Variable:
   * `NEXT_PUBLIC_API_URL`: `https://your-backend.onrender.com`
3. Deploy.
