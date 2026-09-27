# TEST STRATEGY AND CONTRACT TESTS
## Frozen Architecture Verification Strategy

Status: NORMATIVE TESTING GUIDE

## 1. Test Pyramid

Use:
- domain/unit tests for invariants;
- contract tests for interfaces;
- integration tests for authority boundaries;
- end-to-end tests only where they add meaningful evidence;
- negative/security tests for forbidden behavior.

## 2. Contract Tests

Every authoritative boundary should have tests proving both:
1. accepted valid behavior;
2. rejected invalid/unauthorized behavior.

## 3. Critical Contract Families

### Risk
- valid order intent can be evaluated;
- rejected risk decision cannot become executable instruction;
- approval is bound to the exact intent;
- stale/invalid approval cannot authorize a changed intent.

### OMS
- instruction requires valid approval;
- duplicate/invalid instructions are rejected;
- OMS cannot invent authorization.

### Execution
- only valid OMS instructions reach execution;
- execution result is represented by canonical events/state.

### Reconciliation
- broker/external state mismatch is visible;
- mismatch cannot silently become portfolio truth;
- reconciliation outcome controls downstream progression as specified.

### Strategy Promotion
- evidence prerequisites enforced;
- OOS lock semantics preserved;
- no self-promotion;
- rollback/suspension paths tested.

### Agents
- unauthorized agent action is rejected;
- research agents cannot access live credentials;
- Master/Orchestrator cannot bypass Risk.

## 4. Determinism

Where required:
- freeze dataset/version;
- stable ordering;
- stable seeds/configuration;
- reproducible result identity;
- no future-data leakage.

## 5. Regression

Every gate must preserve prior gate tests.

## 6. Test Naming

Names should state the invariant, e.g.:
`test_oms_rejects_instruction_without_valid_risk_approval`

## 7. Coverage

Coverage percentage alone is not acceptance. Critical invariants must be directly tested even when aggregate coverage is high.
