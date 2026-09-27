# IMPLEMENTATION EVIDENCE STANDARD
## What Counts as Proof

Status: NORMATIVE

## 1. Principle

A claim of implementation must be supported by reproducible evidence.

## 2. Evidence Classes

### E1 — Source Evidence
Exact files/modules implementing the behavior.

### E2 — Unit Evidence
Focused tests proving local invariants.

### E3 — Integration Evidence
Tests proving component interaction and authority boundaries.

### E4 — Regression Evidence
Existing relevant tests remain passing.

### E5 — Static Evidence
Type checking, linting, formatting, dependency/security checks where configured.

### E6 — Runtime Evidence
Controlled execution logs/metrics/traces where applicable.

### E7 — Security Evidence
Permission, credential isolation, trust-boundary, adversarial-input, and fail-closed checks where applicable.

### E8 — Reproducibility Evidence
Stable command/configuration needed to reproduce the result.

## 3. Gate Minimum

Every gate requires:
- E1;
- E2;
- E4;
- E8.

Applicable gates additionally require E3, E5, E6, E7.

## 4. Negative Evidence

Tests must also prove forbidden behavior where the specification defines a safety boundary.

Examples:
- unauthorized command is rejected;
- invalid transition is rejected;
- Risk rejection cannot produce an OMS instruction;
- missing reconciliation does not produce a false authoritative state;
- research cannot access live credentials;
- untrusted external text cannot become executable authority.

## 5. Report Requirements

Each gate evidence report must state:
- environment;
- commit/build identifier if available;
- commands;
- result;
- test count;
- failures;
- skipped tests and reason;
- security checks;
- known limitations.

## 6. No Fake Evidence

Kilo Code MUST NOT:
- claim a test ran when it did not;
- claim a live integration was validated when it was not;
- convert static inspection into runtime evidence;
- hide failures by deleting/weakening tests;
- mark unimplemented behavior as PASS.
