from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import os

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

DEFAULT_DB_URL = "sqlite+aiosqlite:///data/trace_app.db"

Base = declarative_base()

_engine: AsyncEngine | None = None
_session_maker: async_sessionmaker[AsyncSession] | None = None


def get_database_url() -> str:
    """Returns the database URL from the DATABASE_URL environment variable or default."""
    return os.getenv("DATABASE_URL", DEFAULT_DB_URL)


def get_engine() -> AsyncEngine:
    """Initializes and returns the singleton async SQLAlchemy engine."""
    global _engine, _session_maker
    if _engine is None:
        url = get_database_url()
        if "sqlite" in url:
            from sqlalchemy import event
            os.makedirs("data", exist_ok=True)
            _engine = create_async_engine(
                url,
                echo=False,
                connect_args={"check_same_thread": False, "timeout": 30},
            )
            @event.listens_for(_engine.sync_engine, "connect")
            def _set_sqlite_pragma(dbapi_connection, connection_record):
                try:
                    cursor = dbapi_connection.cursor()
                    cursor.execute("PRAGMA journal_mode=WAL")
                    cursor.execute("PRAGMA synchronous=NORMAL")
                    cursor.execute("PRAGMA busy_timeout=10000")
                    cursor.close()
                except Exception:
                    pass
        else:
            is_prod = os.getenv("ENVIRONMENT", "").lower() in ("production", "prod")
            pool_size = int(os.getenv("DB_POOL_SIZE", "2" if is_prod else "10"))
            max_overflow = int(os.getenv("DB_MAX_OVERFLOW", "3" if is_prod else "20"))
            _engine = create_async_engine(
                url,
                echo=False,
                pool_size=pool_size,
                max_overflow=max_overflow,
                pool_timeout=30,
                pool_pre_ping=True,
            )
        _session_maker = async_sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Returns the async session factory."""
    global _session_maker
    if _session_maker is None:
        get_engine()
    assert _session_maker is not None
    return _session_maker


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager yielding a database session with automatic commit/rollback."""
    session_maker = get_session_factory()
    async with session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_fastapi_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a database session."""
    session_maker = get_session_factory()
    async with session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def reset_engine(new_url: str | None = None) -> AsyncEngine:
    """Disposes the existing engine and initializes a new one, used in testing."""
    global _engine, _session_maker
    if _engine is not None:
        await _engine.dispose()
    if new_url is not None:
        os.environ["DATABASE_URL"] = new_url
    _engine = None
    _session_maker = None
    return get_engine()
