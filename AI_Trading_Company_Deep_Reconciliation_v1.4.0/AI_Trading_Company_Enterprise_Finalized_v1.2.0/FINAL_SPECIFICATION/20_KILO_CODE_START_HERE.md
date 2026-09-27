# KILO CODE START HERE
## FINAL / FROZEN IMPLEMENTATION BASELINE v1.0

Status: EXECUTION ENTRYPOINT
Audience: Kilo Code

## 1. Mission

Implement the frozen AI-native proprietary trading system.

You are now the implementation and verification executor.

You are NOT the architecture owner.

## 2. Read First

Mandatory order:

1. `FINAL_SPECIFICATION/00_FINAL_STATUS.md`
2. `FINAL_SPECIFICATION/14_SOURCE_OF_TRUTH_AND_CHANGE_CONTROL.md`
3. `FINAL_SPECIFICATION/15_CANONICAL_VOCABULARY.md`
4. `FINAL_SPECIFICATION/16_AUTHORITY_AND_PERMISSION_MATRIX.md`
5. `FINAL_SPECIFICATION/17_EVENT_STATE_TRACEABILITY.md`
6. `FINAL_SPECIFICATION/18_ENVIRONMENT_AND_MARKET_ISOLATION.md`
7. `FINAL_SPECIFICATION/14_IMPLEMENTATION_CONSTITUTION.md`
8. `FINAL_SPECIFICATION/16_GATE_EXECUTION_PROTOCOL.md`
9. `FINAL_SPECIFICATION/18_CANONICAL_IMPLEMENTATION_MAP.md`
10. `FINAL_SPECIFICATION/19_IMPLEMENTATION_EVIDENCE_STANDARD.md`
11. `FINAL_SPECIFICATION/15_G1_IMPLEMENTATION_CONTRACT.md`
12. `FINAL_SPECIFICATION/13_KILO_CODE_HANDOFF.md`

Then read supporting documentation relevant to G1.

## 3. Current Gate

G0 is complete and frozen.

START AT G1.

Do not rerun architecture design.
Do not redesign the system.
Do not connect live brokers.
Do not introduce live credentials.

## 4. Execution Mode

For G1:
1. inspect repository;
2. inspect current implementation status;
3. map existing code to frozen contracts;
4. implement missing G1 foundation;
5. add/repair tests;
6. run verification;
7. write evidence;
8. report PASS/FAIL/BLOCKED.

## 5. If You Find a Contradiction

Do not guess.

Use:
`FINAL_SPECIFICATION` → implementation-control docs → supporting docs.

If the contradiction affects a frozen normative contract:
STOP and create a Change Request.

## 6. If a Detail Is Intentionally Open

Choose the smallest defensible implementation that:
- preserves the contract;
- preserves security;
- is testable;
- is documented.

Do not invent product behavior unnecessarily.

## 7. Success Condition

Success is not “the code looks complete.”

Success is:
- contract-compatible;
- tested;
- secure;
- observable where applicable;
- reproducible;
- evidence-backed;
- gate-bounded.

## 8. Absolute Boundary

No live trading authorization is implied by implementation progress.


## Long-lived production requirement
This implementation is NOT an MVP exercise. Kilo Code must implement production-capable foundations, failure paths, security, observability, upgradeability, and maintainability rather than optimizing for a demo or happy-path success.
