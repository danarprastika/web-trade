# Implementation Start — Kilo Code

Status: **READY TO IMPLEMENT**
Baseline: **AI Trading Company v1.0 FINAL / FROZEN**
Current gate: **G1 — Domain Foundation**

## Instruction

The architecture/documentation baseline has already been finalized and reconciled. Do not run another G0 architecture audit.

Use `FINAL_SPECIFICATION/` as the sole normative source of truth.

Begin implementation at G1 only.

### Required behavior

- Read the mandatory FINAL_SPECIFICATION documents listed in `FINAL_SPECIFICATION/13_KILO_CODE_HANDOFF.md`.
- Implement only G1 scope.
- Follow the exact canonical vocabulary, runtime contracts, state machines, authority model and security boundaries.
- Write tests for every implemented invariant.
- Produce implementation evidence and a G1 report.
- Stop at the G1 boundary after evidence is complete.
- Do not implement live broker connectivity.
- Do not invent unresolved provider-specific or production values.
- Do not alter architecture without an approved Change Request.

### G1 scope

Canonical IDs, timestamp semantics, fixed-precision money/quantity types, instrument primitives, canonical enums/error taxonomy, event envelope, command envelope, correlation/causation/idempotency semantics, configuration foundation, persistence foundation and migration framework, together with the tests required by `FINAL_SPECIFICATION/11_IMPLEMENTATION_GATES.md`.

**The next task is coding G1.**


## MAX IMPLEMENTATION CONTROL
Before coding, Kilo Code must also read FINAL_SPECIFICATION/14_IMPLEMENTATION_CONSTITUTION.md through
FINAL_SPECIFICATION/24_DEFINITION_OF_DONE.md as applicable to the current gate. G1 remains the only
permitted starting gate.


## Enterprise Final Baseline
The package is frozen as the enterprise implementation baseline. Polyglot language boundaries are selective and are not treated as security-by-obscurity. Future changes require the documented Change Request process.

## Final Language Boundary
Frontend: TypeScript. Backend: Go. Safety-critical core: Rust where justified. AI/Research: Python. Persistence: SQL. Infrastructure: IaC.
