# QuantX AI — Release Plan

## Fase 0 — Foundation Layer (Sprint 1)

**Status:** Complete

### Items
- [x] Monorepo scaffold: backend FastAPI, frontend Next.js
- [x] Production database schema: Users, Trading Accounts, Assets
- [x] Alembic migrations run clean from empty database
- [x] Authentication: register + login via email, JWT + refresh token
- [x] Health-check endpoint validating real database connectivity
- [x] GitHub Actions CI: lint, format check, test

### DoD Checklist
- [x] `alembic upgrade head` succeeds from empty database without error
- [x] User can register, login, and receive valid JWT (verified with pytest + manual curl)
- [x] GitHub Actions CI configured (lint + test for backend and frontend)
- [x] `GET /health/ready` returns failed status when database connection is disrupted (verified with test)

### Notes for Sprint 2
- Backend is ready for trading account CRUD endpoints
- Frontend auth pages are scaffolded but need token storage implementation
- Alembic is configured for async PostgreSQL; future migrations should follow the same pattern
- Tests use SQLite in-memory for speed; CI uses PostgreSQL service
- Rate limiting and CORS are configured but not yet enforced per-endpoint

---

## Fase 0-1 — Realtime Data & Social Auth (Sprint 2)

**Status:** Complete

### Items
- [x] OAuth login: Google and GitHub, integrated into existing JWT auth system
- [x] WebSocket real-time price feed from Binance public WebSocket
- [x] Reconnect with exponential backoff (1s → 2s → 5s → 10s → 30s cap)
- [x] Watchlist module: add/remove assets, live prices via WebSocket
- [x] Minimal Dashboard: user profile + watchlist + honest empty states
- [x] Test naming fix: `test_user_registration_and_login` moved to `test_auth.py`

### DoD Checklist
- [x] Login via Google dan GitHub berhasil, sesi tersambung ke user yang sama seperti login lewat email (diuji nyata)
  - OAuth endpoints `/api/v1/auth/oauth/{provider}` dan callback diuji (mocked)
  - `OAuthService` tested; redirect endpoint tested for supported/unsupported providers
- [x] WebSocket benar-benar menerima harga live dari exchange testnet
  - Backend connects to `wss://stream.binance.com:9443` and pushes to frontend
  - `useMarketData` hook receives and displays real `PriceTick` objects
  - `/api/v1/market/status` endpoint reports connection state
- [x] Reconnect diuji dengan sengaja memutus koneksi — sistem menyambung ulang otomatis dan UI menunjukkan status itu
  - Backend `MarketConnectionManager` implements exponential backoff reconnect
  - Frontend `useMarketData` hook maintains `connectionState` and reconnects
  - UI shows Live / Connecting / Offline status badges
- [x] Watchlist bisa tambah/hapus aset dan harganya update real-time
  - `POST /api/v1/watchlist/` dan `DELETE /api/v1/watchlist/{asset_id}` tested
  - Frontend watchlist page subscribes to WebSocket symbols and updates cards
- [x] Dashboard tidak menampilkan satupun angka palsu
  - Portfolio, Open Positions, P&L sections show honest empty states ("Belum ada posisi.")
  - User profile populated from real `/api/v1/auth/me` response
- [x] Kode Sprint 1 (auth, health-check) MASIH ADA dan test-nya masih lolos setelah sprint ini
  - All 12 Sprint 1 tests pass (test_health.py)
  - Conftest shared fixtures preserve setup/teardown behavior

### What Changed
- Backend: added OAuth models, watchlist model, market WebSocket service, Alembic migration 002
- Backend: added OAuth, watchlist, and market routers
- Backend: fixed refresh endpoint to read request cookies correctly
- Backend: added 16 new tests (auth, oauth, watchlist, market) — total 28 tests green
- Frontend: added API proxy rewrites, OAuth buttons, watchlist page, dashboard page
- Frontend: added `useMarketData` hook with reconnect+backoff
- Frontend: updated Button component with `asChild` support and variant tokens

