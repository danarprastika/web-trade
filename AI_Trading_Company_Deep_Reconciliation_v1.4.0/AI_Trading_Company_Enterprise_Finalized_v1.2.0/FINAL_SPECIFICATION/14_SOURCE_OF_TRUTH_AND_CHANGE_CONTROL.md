# Source of Truth and Change Control — Controlled Baseline v1.1.0

**Class:** Governance / Implementation-Control  
**Status:** Effective within finalized v1.1.0 documentation baseline  
**Scope:** Document authority, conflict handling, and change governance

## 1. Purpose

This document establishes how controlled project documents are classified, how conflicts are handled, and how changes are proposed, reviewed, approved, implemented, and verified. It does not grant implementation or live-trading authorization.

## 2. Document authority classes

### 2.1 Normative Core

Normative Core documents define binding requirements and invariants for domain behavior, trading authority, risk, security, isolation, data integrity, runtime contracts, and system behavior. They include the canonical architecture and domain contracts in `FINAL_SPECIFICATION/`.

Normative Core requirements cannot be weakened by Implementation-Control documents, supporting material, code, tests, agent instructions, or general engineering convention.

### 2.2 Implementation-Control

Implementation-Control documents define the process for implementing and verifying Normative Core requirements. They include gate execution, G1 implementation planning, implementation mapping, evidence standards, repository guidance, security checklists, test strategy, and Definition of Done.

Implementation-Control documents are binding for workflow and acceptance, but cannot redefine domain semantics, authority, risk, security, or live-operation constraints.

### 2.3 Governance Records

Approved decisions, Change Requests, exceptions, and baseline records document authorized resolutions. They apply only to their stated scope and effective version. A draft or proposed record has no approval authority.

### 2.4 Supporting and Agent-Specific Material

Supporting documents explain or summarize controlled requirements. Agent-specific instructions configure a development tool. Neither may override Normative Core or approved governance records.

### 2.5 Evidence and Historical Material

Evidence proves only the specific claim, scope, version, and test conditions recorded. Historical or superseded material has no current authority unless explicitly adopted.

## 3. Precedence and conflict resolution

1. An applicable approved Governance Record may resolve an explicitly delegated decision within its scope, but may not weaken Normative Core safety constraints.
2. Normative Core controls over Implementation-Control, Supporting, Agent-Specific, code, and tests when requirements conflict.
3. Implementation-Control controls workflow and evidence requirements where it does not conflict with Normative Core.
4. Supporting material must be corrected when it conflicts with a higher-authority document.
5. Same-class or same-level conflicts without an explicit approved precedence rule are unresolved. Stop the affected work and raise a Change Request.
6. Never resolve conflicts by filename, numeric prefix, document date, folder position, majority of documents, or agent preference.
7. If a safety, risk, security, isolation, authority, or live-operation boundary is unclear, fail closed and block the affected action.

## 4. Change classes

- **C0 — Editorial:** spelling, formatting, or reference repair with no semantic effect.
- **C1 — Non-critical clarification:** clarifies implementation without changing authority, security, state, event, or trading semantics.
- **C2 — Contract change:** changes API, domain, event, state, persistence, or externally observable behavior.
- **C3 — Safety-critical change:** affects risk, execution, credentials, live gates, promotion, security, isolation, or human authority.

Classification must be based on actual impact, not the size of the textual edit. A reference correction that changes which requirement governs is not merely editorial.

## 5. Minimum Change Request record

Every Change Request must include:
- unique ID and title;
- status and requested effective version;
- problem statement and evidence;
- reason and proposed change;
- exact affected documents, sections, requirements, contracts, entities, states, and events;
- authority and safety classification;
- security, privacy, trading, data, operational, and compatibility impact;
- alternatives considered and rationale;
- migration and rollback plan where applicable;
- test and verification plan;
- required reviewers and approvers;
- approval record, implementation reference, evidence, and closure decision.

The canonical template and lifecycle must preserve all required fields across source documents. If source templates conflict, do not silently merge or discard fields; block new CR processing until the governing schema is approved.

## 6. Approval and implementation

- A proposal is not approved until the required authority records explicit approval.
- The author or implementation agent cannot approve its own change.
- C2 changes require domain/architecture review and affected-gate impact analysis.
- C3 changes require explicit owner approval and appropriate independent risk/security review.
- Implementation must not begin before required approvals and prerequisites are recorded.
- A Change Request is closed only after implementation, verification, evidence, documentation synchronization, and release traceability are complete.

## 7. Stop conditions

Stop the affected work and escalate when:
- normative requirements conflict or are ambiguous;
- a canonical identifier, event, state transition, or authority is missing;
- a safety or isolation invariant cannot be enforced;
- the implementation would weaken risk, security, or live controls;
- a required approval or evidence artifact is absent;
- a test cannot demonstrate a mandatory invariant.

The escalation record must cite exact source locations and describe the affected scope. Do not invent a resolution.

## 8. Versioning and baseline

Controlled documents use stable IDs and explicit versions. Numeric prefixes are not authority. A baseline manifest must identify the exact file set, versions, status, and integrity hashes. Superseded documents remain retained as historical evidence and must not be mistaken for current requirements.

## 9. Effective boundary

This v1.1.0 update resolves document authority classification and conflict handling. It does not close the individual G1 contract blockers listed in `G1_READINESS_AND_BLOCKERS.md`, and it does not authorize implementation or live trading.
