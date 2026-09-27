# Implementation Gates — Final / Frozen

| Gate | Scope | Required outcome |
|---|---|---|
| G0 | Specification integrity | Normative documents consistent, traceable and frozen |
| G1 | Domain foundation | Canonical primitives, envelopes, configuration, persistence, migrations |
| G2 | Data/market | Providers, quality, calendars, instruments, normalization, news/events |
| G3 | Trading core | Signal, intent, risk, capital, OMS, simulated execution, deterministic state |
| G4 | Research | Dataset, backtest, walk-forward, OOS, stress, replay, experiment registry |
| G5 | AI Company OS | Agent registry, tasks, scheduler, tools, memory, evaluation, supervision |
| G6 | Demo/Shadow | Isolated portfolios, shadow execution, promotion evidence |
| G7 | Web/Telegram | Same governed command/authorization path and audit |
| G8 | Broker adapters | Sandbox/demo certification, idempotency, reconciliation, provider certification |
| G9 | Security/operations | Secrets, observability, backup/restore, recovery, chaos, incident response |
| G10 | Production readiness | Full evidence, audits, controls and explicit production approval |
| G11 | Live gate | Explicit activation only after all prerequisites and eligibility are satisfied |

## Gate invariants
1. Gates are sequential unless an explicit dependency graph says otherwise.
2. A later gate cannot compensate for a failed earlier gate.
3. A configuration switch cannot satisfy a gate.
4. Live broker mutation is prohibited before the required G8/G9 evidence and G10/G11 approvals.
5. Every gate produces immutable evidence: scope, implementation changes, tests, security/trading review, known limitations, decision and traceability.
6. Any specification contradiction discovered during implementation pauses the affected gate and creates a Change Request.
