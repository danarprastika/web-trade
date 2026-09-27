# CANONICAL IMPLEMENTATION MAP
## Specification → Runtime Responsibility → Evidence

Status: NORMATIVE MAPPING / IMPLEMENTATION GUIDE

This document does not create new architecture. It maps existing frozen responsibilities to implementation areas.

## 1. Authority Chain

AI/Strategy/Signal proposal
→ Risk Engine authoritative decision
→ OMS instruction only after valid approval
→ Execution only valid instruction
→ Reconciliation authoritative broker-state comparison
→ Portfolio state derived from valid reconciled fills/state
→ Performance measurement
→ Research feedback

No downstream component may bypass an upstream mandatory authority.

## 2. Core Mapping

| Responsibility | Governing source | Implementation expectation |
|---|---|---|
| Command/Event envelopes | 02_RUNTIME_CONTRACTS | typed validated primitives |
| Order lifecycle | 03_STATE_MACHINES | explicit transition validation |
| Strategy lifecycle | 03_STATE_MACHINES | explicit promotion/suspension/retirement rules |
| Reconciliation | 03_STATE_MACHINES + 06 | authoritative state comparison |
| Canonical events | 04_EVENT_CATALOG | one identifier per canonical event |
| Database model | 05_DATABASE_CANONICAL_MODEL | no competing source of truth |
| Risk/live gates | 06_RISK_AND_LIVE_GATE | fail-closed enforcement |
| Self-improvement | 07_SELF_IMPROVEMENT_GOVERNANCE | evidence-driven promotion |
| Agent permissions | 08_AI_AGENT_GOVERNANCE | least privilege |
| Security | 09_SECURITY_MODEL | trust-zone enforcement |
| Observability | 10_OBSERVABILITY_AND_FAILURES | correlation + failure evidence |
| Gate control | 11_IMPLEMENTATION_GATES | one gate at a time |
| Audit/traceability | 12_TRACEABILITY_AND_AUDIT | evidence chain |
| Kilo Code workflow | 13_KILO_CODE_HANDOFF | implementation-only role |

## 3. Layering Rule

Implementation layers may be named differently from documentation terms, but semantic responsibility must remain one-to-one.

Do not create:
- duplicate Risk engines;
- duplicate portfolio authorities;
- duplicate reconciliation authorities;
- alternate event catalogs;
- shadow live-authority paths.

## 4. Market Isolation

Crypto, Forex, Stocks, and Commodities are independent market domains/configurations.

Shared infrastructure is allowed only when:
- contracts are explicit;
- state remains correctly scoped;
- credentials are isolated;
- risk policy is correctly scoped;
- failures can be contained to the intended domain.

## 5. Environment Isolation

Research, backtest, shadow, demo/paper, and live are distinct trust/runtime contexts.

Live credentials and live execution authority MUST NOT leak into lower environments.

## 6. AI Boundary

AI can propose, analyze, research, classify, coordinate, and perform permitted tasks.

AI does not become authoritative merely because an LLM or agent produced a confident result.

Risk, authorization, broker/external state, accounting/portfolio truth, and reconciliation remain governed by their specified authoritative components.
