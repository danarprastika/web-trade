# DEPLOYMENT AND RELEASE GOVERNANCE
## Production-Safe Software Delivery

Status: NORMATIVE IMPLEMENTATION CONTROL

## Release principles

- reproducible builds;
- versioned artifacts;
- immutable release identity;
- migration safety;
- configuration separation;
- secret separation;
- rollback capability;
- staged rollout where applicable;
- health verification;
- post-deployment observation.

## Required controls

Every production-bound release must identify:
- source revision;
- build artifact;
- dependency set;
- configuration version;
- database migration version;
- test evidence;
- security evidence;
- approval;
- rollback procedure.

## Prohibited

Do not deploy an untraceable artifact.
Do not alter production behavior manually without an auditable mechanism.
Do not combine unrelated architecture changes with a release merely for convenience.
