# Performance, Capacity, and Scaling Contract

Status: FINAL TRUE-PRODUCTION BASELINE v1.0
Authority: FINAL_SPECIFICATION
Target: Kilo Code
Scope: Long-lived, production-capable AI-native proprietary trading system

## 1. Capacity is a design concern

Performance SHALL be measured against expected workloads rather than assumed.

Measure at minimum:
- API latency;
- event processing latency;
- market-data throughput;
- order workflow latency;
- reconciliation latency;
- database throughput;
- queue depth;
- resource utilization;
- frontend load time where relevant.

## 2. Headroom

Production deployments require documented capacity headroom and scaling behavior.

## 3. No unsafe optimization

Performance optimization must not weaken risk controls, reconciliation, auditability, or determinism.

## 4. Load testing

Load tests must include normal, peak, burst, degraded-provider, and recovery scenarios.

## 5. Bottleneck ownership

Known bottlenecks must have owners and remediation plans.

## Change control

This contract is frozen. Implementation-specific discoveries must use the project's Change Request process with impact analysis, review, tests, evidence, and traceability updates.
