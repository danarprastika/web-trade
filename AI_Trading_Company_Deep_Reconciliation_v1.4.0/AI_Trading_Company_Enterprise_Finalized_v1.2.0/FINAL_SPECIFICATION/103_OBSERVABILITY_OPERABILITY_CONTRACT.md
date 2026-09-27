# Observability and Operability Contract

Status: FINAL TRUE-PRODUCTION BASELINE v1.0
Authority: FINAL_SPECIFICATION
Target: Kilo Code
Scope: Long-lived, production-capable AI-native proprietary trading system

## 1. Three pillars

Production services SHALL provide appropriate:
- logs;
- metrics;
- traces.

## 2. Business telemetry

Technical telemetry is insufficient. The system must expose trading-domain health such as:
- risk rejection rate;
- stale market-data rate;
- order lifecycle anomalies;
- reconciliation mismatches;
- provider degradation;
- strategy health;
- portfolio state freshness.

## 3. Alerts

Alerts must be actionable and mapped to runbooks. Alert fatigue is a production defect.

## 4. Operator readiness

A service is not production-ready if operators cannot determine what failed, whether trading is safe, and what recovery action is authorized.

## Change control

This contract is frozen. Implementation-specific discoveries must use the project's Change Request process with impact analysis, review, tests, evidence, and traceability updates.
