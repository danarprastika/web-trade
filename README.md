# web-trade

**AI-native proprietary trading platform — full-scale enterprise implementation.**

The single engineering authority for this repository is [`docs/`](docs/) — 26 Markdown specifications plus
[`docs/MANIFEST.json`](docs/MANIFEST.json), digest-verified as a package. This repository implements that blueprint.
Where implementation detail and the blueprint disagree, **the blueprint wins** and the difference is an ADR, not a
quiet code change.

> **Status.** The specification is complete. The runtime system is **not** production-ready and holds no live-trading
> capability. No gate below G0 has runtime evidence, and G11 (live activation) is deliberately out of engineering scope.
> See [`docs/25`](docs/25_DEEP_ARCHITECTURAL_AUDIT_AND_FULL_SCALE_RELEASE_PROFILE.md) §1 and §10.

## Operating principle

> AI may propose. Deterministic controls decide. The OMS records the authoritative order state.
> Reconciliation resolves external truth. The ledger records financial facts.

No component may create a second source of truth for order status, financial balances, risk authorization, or
identity. Live capability is disabled by default and cannot be enabled without exact-scope legal eligibility,
verified adult account-holder authority, two-person approval, and passing release gates.

## Canonical repository shape

| Path | Language | Responsibility | Authority |
|---|---|---|---|
| `apps/web` | TypeScript / React / Next.js | Operator UI, dashboards, audit views | Presentation only — untrusted client |
| `services/control-plane` | Go | Identity enforcement, policy integration, domain commands, config, risk, OMS, reconciliation, ledger APIs | **Authoritative application layer** |
| `workers/research` | Python | Datasets, experiments, feature engineering | Offline, non-authoritative |
| `workers/backtest` | Python | Deterministic simulation, artifact production | Offline, non-authoritative |
| `components/risk-engine` | Go | Deterministic financial veto | Authoritative veto |
| `components/oms` | Go | Canonical order lifecycle state machine | Authoritative |
| `components/reconciliation` | Go | Internal vs external convergence | Authoritative |
| `adapters/venues` | Go | Venue translation and submission | Reports observations only |
| `contracts` | Language-neutral | Canonical schemas for every boundary | Single source of truth for cross-language types |
| `db/migrations` | SQL | PostgreSQL 17 schema evolution | System of record |
| `infra/terraform` | HCL | Declarative infrastructure | Provisioning only |
| `ops/runbooks` | Markdown | Operational procedures | Human execution |
| `tests` | Multi | Cross-cutting and acceptance tests | Evidence |
| `docs` | Markdown | The authoritative specification | **Overrides all of the above** |

The control plane is a **modular monolith**. Services are split only when load, fault isolation, or a security
boundary justifies it. Premature microservice fragmentation is prohibited.

## Prohibitions

These are enforced in code review, not just documented:

- No floating-point value may cross a financial contract. Money is a base-10 decimal string plus a currency.
- No AI or model output may authorize its own execution.
- No cache may become authoritative through fallback behavior. Redis is cache only.
- No retry may turn an unknown external outcome into a second exposure-increasing command.
- Research workers hold no live credentials and no authoritative write path.
- The UI cannot establish authorization, risk approval, order state, or financial balances.
- Venue adapters cannot modify policy, risk configuration, or ledger facts.
- No secret is committed. See [`.env.example`](.env.example) and [`.gitignore`](.gitignore).

## Execution gates

`G0` specification integrity → `G1` domain foundation → `G2` market data → `G3` trading core → `G4` research →
`G5` AI company OS → `G6` simulation/shadow → `G7` operator interfaces → `G8` venue adapters →
`G9` security/operations → `G10` production readiness. `G11` live activation is out of engineering scope.

A gate is PASS only when every listed criterion is satisfied. Partial completion is FAIL, not a percentage.
No gate may be marked passed on documentation alone. See [`docs/11_EXECUTION_GATES.md`](docs/11_EXECUTION_GATES.md).

## Execution state

Plan, work items, decisions, risks, and verification evidence live in
[`.kilo/ecc/project-brain/`](.kilo/ecc/project-brain/requirements.md). That directory records *execution* state and
never overrides `docs/`.

## Toolchain

Selected at bootstrap and pinned; the latest stable security-supported release for each language, exact versions
recorded in lockfiles, no end-of-life runtime in a production artifact. CI fails on unpinned dependencies or
toolchain drift. See [`docs/00_README.md`](docs/00_README.md) (toolchain lifecycle) and
[`docs/02_POLYGLOT_ENGINEERING_STANDARD.md`](docs/02_POLYGLOT_ENGINEERING_STANDARD.md) §10.
