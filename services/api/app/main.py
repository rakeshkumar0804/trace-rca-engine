"""TRACE FastAPI Backend Application."""

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.api.incidents import router as incidents_router
from app.api.investigations import router as investigations_router
from app.api.evidence import router as evidence_router
from app.api.rate_limiter import RateLimitMiddleware
from app.db.base import Base, get_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup & shutdown events."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(
    title="TRACE — Telemetry Root-cause Autonomous Critique Engine",
    description="Autonomous RCA agent powered by deterministic falsification and evidence grounding.",
    version="1.0.0",
    lifespan=lifespan,
)

# Rate limiting middleware for expensive endpoints (15 req/min per IP)
app.add_middleware(RateLimitMiddleware, max_requests_per_minute=15)

# Environment-aware CORS configuration
cors_origins_env = os.getenv("CORS_ORIGINS", "*")
allow_origins = ["*"] if cors_origins_env == "*" else [o.strip() for o in cors_origins_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API Routers
app.include_router(incidents_router)
app.include_router(investigations_router)
app.include_router(evidence_router)


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "TRACE API"}
