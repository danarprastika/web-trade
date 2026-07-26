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

