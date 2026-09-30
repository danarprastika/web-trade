# Architecture — web-trade

Derived strictly from the authoritative blueprint. No architectural decision is invented here; every boundary below cites its source.

## 1. Authority hierarchy (source: `docs/01` §3, `docs/25` §3)

1. Owner/operator approval — controls activation and high-impact configuration.
2. **Risk Engine** — the authoritative financial veto. Deterministic. No AI, UI, or venue response can override it.
3. **OMS** — authoritative for canonical internal order state.
4. **Reconciliation** — authoritative for resolving venue discrepancies.
5. **Ledger** — authoritative for financial facts (append-only, compensating corrections).
6. Strategy and AI — propose only.
7. UI, Telegram, research workers, caches, analytics projections — zero financial authority.

**Operating rule:** AI may propose. Deterministic controls decide. The OMS records authoritative order state. Reconciliation resolves external truth. The ledger records financial facts.

## 2. Runtime topology (source: `docs/01` §1)

```
Browser / Telegram
       |
  API Gateway / WAF
       |
  Go Control Plane
  |    |     |     |            |
Auth  Strategy Risk  OMS  Reconciliation
  |    |     |     |            |
  +----+--+--+--+----+
             |
        PostgreSQL 17
             |
     Transactional Outbox
             |
     Event Dispatcher
             |
       Venue Adapters
             |
       External Venue

Python Research/Backtest -- versioned artifacts --> Control Plane validation
Rust components ---------- contract boundary ----> owning Go service
```

## 3. Bounded contexts (source: `docs/01` §2)

Identity and Access · Configuration · Market Data · Research · Strategy · Risk · OMS · Execution · Reconciliation · Portfolio and Ledger · Intelligence (never authoritative for execution) · Audit · Operations.

## 4. Control-plane module decomposition (source: `docs/01` §7)

| Module | Owns | Must never own |
|---|---|---|
| Identity | subject/session/context validation | financial state |
| Policy | RBAC/ABAC decisions, policy versions | order state |
| Configuration | typed configuration, release snapshots | runtime secrets |
| Risk | deterministic authorization/veto | venue connectivity |
| OMS | canonical order state machine | external venue truth |
| Reconciliation | internal vs external convergence | policy authority |
| Ledger | immutable financial facts | strategy decisions |
| Audit | security/decision/configuration evidence | business truth outside evidence records |
| Operations | deployment/recovery/health state | financial authorization |

**Rule:** no module invokes another by reaching around its public contract. Direct table writes outside the owning module are prohibited. Cross-module mutation occurs only through explicit application commands or transactional events.

## 5. Polyglot boundaries (source: `docs/02`, `docs/25` §4)

| Component | Runtime | Permitted | Prohibited |
|---|---|---|---|
| Operator app | TypeScript / React / Next.js | operator workflows, dashboards, presentation validation, accessibility | risk authorization, secret custody, direct DB or venue access |
| Control plane | Go | identity enforcement, policy integration, domain commands, config, risk, OMS, reconciliation, ledger APIs | delegating final financial authority to AI or UI |
| Research/backtest | Python | offline experiments, dataset processing, deterministic simulation, artifacts | live credentials, authoritative writes, self-promotion |
| Safety extension | Rust (ADR only) | narrowly bounded memory-safety/performance component | second domain authority, bypassing Go contracts |
| Persistence | PostgreSQL 17 | constraints, transactional invariants, migrations, durable records | treating cache/bus/analytics as truth |
| Contracts | versioned language-neutral schemas | compatibility, validation, idempotency, trace context, error semantics | implicit cross-language object sharing, unversioned payloads |

Each boundary requires contract tests, schema compatibility checks, tracing propagation, error mapping, resource limits, and an owner. The initial control plane is a **modular monolith** to preserve transaction and authority clarity. Premature microservice fragmentation is prohibited.

## 6. State-machine discipline (source: `docs/01` §8)

Authoritative state machines are closed sets. Every transition declares: actor, command, precondition, resulting state, event, idempotency key, audit record, failure behavior. Unknown states, unknown transitions, missing sequence numbers, or invalid version vectors are rejected into a controlled reconciliation path. OMS, reconciliation engine, configuration service, and recovery controller use optimistic concurrency/version checks. Last-write-wins is prohibited for authoritative financial or security state.

## 7. Trust zones (source: `docs/01` §9)

Four hard zones: **edge**, **control**, **research**, **recovery**. Research workloads cannot route to live control-plane data stores. Recovery uses separately managed administrative credentials and trusted artifact manifests. Edge cannot access databases. Venue adapters cannot modify policy, risk configuration, or ledger facts.

