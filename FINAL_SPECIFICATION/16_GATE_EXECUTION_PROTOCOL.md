# GATE EXECUTION PROTOCOL
## Mandatory Procedure for G1–G11

Status: NORMATIVE

## 1. One Gate at a Time

Kilo Code MUST execute exactly one implementation gate at a time.

Required sequence:
G0 → G1 → G2 → G3 → G4 → G5 → G6 → G7 → G8 → G9 → G10 → G11

G0 is already reconciled in the current package. Implementation starts at G1.

## 2. Gate Lifecycle

For each gate:

### STEP A — Read
Read:
- applicable FINAL_SPECIFICATION documents;
- applicable gate contract;
- relevant supporting docs;
- previous gate evidence.

### STEP B — Plan
Produce a bounded implementation plan:
- scope;
- files/modules;
- contracts;
- tests;
- risks;
- explicit exclusions.

### STEP C — Implement
Implement only the approved scope.

### STEP D — Verify
Run:
- unit/integration tests relevant to the gate;
- regression suite as practical;
- static/type/lint checks;
- security checks where applicable.

### STEP E — Evidence
Record:
- what changed;
- why;
- contract references;
- test results;
- verification commands/results;
- unresolved items.

### STEP F — Gate Decision
Only after evidence:
- PASS → gate may close;
- FAIL → remediate within gate;
- BLOCKED → stop and escalate;
- CHANGE REQUIRED → create Change Request and stop.

## 3. No Hidden Carryover

Unfinished work from a later gate MUST NOT be silently implemented during an earlier gate.

If a dependency is discovered, document it as:
- dependency;
- interface stub;
- test fixture;
- explicit future gate work.

## 4. Regression Rule

A later change must not silently invalidate a previously passed gate.

If it does, reopen the affected gate explicitly and record the reason.

## 5. Evidence Location

Gate reports MUST be stored in a dedicated implementation evidence location chosen by the repository, without replacing the normative FINAL_SPECIFICATION.

Suggested:
`audit/implementation/gates/G<n>/`

## 6. Gate Report Minimum Schema

Each report must contain:
- gate;
- status;
- scope;
- implementation summary;
- files changed;
- tests;
- static analysis;
- security checks;
- contract references;
- deviations;
- unresolved issues;
- next permitted gate.

## 7. Final Rule

A green test suite is evidence, not authority.

The governing specification remains authoritative.
