# Polyglot Language Architecture

Status: FINAL TRUE-PRODUCTION BASELINE v1.0

## Principle

Frontend and backend are distinct architectural layers and may each use more than one language where there is a concrete engineering reason.

The project SHALL NOT use language diversity merely for appearance or "security through obscurity". Each language must have a clear responsibility, ownership boundary, build/test path, and operational justification.

## Frontend

Primary:
- TypeScript — application logic, API clients, state, operator workflows.
- HTML — semantic structure.
- CSS — presentation.

Optional:
- Rust compiled to WebAssembly — only for deterministic/high-performance browser modules or reuse of validated computational logic where the measured benefit justifies complexity.

The frontend is never authoritative for risk, permissions, accounting, or live authorization.

## Backend

Primary:
- Go — API services, orchestration, OMS workflows, execution gateway, event services, market-data services, reconciliation orchestration, operational APIs.

Safety-critical:
- Rust — explicitly selected deterministic/memory-safe components such as validated domain/risk kernels or parsers where the boundary materially improves safety or performance.

Persistence:
- SQL — database schema, constraints, migrations, reporting queries.

Research/Intelligence:
- Python — research, experiments, model evaluation, backtesting, offline self-improvement.

Infrastructure:
- IaC plus controlled shell/configuration where appropriate.

## Language selection rule

A new language may be introduced only when:
1. a concrete requirement exists;
2. the benefit is measurable or strongly justified;
3. the security and maintenance impact is understood;
4. CI/CD/tooling support exists;
5. ownership is assigned;
6. interoperability is contract-based;
7. the language does not create a duplicate authority.

## Security

Using multiple languages does not inherently make the system harder to compromise. Security comes from isolation, least privilege, memory safety where applicable, authentication, authorization, secret isolation, validation, sandboxing, secure supply chain, testing, monitoring, and operational controls.
