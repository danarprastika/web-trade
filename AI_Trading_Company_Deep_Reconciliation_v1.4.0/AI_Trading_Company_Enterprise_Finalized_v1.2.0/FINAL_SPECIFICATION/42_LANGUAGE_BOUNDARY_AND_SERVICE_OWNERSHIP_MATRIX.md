# Language Boundary and Service Ownership Matrix

Status: FINAL TRUE-PRODUCTION BASELINE v1.0

| Layer / Component | Language(s) | Primary responsibility |
|---|---|---|
| Web application | TypeScript + HTML + CSS | Control center UI |
| Browser computational modules (optional) | Rust/WASM | Only justified deterministic/performance-sensitive client computation |
| API Gateway | Go | Authenticated API boundary |
| OMS | Go | Approved order lifecycle |
| Execution Gateway | Go + Rust where justified | External execution boundary + safety-sensitive validation |
| Market Data | Go + Rust where justified | Provider ingestion, validation, normalization |
| Reconciliation | Go + Rust where justified | External/internal state reconciliation |
| Risk/Safety Kernel | Rust where justified | Deterministic safety-critical computation |
| Event/Workflow Services | Go | Orchestration and event processing |
| Research | Python | Research and experimentation |
| Backtesting | Python | Offline deterministic research |
| Model Evaluation | Python | AI/model evaluation |
| Persistence | SQL | Canonical data model |
| Infrastructure | IaC | Deployment/environment |

The language is not the authority. The frozen domain contracts define authority.
