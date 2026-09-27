# Architecture Decisions — Final

| ID | Decision | Normative rule |
|---|---|---|
| AD-001 | Single risk authority | One authoritative Risk Engine per deployment; no duplicate risk decision authority. |
| AD-002 | Exact intent binding | Risk approval hashes the complete normalized order intent, policy version, account/environment and expiry. Any material change invalidates approval. |
| AD-003 | Event-driven core | Domain state changes are represented by immutable events; commands request changes and events record accepted changes. |
| AD-004 | Reconciliation gate | Live trading is blocked when account/order/position reconciliation is stale, failed or unknown. |
| AD-005 | Promotion authority | Strategy promotion is a governed workflow; research agents cannot self-promote to live. |
| AD-006 | Environment isolation | Research/Test/Staging/Shadow/Demo/Live are first-class environments with explicit credential and data boundaries. |
| AD-007 | Append-only ledger | Decision/audit ledger is append-only with hash chaining and periodic signed checkpoints. |
| AD-008 | Telegram parity | Telegram and Web invoke the same command service and authorization policy. |
| AD-009 | External input untrusted | News, APIs, documents and model outputs are untrusted input until validated/normalized. |
| AD-010 | Live artifact immutability | Live strategy/model/prompt/config references are content-addressed and immutable during deployment. |
| AD-011 | Fail closed | Unknown risk, stale data, uncertain broker state or missing authorization blocks live mutation. |
| AD-012 | Human emergency authority | Owner can invoke emergency controls subject to the same auditable command path; emergency actions never grant agents extra authority. |
| AD-013 | Least privilege | Agent permissions are explicit by role, tool, environment, action and resource. |
| AD-014 | No look-ahead | Research datasets preserve event/publication/ingestion timestamps and prevent future information from entering historical decisions. |
| AD-015 | Independent failure domains | Market modules can be disabled without corrupting unrelated markets. |
