# Event ↔ State Traceability — Final / Frozen

## Order
DRAFT → RISK_PENDING (`OrderIntentCreated` / `RiskEvaluated`) → RISK_APPROVED (`RiskApproved`) → OMS_ACCEPTED (`OMSInstructionCreated`) → SUBMITTING (`OrderSubmitted`) → ACKNOWLEDGED (`OrderAcknowledged`) → PARTIALLY_FILLED (`OrderPartiallyFilled`) → FILLED (`OrderFilled`). Cancellation/rejection/expiry/failure/unknown transitions must emit their corresponding canonical facts.

## Reconciliation
CHECKING (`ReconciliationStarted`) → MATCHED (`ReconciliationMatched`) / MISMATCHED (`ReconciliationMismatch`) / UNKNOWN (`ReconciliationUnknown`). Unknown or mismatched state blocks live mutation.

## Strategy
Progression follows the canonical strategy lifecycle in `03_STATE_MACHINES.md`; promotion-related events and immutable evidence are mandatory at approval boundaries.

## Rule
No state transition is valid unless its precondition, authority, persistence effect, and canonical event are defined and testable.
