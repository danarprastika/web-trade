# CHANGE REQUEST PROTOCOL
## Frozen Architecture Change Control

Status: NORMATIVE

## 1. Purpose

Prevent implementation work from becoming an undocumented architecture rewrite.

## 2. Change Request Required When

A Change Request is mandatory for any proposed modification to:
- FINAL_SPECIFICATION normative behavior;
- authority chain;
- Risk ownership;
- live gate prerequisites;
- canonical event names/semantics;
- canonical state machines;
- canonical database model;
- environment isolation;
- market isolation;
- security trust boundaries;
- agent permission boundaries;
- append-only/audit guarantees;
- self-improvement governance.

## 3. Change Request Does Not Mean Automatic Approval

Creating a Change Request only records the proposal.

Implementation MUST pause where the requested change affects a frozen contract.

## 4. Required CR Fields

Each CR must contain:

- CR ID;
- date;
- requester;
- affected specification;
- exact section;
- current behavior;
- proposed behavior;
- reason;
- affected components;
- security impact;
- data impact;
- migration impact;
- backward-compatibility impact;
- test impact;
- gate impact;
- live-trading impact;
- rollback plan;
- approval;
- final decision.

## 5. Emergency Rule

Security or safety defects may require immediate containment. Containment may be implemented without waiting for a full architectural redesign, but the change must be documented retrospectively and must not be used to introduce unrelated design changes.

## 6. No Silent Reconciliation

If Kilo Code discovers two conflicting documents, it MUST:
1. identify the conflict;
2. apply source-of-truth hierarchy;
3. if unresolved at the normative level, stop;
4. create a Change Request.

It must never silently choose a preferred architecture.
