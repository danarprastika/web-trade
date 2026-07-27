# QuantX AI — Build Report

## Sprint 1 — Foundation Layer

### What Was Built
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

### Test Results
- **Backend pytest:** 8 passed
- **Ruff lint:** clean

---

## Sprint 2 — Realtime Data & Social Auth

### What Was Built
- **OAuth login:** Google and GitHub integrated into existing JWT auth system
- **WebSocket real-time price feed:** Binance public WebSocket with exponential backoff reconnect
- **Watchlist module:** add/remove assets, live prices via WebSocket
- **Minimal Dashboard:** user profile + watchlist + honest empty states
- **Frontend:** OAuth buttons, watchlist page, dashboard page, `useMarketData` hook

### Test Results
- **Backend pytest:** 28 passed (12 Sprint 1 + 16 new)
- **Ruff lint:** clean after 73 auto-fixable + 14 manual fixes

---

## Sprint 2.1 — CI Repair

### What Was Built
- Added `[project.optional-dependencies]` group `test` to `backend/pyproject.toml`
- Pinned `bcrypt<4` to resolve passlib/bcrypt compatibility
- Added missing runtime dependency `email-validator>=2.1.0`
- Fixed 73 auto-fixable ruff issues + 14 manual fixes
- Updated `.github/workflows/ci.yml` `test-backend` to install test extras
- Fixed `lint-frontend` cache path
- Migrated frontend lint from deprecated `next lint` to `eslint .`

### Test Results
- **Backend pytest:** 14 passed
- **Ruff lint:** clean
- **Frontend lint:** passes
- **GitHub Actions:** all 3 jobs pass green

---

## Sprint 3 — Paper Trading & Risk Management

### What Was Built
- **Backend models:** `Strategy`, `Order`, `Position`, `Trade`, `RiskProfile`
- **Alembic migration:** `003_add_paper_trading`
- **Services:** `StrategyService`, `OrderService`, `PositionService`, `RiskService`
- **Routers:** `/api/v1/strategies`, `/orders`, `/positions`, `/trades`, `/risk`, `/dashboard`
- **Frontend pages:** `/dashboard` and `/strategies`
- **Tests:** 54 backend tests (strategies, orders, positions, risk, paper trading e2e, dashboard)
- **Real-money execution path:** exists but defaults OFF (`enable_live_trading: bool = False`)

### Test Results
- **Backend pytest:** 54 passed locally
- **Ruff lint:** clean, 24 files formatted
- **GitHub Actions CI:** https://github.com/danarprastika/web-trade/actions/runs/30242887877 — success

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
- **Real-money execution path** implemented with explicit `enable_live_trading` config flag defaulted to `False`
- **Paper trading** is the default execution mode; live trading structure exists but is dormant

## Security Findings & Resolutions
- **HttpOnly refresh cookies:** refresh token not accessible to JavaScript; SameSite=strict
- **No hardcoded secrets:** all via `pydantic-settings` + `.env`
- **Input validation:** Pydantic schemas enforce constraints across all new endpoints
- **CORS:** environment-driven allowlist; credentials allowed for API requests
- **OWASP:** CSRF protection via SameSite cookies
- **SQL injection:** prevented via SQLAlchemy parameterized queries
- **Live trading safety:** real-money execution path is gated behind `enable_live_trading: bool = False` in config

## Manual Switches Left OFF
- **Google/GitHub OAuth:** endpoints implemented but real provider credentials still placeholder
- **Rate limiting middleware:** `slowapi` installed but not yet applied to routes
- **Next.js auth middleware:** protected routes not yet enforced at middleware level
- **Live trading:** `enable_live_trading` defaults to `False`

## Open Follow-ups
- Alembic revision files can use `alembic revision --autogenerate` going forward
- `python-multipart` is declared in `pyproject.toml` but needs to be installed in fresh venvs for local test runs
- `app.config.settings` imported at module level in several routers; tests monkeypatch carefully
- Next.js middleware for auth protection on dashboard/strategies routes is pending
- Fase 2 (Intelligence): News Intelligence, Market Intelligence, Technical Analysis Engine
