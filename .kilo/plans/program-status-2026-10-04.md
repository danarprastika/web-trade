# Program status — 2026-10-04

Snapshot of the platform at `main` = 05dfc64, taken so the next session continues instead of
re-deriving. Every number below was read from `.kilo/ecc/project-brain/work-items.json` or produced
by a command in this repository; nothing here is estimated.

## Where the program actually is

| Measure | Value | Source |
|---|---|---|
| Work items | 66 | `work-items.json` |
| COMPLETED | 39 | `work-items.json` |
| PENDING | 20 | `work-items.json` |
| IN_PROGRESS | 4 | `work-items.json` |
| BLOCKED | 2 | `work-items.json` |
| BLOCKED_OUT_OF_SCOPE | 1 | `work-items.json` |
| Gates passed | **none** | `project.json` `current_state.gates_passed` |
| Commits | 63 | `git rev-list --count HEAD` |
| Repository gates | 14 of 14 PASS | `python scripts/run_gates.py` |
| tests/ci | 229 passed | gate battery |
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
      WI-196  no-stray-SQL gate (WI-120 AC2, closed early) COMPLETED
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

Six work items now exist because a gate was green while proving nothing: a proof that could not see
its own repository, a rule that rejected two correct spellings of `cd`, a guard satisfied by a test
on an unrelated file, a record whose counts had stopped being true, a blocker describing a
repository that no longer existed, and a rule that existed only as a comment in the file that
declared itself its authority. Every fix in this batch is paired with a control that is **measured to
fail** against the code it was written for, and the checks are run against this repository rather
than against fixtures. That is the standing rule for the remaining items.

## Next session starts here

1. WI-120's other two criteria: transactions wrapping every authoritative transition, and
   cross-module mutation only through commands or events. Neither has an enforcement gate; both need
   one, in the same style as `no-stray-sql`.
2. WI-121 (outbox) before WI-117's durability gap is wired, per the architect's assessment — the fix
   is the same-transaction outbox, not a write-ahead log, and it must land before the write path has
   a production caller.
3. The human attestation for G0.8 and G1. Nothing in this list unblocks it; only the user can.