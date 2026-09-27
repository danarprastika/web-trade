# Kilo Code Handoff — Final / Frozen

Kilo Code is the implementation, test, and gate-evidence executor. The specification baseline has already been finalized and reconciled. Kilo Code must not perform a second architecture-finalization exercise or silently resolve specification contradictions.

## Mandatory reading order
1. `FINAL_SPECIFICATION/00_FINAL_STATUS.md`
2. `FINAL_SPECIFICATION/01_ARCHITECTURE_DECISIONS.md`
3. `FINAL_SPECIFICATION/02_RUNTIME_CONTRACTS.md`
4. `FINAL_SPECIFICATION/03_STATE_MACHINES.md`
5. `FINAL_SPECIFICATION/04_EVENT_CATALOG.md`
6. `FINAL_SPECIFICATION/05_DATABASE_CANONICAL_MODEL.md`
7. `FINAL_SPECIFICATION/06_RISK_AND_LIVE_GATE.md`
8. `FINAL_SPECIFICATION/07_SELF_IMPROVEMENT_GOVERNANCE.md`
9. `FINAL_SPECIFICATION/08_AI_AGENT_GOVERNANCE.md`
10. `FINAL_SPECIFICATION/09_SECURITY_MODEL.md`
11. `FINAL_SPECIFICATION/10_OBSERVABILITY_AND_FAILURES.md`
12. `FINAL_SPECIFICATION/11_IMPLEMENTATION_GATES.md`
13. `FINAL_SPECIFICATION/12_TRACEABILITY_AND_AUDIT.md`

## Execution workflow
Start at G1. For each gate: read the required normative contracts → plan only that gate → implement only that gate → run required tests → produce evidence and a gate report → stop. Do not begin a later gate until the current gate is accepted.

## Prohibited behavior
- no live broker connectivity before the relevant gates
- no bypass of Risk Engine, OMS or Reconciliation
- no direct mutation of portfolio/accounting state outside governed paths
- no self-promotion by runtime agents
- no hidden credentials or undocumented environment access
- no architecture change disguised as refactoring
- no silent interpretation of contradictions

## Contradiction protocol
Stop the affected gate. Record the conflict, affected artifacts, proposed resolution, tests and migration/rollback impact in a Change Request. Implementation resumes only after the change is approved and the normative documents are updated.


## Long-lived production requirement
This implementation is NOT an MVP exercise. Kilo Code must implement production-capable foundations, failure paths, security, observability, upgradeability, and maintainability rather than optimizing for a demo or happy-path success.
