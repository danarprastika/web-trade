# PROVIDER AND BROKER CERTIFICATION
## External Integration Certification Contract

Status: NORMATIVE IMPLEMENTATION CONTROL

Provider-specific behavior must be isolated behind approved adapters/contracts.

## Certification areas

For each provider/broker, test as applicable:
- authentication;
- permissions;
- market/instrument mapping;
- timestamps;
- rate limits;
- pagination;
- retries;
- duplicate delivery;
- out-of-order delivery;
- partial fills;
- rejects;
- cancellations;
- reconnect behavior;
- stale data;
- malformed responses;
- reconciliation;
- maintenance/outage behavior.

## Certification rule

A provider integration is not production-ready because a happy-path request succeeded.

The integration must pass its applicable failure, security, reconciliation and recovery tests.

Provider-specific credentials and production endpoints remain prohibited until the applicable gate authorizes them.
