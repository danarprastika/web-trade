# AC4 Durable Buffering: Design Assessment

Scope: read-only architecture assessment for WI-117 AC4 ("bounded durable buffering") in
`services/control-plane/audit`. Recommendation only; no implementation.

## 1. Verification of the stated architecture

Everything in the framing checks out. Verified against source:

| Claim | Verdict | Evidence |
|---|---|---|
| `Guard` state is `pending/limit/halted/haltReason/haltCause` | correct | `audit/guard.go:44-55` |
| `Accept(n)` increments pending, halts fail-closed on `pending+n > limit` | correct | `guard.go:84-97` |
| `Exported(n)` decrements | correct | `guard.go:100-106` |
| `Clear()` refuses while pending > 0 | correct, but only for the `EVIDENCE_BACKLOG` cause | `guard.go:139-154` |
| `SQLSink.Export` writes records + one signed checkpoint per partition in one tx | correct | `sink.go:205-235` |
| A signer is required | correct | `NewAnchor` `sink.go:70-84`, `bootstrap.validate` `bootstrap.go:226` |
| `Exporter.Export` writes sink first, then `guard.Exported(n)` | correct | `sink.go:381-400` |
| `cmd/control-plane/main.go` constructs the sink; `bootstrap` constructs the Exporter | correct | `main.go:321`, `bootstrap.go:164` |
| `Chain.Append(staged)` returns accepted records with sequence + hash | correct, but the param is `records`, not `staged` | `chain.go:71-172` |

### Corrections to the framing

Three things in the framing are wrong or materially incomplete.

**(a) The backlog is not the only in-memory thing that dies in a crash.**
The gap is wider than `pending int`. `Chain` holds every accepted record in
`c.records` and `c.byAuditID` (`chain.go:32-37`), unbounded, with no eviction. So on a
crash the process loses both the count *and the record bodies*. The records are
recoverable only because the chain is rehydrated from `audit_records` at boot
(`bootstrap.go:155`) - meaning anything not yet in `audit_records` is simply gone. This
does not change the recommendation, but it does mean the fix must cover record content,
not just the counter. A design that persists only a pointer/count is not enough.

**(b) The exposure is currently zero in production, because there is no write path.**
`main.go:28-37` and `main.go:435` (`"write_path_exposed": false`) state plainly that no
caller drives Accept-then-Export; only tests do. Confirmed by grep: the only non-test
references to `Accept`, `Exported`, `Allow`, and `ObserveVerification` anywhere in
`services/` are the definitions themselves plus `Exporter.Export`. So no record has ever
been accepted-but-unexported in a running process.

This cuts both ways and is the single most important fact for sequencing:
- It means the gap is **latent, not bleeding**. Nothing is being lost today.
- It means **the fix must land before the write path does**, not after. Whoever wires
  the write path inherits this decision. If the write path ships first with an in-memory
  backlog, the first crash produces the loss.
- It also means the current `Allow` / `ObserveVerification` / `Clear` machinery has no
  production caller either. The whole AC4 control is presently a tested library with no
  enforcement point.

**(c) The severity is understated by "not a silent-drop gap".**
Correct as stated - nothing drops silently. But "bounded" is also not earned, and there is
a specific silent-loss path that framing does not name: `chain.Append` assigns the
sequence and hash *in memory*, and `journal.Apply` writes the record to the chain before
writing to `model_registry` (`journal.go:368` then `journal.go:377`). So a crash between
those two leaves the model_registry row durable and its audit record absent. The next
boot runs `verifyAgainstChain`, which fails closed with "the registry has drifted from the
evidence" - so it is *detected*, not silent. Good. But it converts a lost-evidence event
into a **startup outage**, and the recovery is manual. Rate it as a durability-of-accepted-
evidence gap *whose detection is currently load-bearing*: today, registry/audit
corroboration is the backstop that catches the crash. Any design that removes the
in-memory chain's records must preserve or replace that backstop.

## 2. What docs/22 and ADR-022 actually require

