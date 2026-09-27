# Canonical Event Catalog — Final / Frozen

The following event names are canonical identifiers. Supporting documentation must reference these exact names; older simplified names are descriptive aliases only and are not valid implementation identifiers.

## Canonical events

### Market/Data
MarketDataReceived, MarketDataValidated, MarketDataRejected, NewsReceived, NewsNormalized, MarketRegimeChanged

### Trading
SignalProduced, OrderIntentCreated, RiskEvaluated, RiskApproved, RiskRejected, OMSInstructionCreated, OrderSubmitted, OrderAcknowledged, OrderPartiallyFilled, OrderFilled, OrderCancelled, OrderRejected, BrokerStateChanged

### Reconciliation/Portfolio
ReconciliationStarted, ReconciliationMatched, ReconciliationMismatch, ReconciliationUnknown, PositionChanged, PortfolioValuationChanged

### Research/Strategy
StrategyPromoted, StrategySuspended, StrategyRetired, ExperimentCreated, ExperimentCompleted, DatasetFrozen, OOSLocked

### AI/Governance
ApprovalGranted, ApprovalRejected, AgentTaskCreated, AgentTaskCompleted, AgentQuarantined

### Infrastructure/Security
ProviderDegraded, CredentialAccessDenied, IncidentOpened, IncidentResolved, DeploymentStarted, DeploymentCompleted, DeploymentRolledBack, KillSwitchActivated, KillSwitchReleased

## Event invariants
- Events are immutable facts, never commands.
- Every event uses the canonical Event Envelope.
- Event type, schema version and payload schema are versioned.
- Consumers must tolerate unknown future fields.
- Event names are not reused for materially different semantics.
- State transitions must reference the event(s) that justify them.
- Provider-specific event names never become canonical domain events.
