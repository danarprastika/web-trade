# Long-Term Backward Compatibility and Evolution Contract

Status: FINAL TRUE-PRODUCTION BASELINE v1.0
Authority: FINAL_SPECIFICATION
Target: Kilo Code
Scope: Long-lived, production-capable AI-native proprietary trading system

## 1. Compatibility

Public APIs, events, database schemas, artifacts, and operator workflows require an explicit compatibility strategy.

## 2. Versioning

Breaking changes require a new version or controlled migration. Silent breaking changes are prohibited.

## 3. Rolling upgrades

Services SHALL be capable of safe rolling upgrades where the deployment model requires it. During transition, old and new versions must coexist according to documented compatibility rules.

## 4. Data evolution

Database migrations SHALL consider:
- forward compatibility;
- rollback/forward recovery;
- backfill;
- large-table performance;
- partial deployment;
- audit impact.

## 5. Artifact evolution

A live strategy/model artifact remains immutable. A new version is a new artifact and follows promotion governance.

## Change control

This contract is frozen. Implementation-specific discoveries must use the project's Change Request process with impact analysis, review, tests, evidence, and traceability updates.
