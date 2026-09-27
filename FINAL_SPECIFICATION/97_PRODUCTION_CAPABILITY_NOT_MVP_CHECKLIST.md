# Production Capability Checklist — Not MVP

Status: FINAL TRUE-PRODUCTION BASELINE v1.0
Authority: FINAL_SPECIFICATION
Target: Kilo Code
Scope: Long-lived, production-capable AI-native proprietary trading system

The following capabilities are required for production maturity rather than optional MVP polish.

### Core
- canonical domain model;
- explicit state machines;
- transactional integrity;
- idempotency;
- deterministic replay;
- versioned events;
- schema migrations;
- audit trail.

### Trading
- market-data validation;
- risk gate;
- OMS;
- execution adapters;
- reconciliation;
- portfolio accounting;
- performance calculation;
- kill switches;
- market isolation.

### Intelligence
- experiment registry;
- dataset/version lineage;
- model/prompt versioning;
- evaluation;
- OOS locking;
- promotion governance;
- rollback;
- research/live credential separation.

### Platform
- authentication;
- authorization;
- API versioning;
- frontend/backend contracts;
- observability;
- alerts;
- backups;
- disaster recovery;
- CI/CD;
- artifact provenance;
- dependency management.

### Security
- threat modeling;
- secret management;
- network segmentation;
- sandboxing;
- supply-chain controls;
- security testing;
- red-team assessment;
- incident response.

### Operations
- runbooks;
- game days;
- capacity testing;
- provider certification;
- operational readiness;
- release governance;
- decommissioning.

A component is not production-ready because only the happy path works.

## Change control

This contract is frozen. Implementation-specific discoveries must use the project's Change Request process with impact analysis, review, tests, evidence, and traceability updates.
