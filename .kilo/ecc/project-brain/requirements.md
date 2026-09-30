# Requirements & Plan — web-trade

**Plan version:** 1.0.0
**Status:** AWAITING_APPROVAL
**Authority:** `docs/` (26 specs + `MANIFEST.json`). Precedence per `docs/25` §9.
**Baseline commit:** `15d978f` (main, clean working tree)

---

## 1. Source facts (verified, not assumed)

| # | Fact | Source | Verification |
|---|---|---|---|
| SF-1 | 26 authoritative Markdown specs exist and are final | `docs/00_README.md`, `docs/MANIFEST.json` | File listing + manifest read |
| SF-2 | Every manifest SHA-256 and byte length matches the packaged bytes | `docs/11_EXECUTION_GATES.md` G0 | **Executed** — 26/26 pass, 0 fail |
| SF-3 | No executable code exists at HEAD | `git ls-tree -r HEAD` | 27 tracked files, all under `docs/` |
| SF-4 | A prior FastAPI/Next.js codebase existed and was deleted | `git log --diff-filter=D` | Deleted in `be3ef5d` ("clear"); sprints 1-4 in `7327bfd`, `6f6bde0`, `49e98c2` |
| SF-5 | That deleted code is non-conformant with the blueprint | `docs/12_DECISION_REGISTER.md` ADR-001, ADR-003 | Python authoritative backend contradicts both ADRs |
| SF-6 | Go is the authoritative control plane | ADR-001 | Accepted |
| SF-7 | Live capability is deny-by-default and requires G0-G11 | `docs/11` G11, `docs/25` §3.7 | Binding |
| SF-8 | Waivers are prohibited for financial invariants, authorization, live credential isolation, reconciliation, halt controls, recovery | `docs/11` closing paragraph | Binding |
| SF-9 | Toolchain must be pinned at bootstrap to latest security-supported stable | `docs/00_README.md` toolchain lifecycle | Binding |
| SF-10 | Local toolchain: Go 1.26.2, Node 24.18.0, Python 3.14.6, Docker CLI 29.8.0 | `bash` version probes | Executed |
| SF-11 | Docker daemon is NOT running; Terraform and psql are NOT installed | `docker info`, `Get-Command` | Executed — recorded as RISK-01/RISK-02 |

## 2. Requirements traceability (blueprint area → work item → gate)

| Blueprint area | Source spec | Work items | Gate |
|---|---|---|---|
| Spec integrity | `00`, `11` (G0), `14` | WI-000 | G0 |
| Canonical types, money, time, IDs, envelopes, idempotency, errors | `03` | WI-105, WI-110 | G1 |
| Domain foundation, migrations, domain tests | `13` P1-P2, `11` (G1) | WI-101…108, WI-110…118 | G1 |
| Authority boundaries, bounded contexts, state machines, trust zones | `01` | WI-112…117 | G1 |
| Persistence, outbox, replay, reconciliation storage | `05` | WI-106, WI-120 | G1 |
| Market data normalization, freshness, provenance, replayable ingest | `16` | WI-130 | G2 |
| Risk veto, OMS state machine, ledger, halt, reconciliation tests | `04`, `05` | WI-114…116, WI-131 | G3 |
| Dataset registry, deterministic backtest, artifacts, no financial authority | `07` | WI-140 | G4 |
| Identity, model registry, decision ledger, tool permissions | `07`, `21`, `06` | WI-111, WI-141 | G5 |
| Simulation, shadow, fault injection, performance | `11` (G6) | WI-131, WI-160 | G6 |
| Web + Telegram on the same authorization path, privileged audit | `15`, `06`, `21` | WI-150 | G7 |
| Venue adapter contract, precision, rate limits, failure modes | `16`, `15` | WI-132 | G8 |
| Security scans, secrets isolation, observability, backup restore, DR | `06`, `08`, `10`, `22` | WI-160 | G9 |
| Production readiness, capacity, rollback, ownership | `19`, `09`, `24` | WI-165 | G10 |
| Live activation | `18`, `23`, `11` (G11) | WI-170 — **OUT OF SCOPE** | G11 |
| Polyglot boundaries and supply chain | `02` | WI-101…108, all | all |
| Config governance and risk policy | `17` | WI-112, WI-114 | G1, G10 |
| Governance, data, compliance | `18` | WI-112, WI-170 | G11 |
| Audit integrity, tamper-evident chain | `22` | WI-117, WI-124 | G1, G9 |
| Enterprise release standard | `24` | WI-107, WI-160, WI-165 | G9, G10 |

