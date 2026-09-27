# Polyglot Engineering Quality and Anti-AI-Slop Contract

Status: FINAL TRUE-PRODUCTION BASELINE v1.0
Authority: FINAL_SPECIFICATION
Target: Kilo Code
Scope: Long-lived, production-capable AI-native proprietary trading system

## 1. Objective

Polyglot architecture SHALL be used to create explicit engineering boundaries and use the strengths of each language, not merely to increase the number of languages.

The system is a long-lived product/system, not an MVP disposable prototype.

## 2. Final language allocation

### Frontend
- TypeScript: application logic, API clients, state, operator workflows.
- HTML: semantic document structure.
- CSS: presentation/layout.
- Rust/WASM: only for browser-side modules where deterministic computation, performance, or reuse of validated Rust domain logic provides a material benefit. It is optional and must not become complexity without measurable value.

### Backend
- Go: primary service/backend language for API, orchestration, OMS workflows, provider integration, event services, operational services.
- Rust: safety-sensitive, deterministic, performance-critical core modules where memory safety or strict invariants materially justify a separate boundary.
- SQL: authoritative persistence logic, constraints, migrations, and queries.

### Intelligence
- Python: research, data science, model evaluation, experimentation, backtesting, offline self-improvement.
- Python is not the default language for live execution services.

### Infrastructure
- IaC: reproducible environment and deployment definitions.
- Shell/configuration languages may be used only within controlled operational boundaries.

## 3. Anti-AI-slop rules

Code SHALL NOT be accepted merely because it compiles or passes superficial tests.

Every non-trivial component must have:
- clear ownership;
- explicit domain responsibility;
- failure semantics;
- security boundary;
- observability;
- tests appropriate to risk;
- documentation of non-obvious decisions;
- deterministic behavior where required;
- maintainable interfaces;
- dependency justification.

Avoid:
- giant generic service classes;
- duplicated business logic;
- arbitrary abstractions;
- unnecessary wrappers;
- fake repositories/services created only for test appearance;
- generated boilerplate without review;
- TODO-driven architecture;
- hard-coded provider-specific assumptions in domain code;
- hidden global state;
- catch-all error handling;
- silent fallbacks;
- unnecessary microservices.

## 4. Human engineering review

Kilo Code SHALL act as an implementation assistant, not as the authority that decides architecture. Each gate requires review against the frozen contracts and evidence standard.

## Change control

This contract is frozen. Implementation-specific discoveries must use the project's Change Request process with impact analysis, review, tests, evidence, and traceability updates.
