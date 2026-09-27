# IMPLEMENTATION COMPLETENESS AUDIT
## Anti-MVP Audit

Status: NORMATIVE AUDIT CONTROL

Before declaring the system complete, audit every required domain for four states:

1. specified;
2. implemented;
3. tested;
4. operationally evidenced.

## Mandatory audit questions

- Is the behavior specified?
- Is there one authoritative implementation?
- Is the happy path tested?
- Is the failure path tested?
- Is the security boundary tested?
- Is recovery tested?
- Is observability present?
- Is the behavior reproducible?
- Is the implementation production-safe?
- Is the behavior covered by a gate/evidence report?

## Anti-MVP rule

A feature marked "implemented" but lacking required verification or operational evidence is incomplete.

A feature implemented only as a mock/stub must be explicitly labeled and must not be presented as production capability.

## Final audit outcome

The audit must distinguish:
- implemented and verified;
- implemented but not production-ready;
- stubbed/deferred;
- blocked;
- intentionally out of scope.

No ambiguous "done" category is allowed.
