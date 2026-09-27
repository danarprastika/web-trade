# Final Status — AI-Native Proprietary Trading Company

**Baseline:** v1.1.0  
**Status:** FINALIZED DOCUMENTATION BASELINE — CONTROLLED G1 PLANNING  
**Effective scope:** Document authority, source-of-truth, index, and readiness status  
**Implementation authorization:** NOT GRANTED  
**Live-trading authorization:** NOT GRANTED

## 1. Project identity and scope

This is a personal-use, AI-native proprietary trading system intended to support a long-lived trading operation. Automated trading is its primary purpose; AI models and agents are intelligence capabilities supporting the trading system.

The target market domains are Crypto, Forex, Stocks/Equities, and Commodities, each independently governed. V1 excludes SaaS, multi-tenancy, billing, customer accounts, public strategy marketplace, and social trading unless separately approved by a controlled change.

## 2. Core authority chain

AI/strategy proposes → Risk Engine authorizes/vetoes → OMS accepts only valid risk-bound intents → Execution Adapter executes only OMS instructions → Reconciliation verifies external state → Portfolio derives state from verified/reconciled fills → Performance records outcomes → Research learns only from governed historical artifacts.

No AI agent, UI, Telegram command, model, provider adapter, or broker adapter may bypass this chain.

## 3. Hard boundaries

- Live is a separate environment with separate credentials, deployment, data policy, approvals, and operational controls.
- Research and analysis agents have no live credentials or direct broker-mutation authority.
- Runtime AI employees are distinct from development agents.
- Unknown, stale, mismatched, unauthorized, or indeterminate critical state fails closed for live mutation.
- Market modules are isolated failure domains.
- Demo/paper/shadow learning and live execution are separated by environment and promotion evidence.
- Risk policy and live permissions cannot be changed by an AI agent acting alone.
- No implementation gate may be skipped through configuration, feature flags, manual database edits, hidden credentials, or undocumented exceptions.

## 4. Specification authority

`FINAL_SPECIFICATION/` is the controlled specification set. The authority classes and conflict procedure are defined in `14_SOURCE_OF_TRUTH_AND_CHANGE_CONTROL.md`. Numeric prefixes are identifiers/navigation aids only and do not establish precedence.

The authority classification is:
1. Normative Core: canonical domain, trading, risk, security, isolation, data, and runtime contracts.
2. Implementation-Control: gate workflow, implementation contract, repository/evidence guidance, checklists, and Definition of Done. These may operationalize but cannot weaken Normative Core.
3. Governance Records: approved decisions, change requests, and baseline status records. They are binding only within their approved scope.
4. Supporting and Agent-Specific material: explanatory or tool-specific content; it cannot override the controlled specification.

If sources at the same authority level conflict, stop the affected work and create a Change Request. Do not choose by filename, date, numeric prefix, or agent preference.

## 5. Gate and readiness status

The package’s G0 PASS declaration is retained as a historical package declaration. The Phase 0 revalidation identified unresolved authority, change-control, vocabulary, error-taxonomy, and event/state traceability issues. Accordingly:

- G1 planning may continue only within the documented boundaries.
- G1 implementation is blocked until all applicable blockers are formally dispositioned and entry criteria are met.
- No code, broker integration, live credentials, or live trading is authorized by this status.
- Gate completion requires evidence and an explicit gate decision; passing tests alone is insufficient.

See `G1_READINESS_AND_BLOCKERS.md` and the Phase 0 decision records supplied with the project.

## 6. Freeze and change rule

Changes to risk, order semantics, execution behavior, state machines, event semantics, promotion gates, credential access, environment boundaries, canonical entities, or live configuration require a versioned Change Request, impact analysis, affected tests, reviewer approval, migration/rollback plan where applicable, and release traceability.

## 7. Live disclaimer

This document finalizes the documentation baseline’s authority and planning status; it does not authorize live trading. Live activation remains subject to all required gates, provider certification, legal/account eligibility, security and operational readiness, risk approval, and explicit owner authorization.
