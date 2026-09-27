# RECONCILIATION AND ACCOUNTING ASSURANCE
## Financial-State Integrity

Status: NORMATIVE IMPLEMENTATION CONTROL

## Principle

The system must distinguish:
- intended trades;
- accepted instructions;
- broker/external execution;
- fills;
- fees/costs;
- positions;
- cash/balances;
- valuations;
- realized/unrealized performance.

## Assurance requirements

Test:
- duplicate fills;
- missing fills;
- partial fills;
- fees;
- funding/financing where applicable;
- corporate actions where applicable;
- balance changes;
- position drift;
- restart/recovery;
- stale broker state.

## Authority

Portfolio/accounting truth must not be inferred from AI output.

Reconciliation is an authoritative control boundary as defined by FINAL_SPECIFICATION.
