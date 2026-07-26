# QuantX AI — Sprint 1 Specification (Fase 0: Foundation Layer)

## Vision Summary
QuantX AI is an enterprise-grade AI trading platform built with Clean Architecture, DDD, and SOLID principles. The platform uses a modular monolith architecture with clear module boundaries through package/namespace, not network calls.

## Users
- **Primary:** Retail/algorithmic traders who need a reliable, fast trading platform
- **Secondary:** Developers extending the platform with new strategies and AI modules

## Scope — In (Sprint 1)
1. Monorepo scaffold: backend (FastAPI/Python) + frontend (Next.js/TypeScript)
2. Production database schema for: Users, Trading Accounts, Assets
3. Alembic migrations that run clean from empty database
4. Authentication: register + login via email, JWT + refresh token
5. Health-check endpoint validating real database connectivity
6. GitHub Actions CI: lint, format check, test

## Scope — Out (Sprint 1)
- Google/GitHub OAuth login
- Trading, dashboard, watchlist, AI modules
- Fase 1 and above

## Architecture
See `docs/ARCHITECTURE.md` for full rationale.

## Vertical Slices

### Slice 1: Monorepo Scaffold and CI Bootstrap
- Initialize monorepo with `backend/` and `frontend/` directories
- Backend: FastAPI project with pydantic-settings, pytest, ruff, mypy
- Frontend: Next.js 14 with TypeScript, TailwindCSS, shadcn/ui
- Alembic configured for database migrations
- GitHub Actions workflow: lint, format check, test for both backend and frontend
- `.gitignore`, `README.md`, environment variable templates

### Slice 2: Database Foundation
- PostgreSQL schema: `users`, `trading_accounts`, `assets`
- Alembic migrations (autogenerate + manual polish)
- SQLAlchemy 2.x async models with proper indexes
- Database connection pooling via asyncpg
- Seed script for minimal required data (e.g., asset base types)

### Slice 3: Authentication Core
- Register endpoint: email validation, password hashing (bcrypt via passlib), unique constraint handling
- Login endpoint: form-based (OAuth2PasswordRequestForm), JWT access token + refresh token
- Token validation middleware/dependencies
- Protected route example
- Password confirmation in registration
- Rate limiting on auth endpoints using slowapi

### Slice 4: Health Check and Observability
- `GET /health` endpoint returning JSON with status, timestamp, version
- `GET /health/ready` with real PostgreSQL connection test (SELECT 1)
- Structured logging (structlog) with request IDs
- Environment-based configuration (pydantic-settings)

### Slice 5: Frontend Auth Pages
- Login page with email/password
- Register page with confirmation
- Form validation (React Hook Form + Zod)
- API client wrapper with error handling
- Token storage in httpOnly cookies (backend Set-Cookie) — NOT localStorage per security review
- Redirect logic for authenticated/unauthenticated users

## Design Direction (Frontend)
- **Purpose:** Login/register gate for a trading platform
- **Audience:** Traders and quants who expect fast, reliable, professional interfaces
- **Tone:** Industrial precision, calm, dark-first with high contrast
- **Memorable detail:** Subtle terminal-inspired monospace accents for labels, tight data-dense layout
- **Constraints:** shadcn/ui components, TailwindCSS, dark mode default (traders work late), no decorative gradients, no hero copy bloat

## Commit Strategy
Conventional commits:
- `feat(backend): scaffold FastAPI project with lint/test`
- `feat(backend): add user and trading account models with migrations`
- `feat(backend): implement JWT auth with refresh tokens`
- `feat(backend): add database-connected health check endpoint`
- `feat(frontend): scaffold Next.js with auth pages`
- `feat(ci): add GitHub Actions lint/test workflow`
- `chore: configure Alembic and pydantic-settings`
- `test: add auth integration tests`
- `docs: add RELEASE-PLAN.md and BUILD-REPORT.md`
