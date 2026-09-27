# Canonical Vocabulary — Final / Frozen

| Term | Canonical meaning |
|---|---|
| Signal | Strategy-produced market/trading proposition; never an executable order |
| Order Intent | Normalized desired trading action submitted to Risk |
| Risk Approval | Time-bounded authorization bound to the exact intent hash |
| OMS Instruction | Execution instruction created only from a valid Risk Approval |
| Execution Adapter | Boundary that submits/cancels/queries provider state from OMS instructions |
| Reconciliation | Comparison of expected canonical state with provider state |
| Portfolio | State derived from verified/reconciled trading facts, not arbitrary writes |
| Strategy Version | Immutable versioned strategy artifact with evidence references |
| Candidate | Strategy artifact progressing through governed validation |
| Live Candidate | Approved immutable candidate eligible for live deployment, not itself a bypass |
| Environment | Isolated runtime boundary with explicit credentials/data/policies |
| Market Module | Independently enabled/disabled market-specific trading/data boundary |
| Runtime AI Employee | Product agent operating under explicit runtime permissions |
| Kilo Code Agent | Development-time implementation/review agent; never a runtime employee |
| Decision Ledger | Append-only tamper-evident record of governed decisions |
| OOS | Frozen out-of-sample evaluation data unavailable for candidate tuning |
