# PRODUCTION FAILURE GAME DAY PROTOCOL
## Controlled Resilience Validation

Status: NORMATIVE IMPLEMENTATION CONTROL

Production readiness must be validated against controlled failure scenarios where safe.

## Scenario families

Examples:
- market data outage;
- provider latency;
- provider malformed response;
- broker disconnect;
- duplicate execution message;
- delayed fill;
- reconciliation mismatch;
- database failure;
- service restart;
- clock drift;
- secret access failure;
- model/provider outage;
- agent runaway/failure;
- queue backlog;
- notification outage;
- partial infrastructure failure.

## Rules

Exercises must:
- have defined scope;
- avoid uncontrolled financial exposure;
- record expected behavior;
- record observed behavior;
- verify kill/fail-closed behavior;
- produce remediation items.

A system is not considered resilient merely because the failure path exists in code.
