# Canonical Data Model — Final

Authoritative entity groups:

**Identity/governance:** User/Owner, Agent, AgentRole, Permission, Tool, Approval, ChangeRequest, Deployment, Environment.

**Market/data:** Market, Venue, Instrument, InstrumentVersion, MarketSession, Provider, ProviderCertification, DataFeed, DataPoint, DataQualitySnapshot, NewsEvent, EconomicEvent, CorporateAction, FeatureSet.

**Trading:** Account, Portfolio, Strategy, StrategyVersion, Signal, OrderIntent, RiskEvaluation, OMSInstruction, Order, Fill, Position, BalanceSnapshot, ExposureSnapshot, ReconciliationRun, ReconciliationDifference.

**Research:** Dataset, DatasetVersion, Experiment, ExperimentRun, BacktestRun, WalkForwardRun, OOSRun, StressRun, ShadowRun, PromotionCandidate, EvidenceArtifact.

**Operations:** AgentTask, AgentMemory, DecisionLedgerEntry, Incident, Alert, KillSwitch, ServiceHealth, MetricSnapshot, BackupRun, RestoreDrill.

Every mutable entity has version/timestamps where needed; externally sourced objects retain provider identity and provenance. Money/quantity calculations use fixed-precision decimal semantics, never binary floating point for authoritative accounting.
