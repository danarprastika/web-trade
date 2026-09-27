# SECURITY IMPLEMENTATION CHECKLIST
## Security Requirements Across Implementation Gates

Status: NORMATIVE CHECKLIST

## Identity & Access
- [ ] least privilege;
- [ ] deny by default;
- [ ] role/agent permissions explicit;
- [ ] authorization checked server-side;
- [ ] no trust in client/UI claims.

## Credentials
- [ ] research has no live credentials;
- [ ] demo/paper credentials cannot access live;
- [ ] live credentials isolated;
- [ ] credentials never logged;
- [ ] credential access audited.

## External Input
- [ ] market/news/provider payloads treated as untrusted;
- [ ] external text cannot directly become commands;
- [ ] prompt-injection defenses tested where AI consumes external text;
- [ ] schemas validated before authority decisions.

## Trading Safety
- [ ] Risk is authoritative;
- [ ] fail-closed behavior;
- [ ] kill switches enforced;
- [ ] exact intent binding;
- [ ] no execution without valid approval;
- [ ] reconciliation mismatch blocks unsafe progression.

## Audit
- [ ] decision records append-only where required;
- [ ] correlation/causation preserved;
- [ ] actor/agent identity recorded;
- [ ] timestamps canonical;
- [ ] privileged actions traceable.

## Isolation
- [ ] market scope explicit;
- [ ] environment scope explicit;
- [ ] failure domains explicit;
- [ ] no credential/state leakage across boundaries.

## Implementation Rule

Unchecked items are not automatically failures during every gate; mark them:
- not applicable;
- future gate;
- verified;
- failed;
with evidence.
