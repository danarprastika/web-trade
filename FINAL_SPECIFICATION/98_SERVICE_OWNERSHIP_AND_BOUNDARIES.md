# Service Ownership, Boundaries, and Repository Structure Contract

Status: FINAL TRUE-PRODUCTION BASELINE v1.0
Authority: FINAL_SPECIFICATION
Target: Kilo Code
Scope: Long-lived, production-capable AI-native proprietary trading system

## 1. Ownership

Each service/module SHALL have a documented owner, responsibility, public interfaces, dependencies, data ownership, and failure domain.

## 2. Suggested repository organization

```text
/apps/
  web/                    # TypeScript frontend
/services/
  api/                    # Go
  oms/                    # Go
  execution/              # Go
  market-data/            # Go
  reconciliation/         # Go
  orchestration/          # Go
/crates/
  risk-core/              # Rust where justified
  domain-kernel/          # Rust where justified
/research/
  experiments/             # Python
  backtesting/             # Python
  evaluation/              # Python
/contracts/
  api/
  events/
  schemas/
/db/
  migrations/
  queries/
/infra/
  environments/
  modules/
/tests/
  contract/
  integration/
  security/
  performance/
  resilience/
```

The exact repository layout may be adapted to the actual repository, but ownership boundaries SHALL remain explicit.

## 3. Dependency direction

Domain/core contracts SHALL not depend on frontend code. Research code SHALL not become a dependency of live execution merely because it contains useful logic.

## 4. Shared code

Shared libraries are permitted only when they represent a stable, genuinely shared contract. Copy-paste duplication and "shared utility" dumping grounds are prohibited.

## Change control

This contract is frozen. Implementation-specific discoveries must use the project's Change Request process with impact analysis, review, tests, evidence, and traceability updates.
