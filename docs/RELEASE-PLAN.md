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
