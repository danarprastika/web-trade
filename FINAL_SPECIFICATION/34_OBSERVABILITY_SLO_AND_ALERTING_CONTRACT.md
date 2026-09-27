# OBSERVABILITY, SLO AND ALERTING CONTRACT
## Operational Visibility

Status: NORMATIVE IMPLEMENTATION CONTROL

## Observability

Production-bound services must expose sufficient:
- logs;
- metrics;
- traces;
- health signals;
- audit records;
- correlation identifiers.

## Critical monitoring domains

Monitor as applicable:
- market data freshness;
- provider health;
- event processing;
- queue/backlog;
- risk decisions;
- OMS state;
- execution state;
- reconciliation;
- portfolio state;
- kill switches;
- agent failures;
- model failures;
- security events;
- infrastructure health.

## Alert quality

Alerts must identify:
- what failed;
- scope;
- severity;
- correlation;
- affected market/environment;
- operator action/runbook.

Avoid alerting that cannot lead to a meaningful operational action.
