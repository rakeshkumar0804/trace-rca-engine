# TRACE Database & Environment Setup

This document describes how to configure and initialize PostgreSQL with the **pgvector** extension for TRACE.

---

## 1. Prerequisites

- **PostgreSQL 15+** installed and running on `localhost:5432`
- **Python 3.11+**
- `psql` command-line utility

---

## 2. PostgreSQL & pgvector Setup

### Step A: Install pgvector Extension
If not already installed in your PostgreSQL environment:
- **Windows**: Install precompiled binaries from [pgvector releases](https://github.com/pgvector/pgvector/releases) or build via MSVC:
  ```powershell
  nmake /F Makefile.msvc
  nmake /F Makefile.msvc install
  ```
- **macOS (Homebrew)**:
  ```bash
  brew install pgvector
  ```
- **Linux (Debian/Ubuntu)**:
  ```bash
  sudo apt install postgresql-15-pgvector
  ```
- **Docker**:
  ```bash
  docker run -d --name trace-postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=trace_db -p 5432:5432 pgvector/pgvector:pg16
  ```

### Step B: Create Database and Enable Extension
Connect to PostgreSQL and create the `trace_db` database:

```sql
CREATE DATABASE trace_db;
\c trace_db
CREATE EXTENSION IF NOT EXISTS vector;
```

---

## 3. Environment Configuration

Set the `DATABASE_URL` environment variable:

```bash
# Linux/macOS
export DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/trace_db"

# Windows PowerShell
$env:DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/trace_db"
```

For test environments without active PostgreSQL instances, SQLite with async support is seamlessly supported:
```powershell
$env:DATABASE_URL="sqlite+aiosqlite:///trace_test.db"
```

---

## 4. Database Migrations (Alembic)

Run the initial schema migration from `services/api`:

```bash
cd services/api
alembic upgrade head
```

---

## 5. Ingestion and Test Suite

Run the full end-to-end test suite:

```bash
python -m pytest -v
```