## 3. Assumptions (stated, reversible, not source facts)

- **A-1** The blueprint is authoritative and the deleted FastAPI/Next.js code is intentionally discarded. It violates ADR-001/ADR-003. Greenfield Go implementation per the canonical repository shape in `docs/00_README.md`.
- **A-2** "Implementation" means Phases 1-7 → G0-G10. Phase 8/G11 is not an engineering deliverable and stays disabled.
- **A-3** PostgreSQL 17 will run in Docker locally. The Docker daemon must be started by the operator.
- **A-4** Terraform production infrastructure is out of scope for now; `infra/terraform` is scaffolded with a documented apply path but not applied to any cloud.
- **A-5** Keycloak and OPA are consumed as external services behind defined interfaces; they are not built here. Local dev uses a documented stub/dev mode that cannot reach a `live` environment.
- **A-6** A single owner executes serially. Authority boundaries make parallel editing of `/services/control-plane` unsafe; delegation is used for read-only review only.

## 4. Architecture boundaries (summary — full detail in `architecture.md`)

- **Authority:** Risk veto > OMS state > Reconciliation truth > Ledger facts. AI, UI, research workers, cache, and adapters have zero financial authority.
- **Polyglot:** Go owns all authoritative transitions and must expose deterministic unit-testable functions. TypeScript is an untrusted client. Python is offline-only. Rust requires an ADR.
- **Trust zones:** edge, control, research, recovery. Research cannot route to control data stores. Edge cannot access databases. Venue adapters cannot modify policy, risk config, or ledger facts.
- **Concurrency:** optimistic version checks on OMS, reconciliation, configuration, and recovery. Last-write-wins is prohibited for authoritative state.
- **Fail-closed:** unknown authoritative state denies new risk-increasing activity and enters reconciliation. `UNKNOWN` submission outcome is never converted to rejection or fill by timeout assumption.

## 5. Phased work breakdown (canonical repo shape from `docs/00_README.md`)

### Phase 1 — Foundation (WI-101 … WI-108)
Repository scaffold (`/apps/web`, `/services/control-plane`, `/workers/research`, `/workers/backtest`, `/components/risk-engine`, `/components/oms`, `/components/reconciliation`, `/adapters/venues`, `/contracts`, `/db/migrations`, `/infra/terraform`, `/ops/runbooks`, `/tests`, `/docs`); Go module + pinned toolchain; Next.js app + pinned toolchain; Python workspace + pinned toolchain; contracts package; PostgreSQL 17 migration baseline with sqlc; GitHub Actions CI (format, lint, unit, contract validation, SAST, dependency scan, SBOM, provenance); local dev environment.

### Phase 2 — Domain core (WI-110 … WI-118)
Canonical types and envelopes; command/event envelopes; identity and authorization context; typed configuration with signed immutable release snapshots; strategy state machine; deterministic risk rules; OMS state machine; append-only ledger with compensating corrections; append-only tamper-evident audit chain; domain test suite.

### Phase 3 — Persistence and eventing (WI-120 … WI-125)
Transactional repositories via sqlc; transactional outbox; outbox dispatcher; database-enforced idempotency; replay utilities; reconciliation case storage; expand/contract migration discipline.

### Phase 4 — Market and execution (WI-130 … WI-132)
Market-data normalization and freshness controls; venue adapter interface; simulated execution; paper and shadow execution modes; reconciliation engine; adapter contract tests.

### Phase 5 — Research and AI governance (WI-140 … WI-142)
Dataset registry; deterministic backtest engine; experiment registry; model registry and evaluation; tool allowlists; decision ledger; promotion workflow with no autonomous authority escalation.

### Phase 6 — Operator plane (WI-150 … WI-152)
Next.js control plane consuming only the Go API; audit views; risk dashboards; operational controls including halt; Telegram as a secondary authenticated interface on the identical server-side authorization path.

### Phase 7 — Production hardening (WI-160 … WI-165)
Security testing and secrets isolation; performance and capacity tests; fault injection; backup restore; DR drill; observability validation; deployment rehearsal; rollback verification; release evidence package assembly.

