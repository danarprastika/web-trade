# QuantX AI — Sprint 1 Build Report

## What Was Built
- **Monorepo structure:** `backend/` (FastAPI + Python) and `frontend/` (Next.js + TypeScript)
- **Backend:**
  - FastAPI app with async SQLAlchemy 2.x, Alembic migrations, Pydantic v2 settings
  - Database models: `User`, `TradingAccount`, `Asset`
  - Auth module: `/api/v1/auth/register`, `/login`, `/refresh`, `/logout`, `/me`
  - Health endpoints: `/api/v1/health` and `/api/v1/health/ready` with real DB check
  - Structured logging via `structlog`
  - CORS middleware configured via environment variables
- **Frontend:**
  - Next.js 16 scaffold with TypeScript, TailwindCSS, shadcn/ui primitives
  - Auth pages: `/login` and `/register` with Zod + React Hook Form validation
  - Dark-mode-first design with industrial precision tone
- **CI/CD:** GitHub Actions workflow for backend lint/format/test and frontend lint/typecheck
- **Database:** PostgreSQL 16 with asyncpg; migrations verified from empty schema

## How to Run
### Backend
```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
cp .env.example .env
# Edit .env with your DATABASE_URL
alembic upgrade head
uvicorn app.main:app --reload
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

### Tests
```bash
cd backend
pytest
```

### Migrations
```bash
cd backend
export PYTHONPATH=.
alembic upgrade head
```

## Assumptions & Decisions
- **Modular monolith** package layout (FastAPI routers + SQLAlchemy models in `app/`)
- **JWT access + refresh tokens** with refresh stored in httpOnly cookie
- **Test database:** SQLite in-memory via pytest monkeypatch; CI uses PostgreSQL service
- **Frontend build:** Next.js 16 with Turbopack; module resolution set to `bundler`
- **No external secrets manager** in Fase 0; secrets via `.env` with strict `.gitignore`

## Security Findings & Resolutions
- **HttpOnly refresh cookies:** refresh token not accessible to JavaScript; SameSite=strict
- **No hardcoded secrets:** all via `pydantic-settings` + `.env`
- **Input validation:** Pydantic schemas enforce email format, password length, field constraints
- **CORS:** environment-driven allowlist; credentials allowed for API requests
- **OWASP:** CSRF protection via SameSite cookies; rate-limiting package included but not yet enforced per-route (deferred to Sprint 2)
- **SQL injection:** prevented via SQLAlchemy parameterized queries

## Test Results
- **Backend pytest:** 8 passed
  - `test_health_endpoint` — 2 cases (asyncio, trio)
  - `test_health_ready` — 2 cases (asyncio, trio)
  - `test_health_ready_database_failure` — 2 cases (asyncio, trio)
  - `test_user_registration_and_login` — 2 cases (asyncio, trio)
- **Ruff lint:** clean (with B008 ignored for FastAPI `Depends` usage)
- **Frontend build:** Next.js production build succeeds

## Manual Switches Left OFF
- **Google/GitHub OAuth:** not implemented (out of scope for Sprint 1)
- **Rate limiting middleware:** `slowapi` installed but not yet applied to routes
- **Frontend token storage:** pages are scaffolded but token persistence not implemented
- **Email verification:** `is_verified` flag exists but no email flow

## Open Follow-ups
- Alembic revision file `001_initial.py` is manually written; future migrations can use `alembic revision --autogenerate`
- `app.config.settings` is imported at module level in several routers; tests monkeypatch carefully to avoid import-time validation errors
- `pytest-asyncio` emits warnings about `dispose()` coroutine; suppress or upgrade in Sprint 2
