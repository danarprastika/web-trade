# Enterprise Operating Model

> Status: ENTERPRISE DOCUMENTATION BASELINE v1.2.0 — controlled planning baseline; subordinate to the applicable Normative Core and approved contracts.

## Purpose
Define how the trading organization is governed as a durable engineering and operating system.

## Authority and interpretation
- This document defines control intent and operating expectations; it does not silently approve unresolved values, credentials, legal positions, capital limits, or live activation.
- Where a value is marked TBD, it requires explicit owner-approved decision evidence before implementation may depend on it.
- Same-tier conflicts are fail-closed and require a recorded change request or decision.

## Operating principles
Capital safety, deterministic controls, least privilege, evidence-first delivery, separation of duties, reproducibility, explicit ownership, and controlled change.

## Functional capabilities
Research; market/data operations; strategy engineering; risk; portfolio; execution; platform engineering; AI operations; security; SRE/operations; governance and assurance.

## Three lines of control
First line: engineering and trading operations execute within controls. Second line: risk/security/governance challenge and gate. Third line: independent assurance audits evidence and control effectiveness.

## Decision rights
Architecture changes require architecture governance; risk semantics require risk ownership; production/live activation requires designated owner approval and readiness evidence. AI agents may recommend and execute bounded tasks but cannot self-grant authority.

## Evidence obligations
Every production-impacting decision has an identifier, owner, timestamp, rationale, affected artifacts, approvals, validation evidence and rollback/containment plan where applicable.

## Open items
Organization-specific staffing, legal entity structure, jurisdictions, external assurance scope and financial/accounting ownership remain TBD until explicitly approved.
