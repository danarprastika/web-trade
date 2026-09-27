# Final Coding Baseline Index — v1.1.0

**Status:** Finalized documentation baseline for controlled G1 planning  
**Target development executor:** Kilo Code  
**Implementation authorization:** NOT GRANTED  
**Live authorization:** NOT GRANTED

## Project intent

A long-lived, production-capable AI-native proprietary trading system. Automated trading is the primary purpose; AI agents support research, analysis, and governed operation. This is not an MVP-only target.

## Technology boundaries recorded by the source baseline

- Frontend: TypeScript, HTML, CSS; Rust/WASM only when justified by a documented need.
- Backend: Go as the primary service language.
- Safety-critical components: Rust only where explicitly justified and approved.
- AI, research, and backtesting: Python.
- Persistence: SQL under the approved transactional integrity contract.
- Infrastructure: Infrastructure as Code.

These are architecture boundaries, not permission to introduce additional languages or services without the applicable decision and gate review.

## Quality and authority

Language diversity is not security-by-obscurity. Each component must have a clear responsibility, owner, contract, test strategy, security review, and operational support model.

AI proposals do not authorize execution. Risk remains the mandatory authorization/veto authority; OMS and execution follow the approved command path; reconciliation verifies external state; portfolio state derives from verified fills.

## Finalized documentation scope

The package includes normative and implementation-control material through document 104. The authoritative file inventory is `ENTERPRISE_FINAL_DOCUMENT_INDEX.md`. Numeric gaps and duplicate prefixes are historical identifiers, not implied missing requirements or precedence rules.

## Current readiness

G0’s package declaration is retained as historical evidence. Phase 0 revalidation identified unresolved G1 blockers. G1 implementation is not authorized until blockers are dispositioned, entry criteria are met, and a gate decision is recorded.

## Change rule

No generic specification expansion is needed merely to increase document count. Concrete gaps require a Change Request, impact analysis, approval, implementation, verification, evidence, and traceability update.
