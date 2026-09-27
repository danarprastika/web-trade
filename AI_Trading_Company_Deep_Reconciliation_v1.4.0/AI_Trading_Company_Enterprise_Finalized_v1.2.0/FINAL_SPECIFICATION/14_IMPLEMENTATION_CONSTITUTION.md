# Implementation Constitution — Controlled Baseline v1.1.0

**Class:** Implementation-Control  
**Status:** Effective for controlled planning and authorized implementation gates  
**Applies:** G1–G11  
**Implementation authorization:** Not granted by this document

## 1. Purpose

Prevent implementation drift by requiring implementation agents to realize the approved architecture, preserve canonical contracts, and produce evidence. This document governs implementation workflow; it cannot override Normative Core.

## 2. Authority

The document classes and conflict procedure in `14_SOURCE_OF_TRUTH_AND_CHANGE_CONTROL.md` govern. This Constitution is Implementation-Control. It operationalizes the specification but cannot redefine trading authority, risk, security, isolation, domain semantics, or live gates.

If an implementation-control instruction conflicts with Normative Core, Normative Core prevails. If two applicable sources at the same level conflict and no approved precedence rule applies, stop and raise a Change Request.

## 3. Non-negotiable boundaries

Implementation agents MUST NOT:
- redefine authority ownership or create a second Risk authority;
- allow AI to bypass Risk or authorize itself for live trading;
- connect live brokers before applicable gates and explicit approvals;
- weaken fail-closed behavior;
- treat Signal as Order or proposed AI output as execution authority;
- mutate append-only audit or decision records;
- silently change canonical event names or state transitions;
- silently change canonical database semantics;
- introduce look-ahead into research/backtesting;
- reuse live credentials in research/demo environments;
- collapse isolated markets into an uncontrolled shared trading domain;
- claim a gate passed without required evidence and decision record.

## 4. Engineering freedom

Implementation agents may choose details intentionally left open only when:
- behavior remains contract-compatible;
- security and isolation requirements are preserved;
- tests and evidence prove the chosen behavior;
- the choice is documented and reversible where practical;
- it does not create a new architectural authority;
- required approval is obtained if the choice crosses a decision boundary.

## 5. Determinism and evidence

Where deterministic behavior is required, stable inputs, ordering, versioning, and reproducible outputs must be defined. Infrastructure nondeterminism must not be hidden behind claims of deterministic business behavior.

A feature is not implemented merely because source code exists. Gate evidence must include applicable implementation, automated tests, static/type/lint checks, security and trading review, contract traceability, known limitations, and a recorded gate decision.

## 6. Change rule

Changes to frozen architecture, authority, canonical vocabulary, event identity, state transitions, risk/live gates, isolation boundaries, or normative contracts require a Change Request and the approvals defined by the governance standard.

No implementation PR, commit, or patch may silently act as an architecture decision.

## 7. Sequential gate discipline

Follow the approved gate execution protocol. Do not skip gates by configuration, feature flags, manual database edits, hidden credentials, or undocumented exceptions. Later-gate work cannot compensate for a failed earlier gate.

## 8. Stop conditions

Stop and report rather than guess when:
- a normative contradiction is discovered;
- a required authority is ambiguous;
- a security boundary cannot be enforced;
- a canonical identifier is missing;
- a test cannot establish a mandatory invariant;
- implementation would require changing a frozen contract;
- required approval or evidence is absent.

The report must identify exact document/section references and propose a Change Request. Do not silently resolve the issue.

## 9. Long-lived production requirement

This is not an MVP-only exercise. Authorized implementation must address production-capable foundations, failure paths, security, observability, upgradeability, and maintainability according to the approved requirements.

## 10. Live boundary

Implementation progress does not imply live authorization. Live activation remains separately gated and requires all applicable prerequisites, approvals, security controls, operational controls, legal/account eligibility, and explicit human owner authorization.
