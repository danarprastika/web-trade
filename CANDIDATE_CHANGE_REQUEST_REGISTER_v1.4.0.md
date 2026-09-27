# Candidate Change Request Register — v1.4.0

Status: Draft proposals only. No approval implied.
Baseline: AI Trading Company Enterprise Documentation v1.3.0

| Candidate ID | Subject | Primary gap | Required outputs | Approval boundary |
|---|---|---|---|---|
| CR-CAND-01 | Canonical Event Envelope | Envelope fields and semantics not fully enumerated | schema, examples, compatibility rules, tests | Architecture + domain owner |
| CR-CAND-02 | Canonical Command Envelope | No single complete authoritative command schema | schema, authorization context, idempotency/expiry rules | Architecture + security |
| CR-CAND-03 | State Transition Matrices | Named states lack exhaustive transition contracts | transition tables, event mapping, invariant tests | Domain owners + risk |
| CR-CAND-04 | Risk Parameterization | Limits and activation semantics remain owner decisions | typed parameter schema, governance lifecycle, no invented values | Human owner + risk governance |
| CR-CAND-05 | Privileged Authority Lifecycle | Approval expiry/revocation/emergency paths incomplete | action-level matrix, approval state machine, audit evidence | Human owner + security |
| CR-CAND-06 | Persistence Transaction Map | Critical transaction/consistency behavior underspecified | aggregate ownership, transaction map, outbox/inbox, recovery | Architecture + data owner |
| CR-CAND-07 | Isolation Boundary Matrix | Isolation principles need executable negative tests | environment/market flow matrix, test cases | Security + platform + risk |
| CR-CAND-08 | Error Registry | Categories lack stable canonical codes and retry matrix | error registry, operation policy, ambiguity handling | Architecture + service owners |
| CR-CAND-09 | G1 Evidence Matrix | Invariants not all mapped to acceptance evidence | requirement/test/evidence/reviewer matrix | G1 gate authority |
| CR-CAND-10 | Document Metadata Normalization | Status/authority labels not uniformly machine-auditable | metadata schema, baseline manifest, supersession map | Document control authority |

## Required CR record fields
Each formal CR must include: unique ID; originating requirement; rationale; exact affected documents/sections; proposed change; alternatives; safety/security/risk impact; compatibility/migration impact; tests/evidence; rollback/forward recovery; approvers; effective baseline; status; traceability updates.

## Decision rule
These candidates do not supersede the source documents. Do not implement their proposals until approved under the project’s canonical Change Request Protocol. If a proposal conflicts with a higher-authority requirement, stop and escalate.
