# OPERATIONAL READINESS REVIEW
## Production Candidate Gate

Status: NORMATIVE IMPLEMENTATION CONTROL

Before production/live consideration, verify:

### People
- ownership defined;
- emergency authority defined;
- escalation path defined;
- operational responsibilities understood.

### System
- health checks;
- startup/shutdown;
- failure handling;
- backups;
- restore;
- deployment/rollback;
- observability.

### Trading
- Risk gate;
- kill hierarchy;
- reconciliation;
- duplicate prevention;
- stale-data handling;
- provider failure handling.

### AI
- agent permissions;
- model versions;
- prompt versions;
- tool boundaries;
- quarantine;
- failure containment.

### Security
- credential isolation;
- least privilege;
- audit integrity;
- supply-chain controls;
- incident response.

### Evidence
Every checked item must point to implementation/test/evidence.

A checklist with no evidence is not a readiness PASS.
