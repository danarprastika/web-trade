# QuantX AI — Architecture Decision Records (Fase 0)

## ADR-001: Modular Monolith vs Microservices

**Decision:** Modular Monolith
**Status:** Accepted

**Context:**
QuantX AI needs to manage trading data, user accounts, market data, AI modules, and more. Early architecture choices set the trajectory for the entire platform.

**Alternatives Considered:**
1. **Modular Monolith** (chosen)
   - Clear module boundaries via Python packages and namespaces
   - Single deployment unit, single database
   - Easy local development, simple CI/CD
   - Can extract to microservices later when there's concrete evidence of need
2. **Microservices from day one**
   - Separate services for users, trading, market data, AI
   - Independent scaling and deployment
   - High operational complexity, network latency, distributed transactions
   - Overkill for a team just starting out

**Rationale:**
VISION.md explicitly mandates "Modular Monolith — bukan microservices. Batas antar modul jelas lewat package/namespace, bukan lewat network call, sampai ada alasan konkret untuk memisah jadi layanan sendiri." Microservices introduce unnecessary complexity in Fase 0-1 when the domain boundaries are still being validated.

## ADR-002: FastAPI + SQLAlchemy 2.x Async + PostgreSQL

**Decision:** FastAPI with async SQLAlchemy 2.x, PostgreSQL, Alembic
**Status:** Accepted

**Context:**
Backend technology selection for a high-throughput trading platform.

**Alternatives Considered:**
1. **FastAPI + SQLAlchemy 2.x async + PostgreSQL** (chosen)
   - Native async support, mature ecosystem
   - OpenAPI docs auto-generated
   - Excellent Python type safety with Pydantic v2
   - Alembic for migrations
2. **Django REST Framework**
   - More batteries-included, but heavier
   - Async support still maturing (Django 5.x improved but not as clean as FastAPI)
   - Less flexible for custom trading-specific patterns
3. **Go + Gin/GORM**
   - Better raw performance, but smaller AI/ML ecosystem
   - Team expertise in Python (per VISION.md)
4. **Node.js + Prisma**
   - Good DX, but fewer enterprise trading precedents
   - TypeScript type safety is good but Python's typing + Pydantic is tighter for data contracts

**Rationale:**
FastAPI provides the best balance of performance, async-native design, type safety, and Python ecosystem access for AI/quant workloads. SQLAlchemy 2.x async with PostgreSQL is proven at scale. Alembic handles schema evolution cleanly.

## ADR-003: JWT with Refresh Tokens Stored in HttpOnly Cookies

**Decision:** JWT access + refresh tokens; refresh tokens stored in httpOnly, Secure, SameSite=Strict cookies
**Status:** Accepted

**Context:**
Authentication security for a financial platform. OWASP Top 10 compliance required.

**Alternatives Considered:**
1. **JWT + httpOnly refresh cookie** (chosen)
   - Access token in memory (JS variable, not storage)
   - Refresh token in httpOnly cookie (inaccessible to XSS)
   - CSRF protection via SameSite=Strict + double-submit cookie pattern
2. **JWT in localStorage**
   - Simpler implementation
   - Vulnerable to XSS token theft — FAIL for financial platform
3. **Session cookies only**
   - Requires server-side session store (Redis)
   - Stateless JWT is preferred for API-first architecture
   - Redis adds operational dependency

**Rationale:**
HttpOnly cookies protect against XSS. SameSite=Strict + CSRF token protects against CSRF. Stateless JWT eliminates session store. This satisfies OWASP Top 10 auth requirements.

## ADR-004: GitHub Actions for CI/CD

**Decision:** GitHub Actions
**Status:** Accepted

**Context:**
CI pipeline for lint, format check, and test on every push.

**Alternatives Considered:**
1. **GitHub Actions** (chosen)
   - Native to GitHub, no external service
   - Matrix builds for backend/frontend
   - Free for public repos, generous for private
   - Artifact upload for coverage reports
2. **GitLab CI**
   - More powerful but requires GitLab
   - Team uses GitHub
3. **CircleCI / Travis**
   - External dependency, cost, less integrated

**Rationale:**
GitHub Actions is the natural choice for a GitHub-hosted repo with no additional infrastructure.

## ADR-005: Repository Pattern + Service Layer + Unit of Work

**Decision:** Repository Pattern + Service Layer + explicit Unit of Work via session.commit()
**Status:** Accepted

**Context:**
Backend code organization for maintainability and testability.

**Alternatives Considered:**
1. **Repository Pattern + Service Layer** (chosen)
   - Repositories abstract SQLAlchemy queries
   - Services contain business logic and transaction boundaries
   - Thin FastAPI routers (dependency injection)
   - Highly testable with mocked repositories
2. **Active Record (Django-style)**
   - Models contain business logic
   - Simpler but harder to test and violates separation of concerns
3. **Direct SQLAlchemy in routers**
   - Fastest to write, fastest to become unmaintainable
   - Mixes HTTP concerns with data access and business logic

**Rationale:**
Clean Architecture demands separation of concerns. Repositories + Services enable unit testing, clear transaction boundaries, and domain logic that is independent of FastAPI.

## ADR-006: CQRS Not Applied in Fase 0-1

**Decision:** Defer CQRS to reporting-heavy modules only
**Status:** Accepted

**Context:**
VISION.md states "CQRS hanya diterapkan di modul yang benar-benar butuh (mis. reporting berat), bukan dipaksakan di semua tempat sejak awal."

**Rationale:**
CQRS adds significant complexity (separate read/write models, eventual consistency, event sourcing). For Fase 0-1 with simple CRUD, it is premature optimization. Apply only to Analytics/Reports module later.

## ADR-007: Domain Events In-Process First

**Decision:** In-process event bus (no separate message broker)
**Status:** Accepted

**Context:**
VISION.md: "Domain Events + Event Bus (in-process dulu, bukan message broker terpisah, sampai ada bukti nyata butuh itu)"

**Rationale:**
Adding Redis/RabbitMQ in Fase 0 adds infrastructure complexity without proven need. A simple Python event bus (list of callbacks or pub/sub) suffices for Fase 0-1. Scalable message broker can be added when event volume or cross-service need is demonstrated.

## Rejected Alternatives Summary

| Alternative | Reason Rejected |
|-------------|-----------------|
| Microservices | Overkill, violates VISION.md explicit monolith mandate |
| Django REST Framework | Async not mature enough, heavier, less flexible |
| Node.js + Prisma | Smaller quant/AI ecosystem, team expertise in Python |
| JWT in localStorage | XSS vulnerability, fails OWASP Top 10 |
| Immediate CQRS | Premature, violates VISION.md guidance |
| External message broker | No proven need, adds ops burden |