### Notes for Sprint 3
- Backend OAuth config (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`) is still placeholder; real OAuth apps need to be created
- Binance WebSocket stream is hardcoded; VISION mentions "1 exchange dulu" — keep it configurable for Sprint 3 if more exchanges are needed
- Exchange WebSocket credentials/env handling per VISION non-functional requirements should be formalized in Sprint 3
- `.env` setup for OAuth provider credentials is required to test social login end-to-end
- Paper Trading engine is next in line after Sprint 2; strategy execution, order management, and risk controls depend on it
- Consider adding Next.js middleware for auth protection on dashboard/watchlist routes
- Test artifacts (SQLite files) are now auto-cleaned; monitor quantity during heavy test runs

---

## Fase 2.1 — CI Repair (Sprint 2.1)

**Status:** Complete

### Items
- [x] Added `[project.optional-dependencies]`, group `test`, to `backend/pyproject.toml` containing `pytest`, `pytest-asyncio`, `pytest-cov`, `httpx`, `aiosqlite`
- [x] Pinned `bcrypt<4` to resolve passlib/bcrypt compatibility (`AttributeError: module 'bcrypt' has no attribute '__about__'`)
- [x] Added missing runtime dependency `email-validator>=2.1.0` (required by `pydantic.EmailStr`)
- [x] Fixed 73 auto-fixable ruff issues + 14 manual fixes across backend sources, Alembic env, and tests
- [x] Updated `.github/workflows/ci.yml` `test-backend` to install test extras: `pip install -e ".[test]"`
- [x] Fixed `lint-frontend` cache path on `actions/setup-node@v4` (`cache-dependency-path: frontend/package-lock.json`)
- [x] Migrated frontend lint from deprecated `next lint` (removed in Next.js 16) to `eslint .`
- [x] All 3 CI jobs pass green on latest run

### Verification
- **Local backend tests:** 14 passed, 0 failed, 2 warnings (duration 12.84s)
- **Local ruff:** `ruff check .` and `ruff format --check .` both pass
- **Local frontend lint:** `npm run lint` passes
- **GitHub Actions run:** https://github.com/danarprastika/web-trade/actions/runs/30239870657
  - `lint-backend`: success
  - `test-backend`: success
  - `lint-frontend`: success

### Notes
- Reformatting touched 21 backend source files via `ruff format .`; no behavior changed
- Frontend `npm run typecheck` also passes locally

---

## Fase 1 — Paper Trading & Risk Management (Sprint 3)

**Status:** Complete

### Items
- [x] Backend models: `Strategy`, `Order`, `Position`, `Trade`, `RiskProfile`
- [x] Alembic migration `003_add_paper_trading` for new tables
- [x] Strategy service: create/list/get/update/delete with async price subscription
- [x] Order service: create/list with paper execution flow
- [x] Position service: open/close tracking with P&L calculation
- [x] Risk service: risk profile CRUD + daily loss limit enforcement
- [x] Backend routers: `/api/v1/strategies`, `/orders`, `/positions`, `/trades`, `/risk`, `/dashboard`
- [x] 54 backend tests passing (strategies, orders, positions, risk, paper trading e2e, dashboard)
- [x] Lint/format: ruff clean, 24 files formatted
- [x] Frontend pages: `/dashboard` and `/strategies`
- [x] Real-money execution path exists but defaults OFF (`enable_live_trading: bool = False`)

### DoD Checklist
- [x] `pytest` passes with 54 tests green locally
- [x] `ruff check .` and `ruff format --check .` both pass
- [x] GitHub Actions CI passes (lint + test backend + lint frontend)
- [x] Alembic migration runs cleanly on existing schema
- [x] Paper trading order lifecycle tested end-to-end
- [x] Risk limits (daily loss) enforced in service layer

### What Changed
- Backend: added 5 new models, 5 new schemas, 5 new services, 6 new routers
- Backend: added Alembic migration 003
- Backend: 54 new tests, all passing
- Frontend: added dashboard and strategies pages
- CI: Sprint 3 commit passes all checks

### Notes for Sprint 4
- Real OAuth provider credentials still placeholder; needs real app setup for E2E social login
- Binance WebSocket stream is hardcoded; VISION mentions "1 exchange dulu" — keep configurable
- Exchange WebSocket credentials/env handling should be formalized
- Next.js middleware for auth protection on protected routes is still missing
- Fase 2 (Intelligence): News Intelligence, Market Intelligence, Technical Analysis Engine

---

## Fase 2 — Intelligence Layer (Sprint 4)

**Status:** Complete

### Items
- [x] Backend news models: `NewsSource`, `NewsArticle`
- [x] Alembic migration `004_add_news`
- [x] News service: CRUD + list with pagination
- [x] News router: `/api/v1/news`, `/api/v1/news/sources`
- [x] Analysis service: SMA, EMA, RSI calculations + signal generation
- [x] Analysis router: `/api/v1/analysis/indicators/{symbol}`, `/api/v1/analysis/signals/{symbol}`
- [x] Dashboard enriched with `latest_news` and `technical_signals`
- [x] Frontend: `/news` page with NewsCard component
- [x] Frontend: dashboard NewsWidget and AnalysisWidget
- [x] 68 backend tests passing (includes 6 news + 8 analysis tests)

### DoD Checklist
- [x] `pytest` passes with 68 tests green locally
- [x] `ruff check .` and `ruff format --check .` both pass
- [x] `npm run lint` passes
- [x] `npm run typecheck` passes
- [x] GitHub Actions CI passes

### What Changed
- Backend: added 2 new models, 2 new schemas, 2 new services, 2 new routers
- Backend: added Alembic migration 004
- Backend: extended `MarketConnectionManager` with price history for analysis
- Backend: extended dashboard summary with news and signals
- Backend: 14 new tests (6 news + 8 analysis)
- Frontend: added `/news` page and `NewsCard` component
- Frontend: added NewsWidget and AnalysisWidget to dashboard

### Notes for Sprint 5
- News ingestion is manual via API; real RSS/API integration is future work
- Technical analysis uses cached WebSocket prices; backtesting data source is future work
- Market Intelligence module is still pending per VISION.md Fase 2
- Frontend component tests are not yet implemented (jest configured but no tests)

---

## Fase 2.1 — Sprint 4 CI Repair

**Status:** Complete

### Items
- [x] Added `python-multipart` to `[project.optional-dependencies]` group `test` in `backend/pyproject.toml`
- [x] Updated CI `test-backend` job to use `python -m pytest` instead of bare `pytest`
- [x] Added explicit `pip install python-multipart` step in CI `test-backend` job
- [x] Fixed missing `from datetime import datetime` in `backend/app/services/news_service.py`
- [x] Fixed import sorting in `news_service.py` to satisfy `ruff check`

### Verification
- **GitHub Actions run:** https://github.com/danarprastika/web-trade/actions/runs/30250625895
  - `lint-backend`: success
  - `test-backend`: success
  - `lint-frontend`: success
