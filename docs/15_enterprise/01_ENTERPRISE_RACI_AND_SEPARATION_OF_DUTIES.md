# Enterprise RACI and Separation of Duties

> Status: ENTERPRISE DOCUMENTATION BASELINE v1.2.0 — controlled planning baseline; subordinate to the applicable Normative Core and approved contracts.

## Purpose
Make accountability explicit and prevent one actor or agent from designing, approving, deploying and operating a sensitive change alone.

## Authority and interpretation
- This document defines control intent and operating expectations; it does not silently approve unresolved values, credentials, legal positions, capital limits, or live activation.
- Where a value is marked TBD, it requires explicit owner-approved decision evidence before implementation may depend on it.
- Same-tier conflicts are fail-closed and require a recorded change request or decision.

## Control domains
Architecture; risk policy; strategy promotion; model/prompt promotion; data provider onboarding; broker onboarding; credential administration; deployment; live activation; incident response; audit evidence.

## RACI rules
Every critical control has exactly one accountable owner, at least one responsible executor, and named consultation/information paths. “AI agent” may be responsible for bounded automation but is never the accountable authority for live capital decisions.

## Dual control
Sensitive actions such as live activation, credential rotation into production, disabling safety controls, changing risk limits, or approving high-impact model/strategy promotion require two independent approvals where the applicable control contract calls for dual control.

## Conflict handling
If an actor has incompatible roles, the action is blocked until an independent approver is assigned. Emergency stop actions may be performed by the designated emergency authority and must be reviewed afterward.

## Evidence
RACI assignments, approval identities, timestamps and control versions are retained in the audit trail.
