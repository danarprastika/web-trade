# AI Trading Company — Finalized Documentation Baseline v1.1.0

**Baseline status:** FINALIZED FOR CONTROLLED DOCUMENTATION AND G1 PLANNING  
**Implementation authorization:** NOT GRANTED  
**Live-trading authorization:** NOT GRANTED

This package is the controlled documentation baseline for a personal-use, AI-native proprietary trading system intended to support a long-lived proprietary trading operation. Automated trading is the system’s primary purpose; AI agents provide governed intelligence and support capabilities.

## 1. Authority and source of truth

`FINAL_SPECIFICATION/` contains the controlled specification. Its documents are classified by function, not by filename or numeric prefix. The precedence and conflict procedure in `FINAL_SPECIFICATION/14_SOURCE_OF_TRUTH_AND_CHANGE_CONTROL.md` governs the package.

Supporting `docs/`, `.kilocode/`, audit templates, reports, examples, and generated artifacts must not redefine normative requirements. The exact baseline status, known blockers, and implementation boundary are recorded in `FINAL_SPECIFICATION/00_FINAL_STATUS.md` and `FINALIZATION_CHANGELOG.md`.

## 2. Non-negotiable trading authority chain

AI/strategy proposes → Risk Engine authorizes or vetoes → OMS accepts only valid risk-bound instructions → Execution acts only on authorized OMS instructions → Reconciliation verifies external state → Portfolio derives from verified/reconciled fills → Performance records outcomes → Research learns only from governed historical artifacts.

No AI agent, UI, Telegram command, model, provider adapter, or broker adapter may bypass this chain.

## 3. Markets and operating boundaries

Crypto, Forex, Stocks/Equities, and Commodities are independently governed market modules. Market availability requires market-specific data, instrument, provider, risk, legal/account eligibility, and readiness evidence.

Research, backtesting, simulation, paper, shadow, and live operation are distinct modes. Live activation is a separate owner-authorized decision and is not implied by documentation completion, tests, or gate progress.

## 4. Gate status

The package’s prior G0 PASS declaration is retained as a historical package declaration. The subsequent Phase 0 revalidation identified governance and contract issues that block G1 implementation. G1 may proceed only through authorized planning and closure of applicable blockers. See `G1_READINESS_AND_BLOCKERS.md`.

## 5. Implementation-agent boundary

The package contains Kilo Code-specific handoff material. Development agents are not runtime AI employees. Implementation agents must follow the approved gate workflow, stop on unresolved normative conflicts, and must not silently alter canonical contracts.

## 6. Finality and change control

This v1.1.0 baseline finalizes document authority, indexing, and the recorded G1 planning boundary. It does not assert that all implementation-specific provider values, legal eligibility, risk limits, deployment sizing, or production evidence have been completed. Changes to controlled requirements follow the Change Request process.

See:
- `FINAL_SPECIFICATION/00_FINAL_STATUS.md`
- `FINAL_SPECIFICATION/14_SOURCE_OF_TRUTH_AND_CHANGE_CONTROL.md`
- `FINALIZATION_CHANGELOG.md`
- `G1_READINESS_AND_BLOCKERS.md`


## v1.3.0 Enterprise Completion
This baseline adds an enterprise operating/governance layer covering organizational accountability, enterprise risk, compliance/legal controls, financial assurance, vendor governance, data stewardship, strategy/model governance, SRE/service ownership, identity/evidence, architecture/change governance, business continuity, capacity/cost, incident communication, and document control. These additions do not authorize implementation or live trading.

## Enterprise Control Plane Completion — v1.3.0

The v1.3.0 baseline adds a dedicated `ENTERPRISE_CONTROL_PLANE/` covering requirements traceability, control catalog, assurance/evidence, exception governance, secure SDLC, testing, data lineage, integration governance, asset/configuration management, identity, observability, continuity, provider certification, release assurance, financial-state assurance, AI/model assurance, privacy, and document baseline control.

`ENTERPRISE_DOCUMENT_REGISTER_v1.3.0.md` provides a deterministic corpus inventory. `ENTERPRISE_FULL_AUDIT_v1.3.0.md` records the static audit result and remaining reconciliation work.

These additions strengthen governance coverage; they do not silently approve unresolved Phase 0 decisions and do not authorize implementation or live trading.


## v1.4.0 Deep Reconciliation

See `DEEP_SPECIFICATION_RECONCILIATION_v1.4.0.md` and `CANDIDATE_CHANGE_REQUEST_REGISTER_v1.4.0.md`. This review does not authorize G1 implementation or live trading.
