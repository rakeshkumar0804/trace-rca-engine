"""Tests for database migration and backward compatibility:
1. Fresh database initialization and schema validity.
2. Pre-polish schema upgrade preserving historical investigations.
3. Reading both legacy (migrated) and new provider-labeled investigations via API.
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import pytest
from httpx import ASGITransport, AsyncClient
import sqlalchemy as sa
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from alembic import command
from alembic.config import Config
from app.db.base import Base, reset_engine
from app.db.models import IncidentORM, InvestigationORM, InvestigationStepORM
from app.main import app
from app.api.rate_limiter import RateLimitMiddleware


ALEMBIC_INI_PATH = str(Path(__file__).resolve().parent.parent / "alembic.ini")
MIGRATIONS_DIR = str(Path(__file__).resolve().parent.parent / "app" / "db" / "migrations")


def make_alembic_config(db_url: str) -> Config:
    cfg = Config(ALEMBIC_INI_PATH)
    cfg.set_main_option("script_location", MIGRATIONS_DIR)
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


@pytest.fixture
def alembic_config(tmp_path):
    """Generates an Alembic config pointing to a temporary SQLite test database."""
    db_file = tmp_path / "migration_test.db"
    db_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    cfg = make_alembic_config(db_url)
    return cfg, db_url, db_file


class TestDatabaseMigrations:
    """Verifies that Alembic migrations run cleanly and preserve historical data."""

    def test_alembic_upgrade_head_on_fresh_db(self, alembic_config):
        """A fresh database initializes through Alembic upgrade head without error."""
        cfg, db_url, _ = alembic_config
        command.upgrade(cfg, "head")

        # Verify tables created
        engine = sa.create_engine(db_url.replace("+aiosqlite", ""))
        insp = sa.inspect(engine)
        tables = insp.get_table_names()

        assert "incidents" in tables
        assert "investigations" in tables
        assert "investigation_steps" in tables
        assert "logs" in tables

        inv_cols = {col["name"] for col in insp.get_columns("investigations")}
        assert "llm_provider" in inv_cols
        assert "llm_model" in inv_cols
        assert "is_fallback" in inv_cols
        assert "fallback_reason" in inv_cols

    def test_revision_id_does_not_exceed_postgres_32_char_limit(self, alembic_config):
        """PostgreSQL's alembic_version.version_num is VARCHAR(32).
        
        Verifies every migration revision ID in the script directory is <= 32 characters.
        """
        cfg, _, _ = alembic_config
        from alembic.script import ScriptDirectory
        script_dir = ScriptDirectory.from_config(cfg)
        
        for rev in script_dir.walk_revisions():
            assert len(rev.revision) <= 32, (
                f"Migration revision ID '{rev.revision}' ({len(rev.revision)} chars) "
                f"exceeds PostgreSQL's VARCHAR(32) limit on alembic_version.version_num."
            )

    @pytest.mark.anyio
    async def test_pre_polish_schema_upgrade_preserves_historical_investigations(self, tmp_path, monkeypatch):
        """Simulates an existing deployed database created with pre-polish schema.
        
        1. Creates pre-polish 'investigations' table (WITHOUT llm_provider, llm_model, etc.).
        2. Inserts historical investigation rows.
        3. Runs Alembic migration 0003.
        4. Verifies historical rows are preserved, get safe defaults, and can be read via API.
        5. Verifies new investigations with explicit provider fields can be created and read alongside old ones.
        """
        RateLimitMiddleware.reset_all_instances()
        db_file = tmp_path / "legacy_test.db"
        db_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
        sync_url = f"sqlite:///{db_file.as_posix()}"

        # 1. Manually create pre-polish database schema (as it existed prior to Phase 4)
        sync_engine = sa.create_engine(sync_url)
        with sync_engine.connect() as conn:
            # Create incidents table
            conn.execute(text("""
                CREATE TABLE incidents (
                    incident_id VARCHAR(36) PRIMARY KEY,
                    incident_type VARCHAR(100) NOT NULL,
                    start_time TIMESTAMP NOT NULL,
                    end_time TIMESTAMP,
                    affected_services JSON NOT NULL,
                    expected_symptoms JSON NOT NULL,
                    distractor_event_ids JSON NOT NULL,
                    difficulty VARCHAR(50) NOT NULL,
                    severity VARCHAR(50) NOT NULL
                )
            """))
            # Create pre-polish investigations table WITHOUT provider fields
            conn.execute(text("""
                CREATE TABLE investigations (
                    investigation_id VARCHAR(36) PRIMARY KEY,
                    incident_id VARCHAR(36) NOT NULL,
                    final_state VARCHAR(50) NOT NULL,
                    leading_hypothesis_id VARCHAR(36),
                    confidence FLOAT,
                    started_at TIMESTAMP NOT NULL,
                    completed_at TIMESTAMP,
                    rca_narrative TEXT
                )
            """))
            # Create investigation_steps table
            conn.execute(text("""
                CREATE TABLE investigation_steps (
                    id VARCHAR(36) PRIMARY KEY,
                    investigation_id VARCHAR(36) NOT NULL,
                    step_number INTEGER NOT NULL,
                    state VARCHAR(50) NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    summary TEXT NOT NULL,
                    details JSON NOT NULL
                )
            """))
            # Create services table (to satisfy 0001 check)
            conn.execute(text("""
                CREATE TABLE services (
                    name VARCHAR(100) PRIMARY KEY,
                    description TEXT NOT NULL,
                    owns_database BOOLEAN NOT NULL
                )
            """))

            # 2. Insert historical data (pre-polish investigation)
            hist_inc_id = uuid4()
            hist_inv_id = uuid4()
            now_iso = datetime.now(timezone.utc).isoformat()

            conn.execute(text("""
                INSERT INTO incidents (incident_id, incident_type, start_time, affected_services, expected_symptoms, distractor_event_ids, difficulty, severity)
                VALUES (:inc_id, 'bad_deployment_db_exhaustion', :start_time, '["checkout-service"]', '[]', '[]', 'medium', 'sev1')
            """), {"inc_id": hist_inc_id.hex, "start_time": now_iso})

            conn.execute(text("""
                INSERT INTO investigations (investigation_id, incident_id, final_state, confidence, started_at, completed_at, rca_narrative)
                VALUES (:inv_id, :inc_id, 'rca_generated', 85.5, :start_time, :start_time, 'Historical RCA root cause analysis narrative.')
            """), {"inv_id": hist_inv_id.hex, "inc_id": hist_inc_id.hex, "start_time": now_iso})

            conn.execute(text("""
                INSERT INTO investigation_steps (id, investigation_id, step_number, state, timestamp, summary, details)
                VALUES (:step_id, :inv_id, 1, 'incident_detected', :start_time, 'Initial incident detected.', '{}')
            """), {"step_id": uuid4().hex, "inv_id": hist_inv_id.hex, "start_time": now_iso})

            conn.commit()

        # 3. Apply Alembic migration up to head on the existing legacy database
        cfg = make_alembic_config(db_url)
        command.upgrade(cfg, "head")

        # 4. Point app engine to the migrated database and test through REST API
        monkeypatch.setenv("DATABASE_URL", db_url)
        engine = await reset_engine(db_url)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 4a. Fetch historical investigation through API
            res_hist = await client.get(f"/api/investigations/{hist_inv_id}")
            assert res_hist.status_code == 200
            data_hist = res_hist.json()

            assert data_hist["investigation_id"] == str(hist_inv_id)
            assert data_hist["final_state"] == "rca_generated"
            assert data_hist["confidence"] == 85.5
            assert data_hist["rca_narrative"] == "Historical RCA root cause analysis narrative."
            # Historical row must safely default to Unknown (historical run) without crash
            assert data_hist["llm_provider"] == "unknown"
            assert data_hist["llm_model"] == "Unknown (historical run)"

            # 4b. Create a new provider-labeled investigation in the migrated DB
            gen_res = await client.post(
                "/api/incidents/generate",
                json={"incident_type": "bad_deployment_db_exhaustion", "seed": 77}
            )
            assert gen_res.status_code == 200
            new_inc_id = gen_res.json()["incident_id"]

            run_res = await client.post("/api/investigations/run", json={"incident_id": new_inc_id})
            assert run_res.status_code == 200
            new_inv_id = run_res.json()["investigation_id"]

            res_new = await client.get(f"/api/investigations/{new_inv_id}")
            assert res_new.status_code == 200
            data_new = res_new.json()

            assert data_new["investigation_id"] == new_inv_id
            assert "llm_provider" in data_new
            assert "llm_model" in data_new

            # 4c. Verify both historical and new investigations are simultaneously preserved
            async with engine.connect() as conn:
                count_res = await conn.execute(select(sa.func.count()).select_from(InvestigationORM))
                total_investigations = count_res.scalar()
                assert total_investigations >= 2
