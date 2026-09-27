# G1 IMPLEMENTATION CONTRACT
## Domain Foundation / Core Runtime

Status: NORMATIVE FOR G1
Current implementation gate: G1
Prerequisite: G0 PASS

## 1. G1 Objective

Build the minimum authoritative domain/runtime foundation required for all later gates.

G1 is not a trading-strategy gate and not a broker-connectivity gate.

## 2. G1 Scope

Implement only the foundational contracts required by the frozen specification, including as applicable:

- canonical identifiers and identity rules;
- timestamps and temporal semantics;
- correlation/causation identifiers;
- command/event envelope primitives;
- domain error/exception taxonomy;
- immutable/value-object behavior where specified;
- canonical domain primitives required by later Trading Core;
- append-only/audit foundations required by later gates;
- deterministic serialization/validation foundations;
- configuration boundary primitives;
- test infrastructure needed to prove G1 invariants.

The exact package/module placement is an implementation decision unless frozen elsewhere.

## 3. G1 Must Not Implement

Do not use G1 as an excuse to implement:
- live broker connectivity;
- live credentials;
- autonomous live execution;
- strategy self-promotion;
- unrestricted AI agents;
- production deployment;
- market-specific trading logic that belongs to later gates;
- undocumented architecture.

## 4. Required Invariants

At minimum, tests must establish:

1. identity values are stable and unambiguous;
2. required envelope fields cannot be omitted silently;
3. event/command identity semantics are preserved;
4. temporal fields follow one canonical representation;
5. invalid domain states are rejected;
6. append-only records cannot be casually mutated through the domain API;
7. serialization is deterministic where required;
8. correlation/causation relationships are preserved;
9. errors are classifiable and machine-testable;
10. the implementation does not introduce a second source of truth.

## 5. G1 Acceptance Evidence

Kilo Code MUST provide:
- changed-file inventory;
- tests created/updated;
- full relevant test result;
- static/type/lint result where configured;
- contract-to-code mapping;
- known limitations;
- explicit confirmation that no live broker/credential path was introduced.

## 6. G1 Exit

G1 PASS means foundation is implemented and evidenced.

G1 PASS does not authorize G2 implementation automatically without the normal gate transition protocol.

## 7. Stop Conditions

Stop if implementation requires:
- changing a canonical event;
- changing a state machine;
- changing a database authority rule;
- changing risk/live authority;
- changing market/environment isolation.

Those are architecture changes, not G1 coding choices.