## 8. Environments (source: `docs/01` §4)

`dev`, `test`, `staging`, `paper`, `shadow`, `live`. Each has separate credentials, database, encryption keys, deployment identity, network policy, and configuration namespace. Live credentials are never available to lower environments.

## 9. Failure rule (source: `docs/01` §6, `docs/25` §6)

When authoritative state cannot be established: fail closed for new risk-increasing actions, preserve observable state, record the uncertainty, start reconciliation. Unknown external outcomes are never converted into deterministic failure by assumption.

Mandatory responses (source `docs/25` §6):

| Failure | Response |
|---|---|
| Identity provider unavailable | Deny new privileged sessions and mutations; never bypass SSO |
| Authorization policy stale/unverifiable | Fail closed for privileged and risk-increasing commands; alert policy owner |
| PostgreSQL primary unavailable | Stop authoritative mutations; never substitute cache/bus/memory as truth |
| Outbox dispatch delayed | Preserve committed records, alert on lag, bounded backpressure; no loss, no duplicate transition |
| Venue request timeout | Persist unknown outcome, reconcile before any exposure-increasing retry |
| Market data stale/contradictory | Mark feed unhealthy; deny dependent commands; retain provenance and alert |
| Audit sink unavailable | Bounded durable buffer; block sensitive operations before evidence loss; never silently drop |
| Configuration signature invalid | Reject; last known-good only if validity and freshness proven, else safe halt |
| Region failover | Enter `RECOVERY_HOLD`; verify ledger, OMS, outbox, audit checkpoints, reconciliation before resume |
| Model registry/research compromised | Revoke workload identity, quarantine artifacts, block promotion, preserve forensics |
| Secret/key compromised | Revoke/rotate, invalidate dependent sessions, assess signed audit and artifact integrity |
| Feature flag service unavailable | Last verified safe snapshot within configured freshness only; unknown flags never grant authority |
| Capacity saturation | Backpressure; shed non-authoritative workloads first; preserve risk, OMS, ledger, audit, halt |

## 10. Architectural invariants (source: `docs/01` §10)

1. No AI/model output can authorize its own execution.
2. No cache can become authoritative through fallback behavior.
3. No retry may transform an unknown external outcome into a second exposure-increasing command.
4. No restored environment may leave `RECOVERY_HOLD` without independent verification.
5. No stale authorization context beyond the configured revocation window.
6. No undocumented configuration may enter the live configuration snapshot.
7. No schema migration may require simultaneous deployment of an incompatible producer and consumer.
8. No telemetry pipeline outage may disable preservation of mandatory security and financial evidence.

## 11. Security architecture (source: `docs/06`, `docs/21`, ADR-017/018)

Zero Trust: authenticate every workload and operator, authorize each request, deny by default, short-lived workload identity, network segmentation. Keycloak is the reference workforce identity broker; OIDC Authorization Code + PKCE is the application protocol; SAML is accepted only at the federation boundary. Open Policy Agent evaluates identity/resource authorization policy; Go domain code owns trading-risk decisions. Signed, versioned policy bundles fail closed when stale. Phishing-resistant step-up, exact-diff approval, two-person control, bounded break-glass, post-use review. SCIM lifecycle where supported. Audit chain: signed hash-chain checkpoints plus independent immutable retention (ADR-022) — no public blockchain.

## 12. Canonical repository shape (source: `docs/00_README.md`)

```text
/apps/web
/services/control-plane
/workers/research
/workers/backtest
/components/risk-engine
/components/oms
/components/reconciliation
/adapters/venues
/contracts
/db/migrations
/infra/terraform
/ops/runbooks
/tests
/docs
```

## 13. Toolchain (pinned at bootstrap, source: `docs/00_README.md` toolchain lifecycle)

Latest stable security-supported release at bootstrap; exact versions pinned in lockfiles; selected versions recorded in G1 evidence; EOL prohibited; monthly security review; critical/high fixes within 14 days; routine patches quarterly; major upgrades require compatibility tests, migration notes, and an ADR; CI fails on unpinned dependencies or toolchain drift.

Observed on this host: Go 1.26.2, Node 24.18.0, Python 3.14.6, Docker CLI 29.8.0 (daemon not running), Terraform absent.

## 14. Documented deviation from a prior implementation

The deleted sprint 1-4 codebase (`backend/` FastAPI, `frontend/` Next.js) placed a Python service in the authoritative position. That is a direct contradiction of ADR-001 and ADR-003. It is **not** a restore target. It may be mined for domain vocabulary and test scenarios only, and any code carried forward must be re-expressed against the Go authority model and `/contracts`.
