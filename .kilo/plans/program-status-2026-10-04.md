# Program status — 2026-10-04

Snapshot of the platform at `main` = 3b9c9bb, taken so the next session continues instead of
re-deriving. Every number below was read from `.kilo/ecc/project-brain/work-items.json` or produced
by a command in this repository; nothing here is estimated.

## Where the program actually is

| Measure | Value | Source |
|---|---|---|
| Work items | 65 | `work-items.json` |
| COMPLETED | 39 | `work-items.json` |
| PENDING | 20 | `work-items.json` |
| IN_PROGRESS | 4 | `work-items.json` |
| BLOCKED | 2 | `work-items.json` |
| BLOCKED_OUT_OF_SCOPE | 1 | `work-items.json` |
| Gates passed | **none** | `project.json` `current_state.gates_passed` |
| Commits | 58 | `git rev-list --count HEAD` |
| Repository gates | 13 of 13 PASS | `python scripts/run_gates.py` |
| tests/ci | 211 passed | gate battery |
| G0 verdict | `PENDING_HUMAN_ATTESTATION` | `scripts/verify_spec_gate.py` |

Phase 2 work is largely built (CI pipeline, control-plane domain core, database assertions for all
four migrations, migration rehearsal, tamper-evident audit chain). Phases 3–6 are the bulk of the
platform and are **not** started.

## The two things that cannot be done by an agent

`docs/11_EXECUTION_GATES.md` requires six fields in every gate report, and two of them are a
**named human reviewer** and a **binary verdict over a reviewed commit**. An automated agent
recording itself as the reviewer satisfies the field and none of its purpose, so this repository
does not do it.

1. **G0.8 — specification attestation.** G0.1–G0.7 pass mechanically (manifest, byte lengths,
   SHA-256 digests, no unlisted or duplicate documents, no unresolved architecture choice).
   G0.8 needs a named human to attest the package.
2. **G1 reviewer — the same requirement, one gate later.** WI-118 is BLOCKED on this.

These are on the critical path: WI-120 depends on WI-118. Engineering can proceed against a frozen
specification — its digests are pinned, so it cannot drift under the build — but the **gate reports**
cannot be completed, and therefore the platform cannot be declared operational, until a human signs.

**This is the one item that needs the user.** Everything else below is agent work.

## Critical path, in dependency order

```
G0.8 human attestation          <-- external, blocks everything below at the gate level
  WI-118  G1 domain foundation gate report      BLOCKED (reviewer)
    WI-120  Transactional repositories via sqlc          PENDING
      WI-121  Transactional outbox                        PENDING
        WI-122  Outbox dispatcher                         PENDING
      WI-123  Database-enforced idempotency              PENDING
      WI-124  Replay utilities                           PENDING
      WI-125  Reconciliation case storage                PENDING
    WI-130  Market data normalization + ingestion        PENDING
    WI-131  Simulated/paper/shadow execution + recon     PENDING
    WI-132  Venue adapter interface + contract tests     PENDING
    WI-140  Dataset registry + deterministic backtest    BLOCKED (deps WI-139)
    WI-141  Model registry, evaluation, decision ledger  IN_PROGRESS
    WI-142  Promotion workflow                           PENDING
    WI-150  Operator web control plane                   PENDING
    WI-151  Audit views, risk dashboards, controls       PENDING
```

WI-117 (tamper-evident audit chain) is IN_PROGRESS and has a known durability gap: the chain holds
records in process memory, so a crash between `Append` and persist loses the record body. The
architect's assessment (`.kilo/plans/1790888029810-audit-backlog-durability-design.md`) is that the
fix is the same-transaction outbox of WI-121, not a write-ahead log, and that it must land **before**
the write path is wired. Exposure today is zero — no non-test caller of `Accept` exists — so this is
latent rather than live.

## Checked this session, so it is not re-chased

Four defects reported by review on earlier commits were re-inspected in the current tree. All four
are resolved, with the fix located in the code rather than inferred from the review:

- **migrate `-to 1` destroying the audit schema** — `cmd/migrate/main.go:146` now guards *every*
  `down`, with `migrate.CommandOptInPolicy()` (`OptInOverrides: false`), and the comment at :130
  states why a bound cannot be the thing that decides safety.
- **Restore rebuilding an incomplete idempotency Outcome** — `model/restore.go:79-93` rebuilds via
  `TransitionFor(entry.From, entry.To)` and carries `ModelID`, `EventType`, `IdempotencyScope` and
  `FailureBehavior`.
- **Duplicate `audit_id` accepted within one batch** — `audit/chain.go:77` adds an `inBatch` index,
  because `byAuditID` is only written after the batch commits.
- **Halt latch losing a SEV-1 cause behind a backlog cause** — `audit/guard.go:145`
  `haltCauseEscalatesTo` escalates backlog to SEV-1 integrity.

## The one defect class that keeps recurring

Five separate work items in this program (WI-193, WI-194, WI-195, EV-091, EV-096) exist because a
gate was green while proving nothing: a proof that could not see its own repository, a rule that
rejected two correct spellings of `cd`, a guard satisfied by a test on an unrelated file, a record
whose counts had stopped being true. Every fix in this batch is paired with a control that is
**measured to fail** against the code it was written for, not asserted to be the right shape. That
is the standing rule for the remaining items.