# TRACE — Portfolio Summary

**Project**: TRACE (Telemetry Root-cause Autonomous Critique Engine)  
**Role**: Creator & Core Engineer  
**Stack**: Python 3.11, FastAPI, SQLAlchemy, Next.js 14, TypeScript, Tailwind CSS, Google Gemini, PostgreSQL / SQLite  
**Repository**: [https://github.com/rakeshkumar0804/trace-rca-engine](https://github.com/rakeshkumar0804/trace-rca-engine)  

### Key Accomplishments:
* **Built an autonomous root cause analysis engine** that correlates logs, metrics, trace spans, database locks, alerts, and deployment rollouts across microservice topologies.
* **Designed a hybrid neuro-symbolic architecture**: Gemini handles hypothesis formulation and unstructured log reasoning, while deterministic state machines, topological graph traversal, and linear regression slope trend checks handle scoring, falsification, and confidence calibration.
* **Created a rigorous, reproducible 19-incident benchmark** evaluating against isolated ground truth: TRACE achieved **89.5% root-cause accuracy** vs a **73.7% naive single-shot LLM baseline**.
* **Engineered a deterministic trend-differential verification engine** to eliminate LLM recency bias on red-herring deployments, boosting memory leak diagnosis from 0.0% to 60.0%.
* **Developed an interactive dark-terminal investigation UI** (Next.js 14 / TypeScript) with real-time state machine progress tracing, interactive causal graphs, and UUID click-through evidence inspection modals.
* **100% test coverage**: 154 automated pytest tests covering generation, conversions, retrieval, scoring, state machine transitions, and API endpoints.