`docs/22_AUDIT_INTEGRITY_AND_EVIDENCE.md` exists. ADR-022 exists only as one line of
`docs/12_DECISION_REGISTER.md:34` - there is no ADR-022 file. Neither document contains
the phrase "durable buffering"; AC4's wording comes from
`.kilo/ecc/project-brain/work-items.json` (WI-117 `acceptance_criteria[3]`) and is
mirrored nearly verbatim in `docs/25` section "Audit sink unavailable"
(`docs/25...md:92`): *"Buffer only within documented bounded durable capacity; block
sensitive operations before evidence can be lost; never silently drop audit events."*

The requirement that actually bears on this design is **docs/22 section 4**, line 19:

> The authoritative operational audit stream is written **transactionally with the
> business mutation or outbox event**. A separate audit exporter copies signed batches to
> a distinct account/project and region using object-lock/WORM retention.

That sentence is decisive and it points away from both A and C. docs/22 section 4 does not
describe a system where accepted records sit in a process buffer awaiting a later flush.
It describes **one transaction containing the state mutation, the audit record, and an
outbox row**, plus a *separate* exporter for the independent copy. That is option B's
shape, with the second hop being an outbox - not a WAL.

Supporting: `docs/05:11` - "An authoritative command executes domain validation, state
mutation, audit record creation, and outbox insertion in one PostgreSQL transaction. A
committed state mutation always has a corresponding durable outbox record." Same
sentence, same architecture. And `docs/08:13` is the answer to question 4 outright:
"Safety invariants are not traded against availability ... every accepted risk-increasing
command must have a durable risk decision and audit event ... These are invariant checks,
not statistical SLOs." So the source documents have already decided question 4 against
availability.

## 3. Recommendation: B, scoped as "the audit record is written in the business
transaction", with the Guard retained but redefined

**Reject A. Reject C. Choose B - but not the naive form of B in the question.**

