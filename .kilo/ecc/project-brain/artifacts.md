# Artifacts — web-trade

## Project Brain (created by this command)

| Path | Purpose | Status |
|---|---|---|
| `.kilo/ecc/project-brain/project.json` | Project identity, scale, authority, toolchain, current state, plan pointer | Created |
| `.kilo/ecc/project-brain/requirements.md` | Source facts, assumptions, traceability, phased WBS, dependency DAG, acceptance criteria, verification plan, gates, risks, open questions | Created — plan v1.0.0 |
| `.kilo/ecc/project-brain/architecture.md` | Authority hierarchy, topology, bounded contexts, module decomposition, polyglot boundaries, state-machine discipline, trust zones, failure rules, invariants, security architecture, repo shape, toolchain policy | Created |
| `.kilo/ecc/project-brain/work-items.json` | 40 work items with status, dependencies, acceptance criteria, write scopes, gate mapping | Created |
| `.kilo/ecc/project-brain/decisions.md` | EXD-001…EXD-010 execution decisions + open decisions OD-1…OD-3 | Created |
| `.kilo/ecc/project-brain/risks.md` | RISK-01…RISK-10 + blockers BLK-1…BLK-3 | Created |
| `.kilo/ecc/project-brain/evidence.jsonl` | EV-001…EV-004 recorded evidence with method, command, and raw output | Created |
| `.kilo/ecc/project-brain/events.jsonl` | EVT-0001…EVT-0009 lifecycle events | Created |
| `.kilo/ecc/project-brain/artifacts.md` | This index | Created |

## Inspected (pre-existing, unmodified)

| Path | Role |
|---|---|
| `docs/00_README.md` … `docs/25_*.md` | 26 authoritative specifications — the single engineering authority |
| `docs/MANIFEST.json` | Package manifest with SHA-256 digests; G0 verification input |

No pre-existing project instructions (`AGENTS.md`, `CLAUDE.md`, `.kilo/`), no manifests, no CI, no tests, and no source code were found.

## Referenced in history (not present in the working tree)

| Commit | Content | Disposition |
|---|---|---|
| `be3ef5d` "clear" | Deleted 358 files including all `backend/` and `frontend/` code | Non-conformant; not a restore target |
| `7327bfd` | sprint4: news intelligence, technical analysis, dashboard widgets | Reference only |
| `6f6bde0` | sprint3: paper trading engine, risk, strategies, dashboard | Reference only |
| `49e98c2` | sprint2: OAuth, watchlist, market | Reference only |

## Planned (not yet created)

`/apps/web`, `/services/control-plane`, `/workers/research`, `/workers/backtest`, `/components/risk-engine`, `/components/oms`, `/components/reconciliation`, `/adapters/venues`, `/contracts`, `/db/migrations`, `/infra/terraform`, `/ops/runbooks`, `/tests`, `.github/workflows`.

## Notes

Kilo's built-in configuration validator emits an "Unrecognized keys" warning when it probes `*.json` under `.kilo/`. This is the harness's own config loader, not a defect in these artifacts — the V7 path `.kilo/ecc/project-brain/project.json` is mandated by the Project Brain specification.