### Phase 8 — Controlled activation (WI-170) — OUT OF SCOPE
G11 requires two distinct authorized approvers, verified adult account-holder authority, current exact-scope legal/venue eligibility, isolated live credentials with withdrawal/transfer disabled, and an immutable canary activation record. Not an engineering deliverable; remains deny-by-default.

## 6. Dependency order and integration strategy

```
G0 (done)
 └─ P1: WI-101 → WI-102/103/104 (parallel, disjoint dirs)
              → WI-105 (contracts) → WI-106 (migrations+sqlc) → WI-107 (CI) → WI-108 (dev env)
 └─ P2: WI-110 → WI-111, WI-112, WI-113 (parallel)
              → WI-114 (risk) → WI-115 (OMS) → WI-116 (ledger) → WI-117 (audit) → WI-118 [G1]
 └─ P3: WI-120 → WI-121/122 → WI-123/124/125
 └─ P4: WI-130 [G2] → WI-131/132 [G3, G6, G8]
 └─ P5: WI-140 [G4] → WI-141 [G5] → WI-142
 └─ P6: WI-150 → WI-151/152 [G7]
 └─ P7: WI-160 → WI-161/162/163 → WI-164 → WI-165 [G9, G10]
 X   P8: WI-170 [G11] — BLOCKED, out of scope
```

**Integration strategy.** Vertical slices close per phase. Each phase ends with a runnable, tested increment; no phase is marked complete on documentation. Cross-language contracts are validated from the single `/contracts` authority via shared fixtures in every producer/consumer language. Parallelism is limited to disjoint write scopes (UI vs control plane vs research worker).

**Critical path:** WI-105 (contracts) → WI-110 (canonical types) → WI-114 (risk) → WI-115 (OMS) → WI-120 (persistence) → WI-131 (execution). Everything in Phase 6+ depends on this chain.

## 7. Acceptance criteria and verification plan

Each work item carries acceptance criteria in `work-items.json`. Verification is layered:

| Layer | Mechanism | Applies to |
|---|---|---|
| L1 | `go build ./... && go vet ./... && go test ./...` | Go control plane, components |
| L2 | `npm run lint && npm run typecheck && npm run test` | Next.js UI |
| L3 | `pytest` in the Python workspace | Research workers |
| L4 | Contract conformance against `/contracts` fixtures, all languages | Every language boundary |
| L5 | `sqlc vet` + migration up/down rehearsal against PostgreSQL 17 | Persistence |
| L6 | Property/state-machine tests for OMS, risk, reconciliation | Financial invariants |
| L7 | Fault injection: timeouts, duplicate events, stale data, venue failure, DB failover, credential rejection | Phases 4, 7 |
| L8 | SBOM + provenance + artifact digest verification | CI/release |
| L9 | Gate report: reviewer, commit, timestamp, command output, binary PASS/FAIL, evidence digests | G0-G10 |

A gate is PASS only when every listed criterion is satisfied. Partial completion is FAIL. No gate is marked PASS on documentation alone.

## 8. Gates

G0 spec integrity → G1 domain foundation → G2 market data → G3 trading core → G4 research → G5 AI company OS → G6 simulation/shadow → G7 operator interfaces → G8 venue adapters → G9 security/operations → G10 production readiness. G11 live activation is blocked and out of scope.

## 9. Risks (summary — full register in `risks.md`)

RISK-01 Docker daemon not running (blocks all PostgreSQL work). RISK-02 Terraform absent. RISK-03 Python 3.14.6 scientific-stack wheel availability. RISK-04 Blueprint scope is enormous relative to a single-owner serial effort. RISK-05 Temptation to reintroduce a Python authoritative backend, violating ADR-001. RISK-06 Spec editorial duplication in `docs/00_README.md` (lines 35-37, 78-85) contradicts the `docs/25` §10 claim of repaired duplication — documentation-integrity risk only; digests still match, so G0 passes.

## 10. Open questions (blockers to full execution, not to Phase 1)

- **Q-1** Confirm greenfield Go implementation rather than restoring the deleted FastAPI codebase. (A-1)
- **Q-2** Confirm G11/live activation is out of scope for this effort. (A-2)
- **Q-3** Operator must start Docker Desktop before Phase 1 persistence work.