Option B as posed ("Accept writes to `audit_records` synchronously; Export only does
checkpoint bookkeeping") is close to right but is stated one step too far. Answering the
five sub-questions:

### Q1 - Does B collapse accepted vs exported, and does Guard survive?

Partly, and Guard survives with a *changed* job. If the record is durable at accept time
then `pending` cannot mean "records not yet in `audit_records`", because that set is
empty by construction. It has to mean one of:

- **(B-i) "records committed locally but not yet copied to the independent/WORM copy."**
  This is the reading docs/22 section 4 supports. Guard survives intact, and its bound
  becomes the honest one: the size of the un-shipped backlog. The second hop is exactly
  the outbox in WI-121/122, so `pending` becomes a count of undelivered outbox rows,
  which is durable and recomputable after restart.
- **(B-ii) "records committed to the business transaction but whose checkpoint is not yet
  written."** Weaker; see Q3.

**B-i is the recommendation.** Under it the Guard's fail-closed latch, its `Allow` class
split (read-only and risk-reducing stay available during a halt - `guard.go:162-172`),
its `Clear` refusal, and the `EVIDENCE_BACKLOG` vs `SEV-1_AUDIT_INTEGRITY` cause split all
remain meaningful and none of them need redesign. Only the *counter's meaning* changes,
and the counter's *source* becomes durable state (a query, or the outbox) rather than a
process int.

The thing B actually removes is the current design's worst property: that a record can be
"accepted" - meaning the Guard promised the caller it would be preserved - while living
only in a `map[string][]Record` in a Go heap. B makes acceptance mean the same thing the
caller already assumes it means.

### Q2 - Partial failure semantics

**Option A (WAL):** two nasty cases, both requiring idempotent replay that the schema
actively resists.
- WAL write succeeds, process dies before the chain advances. On restart the WAL holds
  records whose sequence/hash were assigned by a chain that no longer exists. Replaying
  them re-runs `GetNextAuditSequence`-style allocation against a chain rehydrated from
  the DB - the sequences may now collide or gap. The 0002 migration's
  `audit_records_chain_link` constraint trigger (`0002_audit.sql:165-199`) will refuse a
  record with no predecessor, so a partially-replayed WAL is a startup failure, not a
  quiet resume.
- Export commits, WAL delete does not. Replay re-inserts an existing `audit_id`.
  `AppendAuditRecord` has **deliberately no ON CONFLICT** (`db/dbgen/audit.sql.go:129-135`:
  "a duplicate audit_id is a genuine conflict between two different facts, and silently
  returning the existing row would make the second write disappear while the caller
  believed it was recorded"). So idempotent replay cannot be done with an upsert. It has
  to be a read-then-decide, and "decide" has to distinguish retry from contradiction -
  which `Chain.Append` already does in memory (`chain.go:112-127`) and which would have
  to be reimplemented against durable state. Possible, but it is new correctness surface
  in the most safety-critical component in the repo, and the honest cost is that A is a
  second source of truth for audit content, held outside the database that enforces the
  chain link, the coverage check, and append-only.

**Option B-i:** the failure windows mostly disappear, because there is no second copy to
reconcile.
- Crash mid-transaction: the DB rolls back. Record and mutation both absent. No accepted
  evidence is lost, because nothing was accepted - the caller's transaction failed.
  This is the property A cannot offer and the reason B is the right shape.
- The residual window is **between the local commit and the independent copy**. That
  window is exactly what the outbox (WI-121) makes durable: the outbox row is committed
  in the same transaction as the audit record, so "committed locally but not yet shipped"
  is a *queryable durable fact*, not a heap count. The Guard latches on that fact.
- The genuinely hard residual, already recorded as open in WI-117's blocker: **a driver
  error during `Commit` whose outcome the caller cannot determine.** Under B this is worse
  in one specific way and better in another. Worse: the commit carries the business
  mutation, so "did it commit?" is now a question about a model transition, not about a
  log flush. Better: it is answerable, because the caller can re-read the row and compare
  - which is what `model_transition_idempotency` (WI-123) exists to make safe. B makes
  that hazard *legible* rather than hiding it inside a retry loop.

### Q3 - Does the existing transaction shape help or conflict?

**It helps, and it constrains where the boundary may be drawn.**

`SQLSink.Export` writes records and checkpoints in one transaction, with the checkpoint
signed *before* the transaction opens (`sink.go:210-217`) so an unanchorable batch writes
nothing. `0002_audit.sql` backs this with two deferred constraint triggers -
`audit_records_chain_link` and `audit_checkpoints_coverage` - both
`DEFERRABLE INITIALLY DEFERRED` so order within the transaction does not matter but
completeness at commit does. This is a good shape and B should preserve it verbatim.

The constraint B must respect: `audit_checkpoints_coverage` requires, at commit, that
`record_count` records exist in the range and that the boundary hashes match. So a
checkpoint cannot be written in a *later* transaction than its records unless it covers a
range already present. That is why B-i beats B-ii: **the checkpoint belongs in the same
transaction as the records**, and what is deferred to the outbox is only the *independent
copy* of an already-anchored batch. Deferring the checkpoint (B-ii) is legal only because
the trigger is deferred, and it widens the window in which a partition's tail is neither
stored nor anchored - which is precisely the unanchored-truncation state `restore.go:125-171`
was written to refuse.

So: keep `SQLSink`'s transaction shape exactly as is. B changes *when* it is called, not
*what* it does.

### Q4 - Which failure is worse

The documents answer this, so I will not relitigate it:

- `docs/08:13` - safety invariants are not traded against availability; an accepted
  risk-increasing command *must* have a durable audit event, as an invariant not an SLO.
- `docs/25:92` - the required behaviour under sink unavailability is to *block*, not to
  buffer harder.
- `docs/22:15` - a chain break is SEV-1 and stops risk-increasing activity.

For a trading system the ordering is: **never lose accepted evidence; do block when you
cannot store it.** Losing accepted audit evidence means a transition happened that the
platform cannot prove or disprove, which for a regulated book is worse than a halt. Note
also that under B the blocking is *narrower* than the framing assumes, not broader: today
the guard blocks when a process-local counter nears a limit regardless of whether
anything is actually wrong with storage. Under B-i the latch condition becomes "the
durable un-shipped backlog exceeds its bound", which trips only when the independent copy
is genuinely behind.

### Q5 - If C, what would make it defensible

C is still the wrong answer, but since asked: it would require all of the following, and
none of it exists today.

1. **A durable record of the loss.** A metric is not enough. Every halt must emit a record
   naming the accepted-but-unexported `audit_id`s and their sequence range.
   `audit_deletion_events` (`0002_audit.sql:104-117`) is the wrong table; it models
   approved deletion. This needs a new table, which is itself a schema change.
2. **`/readyz` must be scrape-promoted.** `main.go:408-462` already reports
   `audit_backlog{pending,limit,halted}` and returns 503 on halt. That is a real
   compensating control and it already exists - but there is **no metrics exporter anywhere
   in the repo** (no prometheus/otel/`/metrics`; grep confirms) and `ops/runbooks/` holds
   only `.gitkeep`. So the alert does not exist and the runbook does not exist.
3. **A restart-time reconciliation that detects the gap.** Today `bootstrap.Build` does not
   compare `audit_records` sequences against anything, so a crash that lost records leaves
   no trace until `verifyAgainstChain` happens to catch it via a registry row.
4. **A documented capacity figure.** `docs/25:92` says "documented bounded durable
   capacity". `CONTROL_PLANE_GUARD_LIMIT` defaults to 1000 (`main.go:226`) and nothing
   documents what 1000 records is worth in bytes or seconds.

So C would need a metrics pipeline, a runbook, a new table, and restart reconciliation,
all of which cost more than B and leave the invariant unimplemented. C is not the cheap
option here.

## 4. Existing structures to reuse

**There is no durable queue, WAL, spool, or outbox in the repository.** Verified:

- No `fsync`, `os.OpenFile`, `O_APPEND`, bolt, badger, or LevelDB anywhere
  (grep over the whole tree: no matches).
- No outbox table in any migration. All four migrations (`0001_ledger`, `0002_audit`,
  `0003_authz`, `0004_model_registry`) were enumerated by `CREATE TABLE`; there is none.
- The only `outbox` mentions in Go are a comment in `contracts/go/envelope.go:291` and
  the schema description in `contracts/schema/event-envelope.schema.json:5`, both citing
  ADR-006.
- `WI-121` "Transactional outbox" and `WI-122` "Outbox dispatcher" are both **PENDING**,
  phase 3, `WI-121` depends on `WI-120` (also PENDING) which depends on `WI-118`
  (**BLOCKED**).

**So: the outbox is the intended answer, plainly, and it does not exist yet.** The
repository has already decided this - `ADR-006` (Accepted, `docs/12:10`), `docs/05:11`
and `:15`, and `contracts/go/envelope.go:288-293` (delivery is at-least-once, `Sequence`
exists so a consumer can detect a gap or a duplicate, "rather than to prove delivery").
`WI-121`'s AC already contains AC4's substance: *"Delayed dispatch: no event loss, no
duplicate domain transition; alert on lag; bounded backpressure"*.

How the audit backlog would use it, concretely:

1. Migration adds `audit_outbox` (partition, first_sequence, last_sequence, created_at,
   dispatched_at NULL). Rows are appended by a deferred trigger on `audit_checkpoints`
   insert, or by the sink in the same transaction - either way, same transaction.
2. The dispatcher is the WI-122 component: `SELECT ... FOR UPDATE SKIP LOCKED` over
   undispatched rows, copy the anchored batch to the independent account/region, set
   `dispatched_at`.
3. The Guard's `pending` becomes `count(*) FROM audit_outbox WHERE dispatched_at IS NULL`.
   That is **durable and correct across restart**, which is the entire gap.
4. `Clear()`'s refusal condition becomes "the un-shipped backlog is non-empty", which is
   what it means today, but now checkable after a crash.

Note the layering this produces, and it is the right one: **B closes the local half, the
outbox closes the independent half, and the Guard spans both.** `pending` counts what has
not reached independent immutable retention - which is exactly what `docs/22` section 4
and the `sink.go:22-26` comment ("one database is not independent of the process that
writes to it") are actually asking about. The current Guard counts something less
meaningful.

**This is a scope decision, not a code decision.** B-i requires WI-120 (transactional
repositories via sqlc) to build the transaction, and WI-121 to make the second hop
durable. All three are PENDING or BLOCKED and WI-118 blocks WI-120. Attempting to close
AC4's durable-buffering half inside WI-117 alone means either duplicating the outbox or
shipping a WAL - which is why the honest recommendation includes re-sequencing.

## 5. Failure semantics of the recommendation, stated precisely

Under B-i with the outbox:

| Event | Outcome | Detectable by |
|---|---|---|
| Crash before business tx commits | Nothing happened. No audit record, no mutation, no backlog entry. Caller sees an error. | n/a - correct by construction |
| Crash after commit, before dispatch | Audit record + anchored checkpoint + outbox row are durable. Nothing is lost. Backlog is non-zero and durable. | `pending` after restart, which is now computed from `audit_outbox`, so it is *correct* after restart rather than reset to zero |
| Independent copy unavailable | Outbox rows accumulate. At the bound, Guard latches `EVIDENCE_BACKLOG`. Read-only and risk-reducing continue; risk-increasing and privileged mutations refuse. | `Guard.Halted()`, `Allow(class)`, `/readyz` 503 |
| Outbox dispatcher crash mid-batch | `FOR UPDATE SKIP LOCKED` releases the rows; redelivery is at-least-once. Consumer is idempotent by `audit_id` + sequence range. | standard |
| Commit outcome unknown (driver error) | **The open hazard.** Under B the commit carries the business mutation. Resolve by re-reading the row and comparing; WI-123's idempotency constraint is what makes this safe. | must be closed before B ships |
| Duplicate audit_id on replay | Refused, loudly. No ON CONFLICT, by design. | `AppendAuditRecord` error |

The one thing B does *not* fix, and which must not be lost in the transition: today
`Allow` and `ObserveVerification` have no production caller, and
`"write_path_exposed": false`. B makes the evidence durable; it does not make anything
*block*. The enforcement point is the write-path handler, and that is separate work.

## 6. Acceptance tests I would require before believing the gap is closed

Named concretely, in the style the repo already uses. Every one of these must be shown to
**fail** when the property is removed - a mutation gate per property, following the
existing `scripts/mutation_check_anchor.py` and `scripts/mutation_check_drain.py`
precedent, since this repo has a documented history of green-but-vacuous tests (EV-064,
EV-065, and the WI-117 blocker text itself).

**Durability of accepted evidence**
1. `TestAcceptedAuditRecordsSurviveAProcessCrash` - integration, live PostgreSQL. Accept
   N records through the real Exporter against a real sink, `os.Exit` the test process
   without draining, restart, rehydrate via `audit.Rehydrate`, and assert all N records
   and their checkpoint are present. This is the test that cannot exist today and is the
   direct answer to AC4's "durable".
2. `TestTheBacklogAfterRestartEqualsTheDurableUnshippedCount` - kill with a non-empty
   outbox backlog, restart, assert `Guard.Pending()` equals `count(undispatched)` and is
   non-zero. This catches the current defect precisely: today pending resets to 0 on
   restart while the records are gone.
3. `TestAnAuditRecordIsNeverAbsentWhileItsRegistryRowExists` - the crash-between-append-
   and-persist case from correction (c). Assert the invariant either holds or is detected
   at boot, so the backstop cannot silently regress.

**Atomicity and the transaction shape**
4. `TestTheBusinessMutationTheAuditRecordAndTheOutboxRowCommitTogether` - force a failure
   at each of the three write points in turn; assert the transaction rolls back whole each
   time. No partial commit, ever.
5. `TestACheckpointCannotCommitWithoutItsRecords` - the deferred-trigger property. Assert
   `audit_checkpoints_coverage` refuses an orphaned checkpoint at commit. If B ever widens
   the checkpoint window, this fails.
6. `TestTheDriverErrorDuringCommitIsAnswerableByReRead` - the open hazard. Simulate an
   indeterminate commit and assert the re-read resolves it. Must be paired with WI-123.
7. `TestAnOutboxRowIsNeverCreatedWithoutItsCheckpoint` - and the converse. The outbox is
   not a second, looser writer of audit evidence.

**Fail-closed behaviour**
8. `TestSensitiveOperationsBlockOnDurableBacklogNotOnACounter` - fills the *durable*
   backlog, asserts `OpRiskIncreasing` and `OpPrivilegedMutation` refuse while
   `OpReadOnly` and `OpRiskReducing` proceed. Same shape as
   `TestSensitiveOperationsAreBlockedWhenTheBacklogIsFull`, but driving the durable path.
9. `TestClearStillRefusesWhileTheDurableBacklogIsNonEmpty` - the `Clear` refusal
   (`guard.go:143-149`) must survive the counter's change of meaning. Guard against a
   regression to the unconditional `Clear()` that EV-044 caught.
10. `TestACommittedMutationWithNoUnshippedCopyTripsNoFalseHalt` - the converse. Proves the
    new bound is not so eager that it halts on a healthy system.

**Idempotence and replay**
11. `TestRedeliveryOfAnAlreadyDispatchedBatchIsANoOp` - dispatcher replays a dispatched
    batch; assert no duplicate `audit_records` row and no duplicate checkpoint, and that
    the `audit_id` conflict is refused rather than upserted.
12. `TestTheGuardLatchesAcrossRestartOnADurableBacklog` - halt, kill, restart, assert the
    latch survived. Today it cannot: `halted` is a `bool` in a struct.

**Non-vacuity, per property above**
13. A mutation gate per numbered test. The repo's own evidence records twice found tests
    that could not fail. Any acceptance test for this work that has not been shown to fail
    against a broken implementation should be treated as not written.

**Also required, and cheap:** update `WI-117`'s blocker text and `docs/25:92`'s
"documented bounded durable capacity" with the actual figure the new bound represents.

## 7. What I would NOT do

- **Do not build a WAL.** It creates a second source of truth outside the database that
  enforces the chain link and append-only, requires re-implementing retry-vs-contradiction
  against a schema that deliberately refuses upserts, and does not compose with
  `GetNextAuditSequence` or the deferred chain-link trigger on replay.
- **Do not defer the checkpoint to Export (B-ii).** Legal only because
  `audit_checkpoints_coverage` is deferred, and it reopens the unanchored-tail window that
  `restore.go:125-171` exists to refuse.
- **Do not close AC4 inside WI-117 alone.** It needs WI-120's transaction and WI-121's
  outbox. The scope decision - re-sequence, or duplicate the outbox inside WI-117 - is a
  call for the work-item owner, and duplicating it would create exactly the two-writers
  problem the whole package is built to prevent.
- **Do not wire the write path before this lands.** It is the thing that turns a latent gap
  into a real loss, and it is currently one commit away.

## 8. Recommendation summary

Choose **B-i**. Write the audit record, its signed checkpoint, and the outbox row in the
same PostgreSQL transaction as the business mutation (docs/22 section 4, docs/05:11,
ADR-006). Retain the Guard with its latch, its class split, and its `Clear` refusal, and
redefine `pending` as the count of committed-but-not-independently-dispatched rows -
durable, recomputable after restart, and the quantity `docs/22` section 4 actually cares
about. Reuse WI-121's outbox rather than inventing a queue; there is nothing in the repo
to reuse today because the outbox has not been built. Reject A (second source of truth,
resists its own idempotence requirement) and C (needs a metrics pipeline, a runbook, a new
table, and restart reconciliation that do not exist, and leaves the invariant
unimplemented). Sequence B-i after WI-120 and WI-121, and before the write path is
exposed.
