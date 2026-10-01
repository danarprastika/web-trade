"""Correct WI-117's stale blocker and partial_results.

The narrative in work-items.json was written when the audit sink had no producer, no composition
root, and no checkpoints. All three of those are now implemented and committed, but the text still
says they are missing. A blocker that misreports the state is worse than an absent one: the next
engineer reads it, concludes an Exporter is never constructed, and goes to build one that already
exists at main.go:321 and bootstrap.go:164.

This rewrites only the two fields, and it keeps the EV-044 history, because that history is the
reason the item was reopened and a reviewer who disagrees with the current reading needs to be able
to reconstruct the original claim.

What is stated as resolved is stated because a specific committed artifact establishes it, and
those artifacts are named so the claim can be checked rather than trusted. What remains is stated
as remaining, including one gap that is easy to miss: the guard's backlog between accept and export
is a bare in-memory int, so AC4's "bounded DURABLE buffering" is only half met. The sink is
durable; the buffer in front of it is not, and a process death loses accepted-but-unexported
records. That is a real limitation of the current design, not a defect introduced by this update,
and it is recorded here rather than smoothed over.
"""

from __future__ import annotations

import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
TARGET = REPO / ".kilo" / "ecc" / "project-brain" / "work-items.json"

NEW_BLOCKER = (
    "Reopened by EV-044: AC4 is not implemented, so the COMPLETED status overstated the state. The "
    "Guard that would implement it is correct in isolation and tested - bounded backlog, latched "
    "fail-closed halt, explicit Clear, no drop, no overwrite-oldest, no truncate, and a class split "
    "that keeps read-only and risk-reducing operations available - but its backlog is reduced by "
    "exactly one function, Exported, and nothing outside guard_test.go calls it. There is no audit "
    "sink: db/migrations/0002_audit.sql creates audit_records, audit_checkpoints and "
    "audit_deletion_events and db/dbgen/audit.sql.go is generated, but no Go code writes to them, "
    "so the durable-buffering half of AC4 does not exist. Observed consequence: with a limit of 3 "
    "the fourth Accept halts with DEPENDENCY_UNAVAILABLE and pending still at 3, and recovery is "
    "possible only through a manual privileged Clear. A guard wired in its current state would "
    "therefore latch permanently at its limit, and no wiring can fix that because the exit "
    "condition has no producer. To close: implement a durable audit sink that exports accepted "
    "records and calls Exported, and add the assertion that a guard whose sink recovers drains its "
    "backlog and un-halts without a manual Clear. Not part of this item: the absence of a "
    "composition root, which belongs to WI-164 and WI-165. Not disputed: the hash chain, "
    "checkpoints, retention, key rotation and the in-memory verifier, which are implemented and "
    "tested. The previous COMPLETED state and its completed_at stamp are preserved in the item's "
    "completion_note and in EV-044, so a reviewer who disagrees with this reading can restore the "
    "status."
    " || "
    "EV-045 implemented the sink, the exporter, and a backlog-aware Clear, closing the structural "
    "blocker recorded by EV-044. THIS PARAGRAPH CORRECTS THE ONE THAT PRECEDED IT, which is kept "
    "above because it is the claim being corrected."
    " || "
    "Corrected on review, because that earlier ending no longer described the tree. It said the "
    "item remains IN_PROGRESS because nothing constructs an Exporter and because the transaction, "
    "commit and mid-commit driver-error paths are unproven against a live database. Both were true "
    "when written and neither is now."
    " || "
    "A composition root exists and constructs both halves. cmd/control-plane/main.go builds "
    "audit.NewSQLSink with a checkpoint signer and hands the sink to bootstrap.Deps, and "
    "bootstrap.Build constructs audit.NewExporter(guard, d.Sink) and refuses to build without a "
    "sink, so the guard's backlog has a producer in the running process rather than only in tests. "
    "bootstrap_test.go asserts the sink actually received the record, which is what distinguishes a "
    "drained backlog from a merely-wired one. A nil Sink is a build failure and is named in the "
    "refusal."
    " || "
    "The sink now closes what it stores. Export groups its records by partition, signs one "
    "checkpoint per partition before the transaction opens, and inserts records and checkpoints in "
    "the same transaction, so a batch that cannot be anchored writes no records and there is no "
    "window in which records commit unanchored. A signer is required by both NewSQLSink and the "
    "composition root. This closed a defect the re-review found in the previous fix: restore read a "
    "partition's latest checkpoint and refused an archive whose head fell behind it, but nothing "
    "wrote that table, and every test of the fix had been inserting its own checkpoint by hand."
    " || "
    "The transaction and commit paths are now proven against live PostgreSQL rather than only "
    "against a fake querier: TestTheSinkWritesACheckpointThatARehydrationFinds writes through the "
    "real SQLSink and rehydrates through the real SQLChainReader. The pinning constraint that made "
    "a live driver unavailable to unit tests still stands for a mid-commit driver error - a "
    "connection lost during Commit, after the driver has begun the transaction - which no test "
    "simulates and which the real driver would surface as a commit whose outcome is unknown to the "
    "caller. That is a distinct hazard from a clean commit and remains open."
    " || "
    "It therefore remains IN_PROGRESS on four things, none of which is a structural hole and all "
    "of which are recorded rather than asserted away. First, AC4's word DURABLE is not yet earned: "
    "the sink is durable, but the backlog between Accept and Export is a bare in-memory int on the "
    "Guard, so a process death loses accepted-but-unexported records and the guard's own count goes "
    "with them. Closing that needs a write-ahead log in front of the sink, which is a design "
    "decision rather than a bug fix. Second, independent immutable retention: docs/22 section 4 "
    "requires a second, independent copy, the interface now permits one, and only one sink is "
    "constructed. Third, the anchor is signed by audit.LocalSigner, which is in-process and "
    "ephemeral, so a restart mints a new key and an earlier process's checkpoints cannot be "
    "verified against the new ring; nothing is functionally broken because the anchored restore "
    "compares sequence and hash and does not verify signatures, but a KMS-backed signer is "
    "outstanding. Fourth, Clear latches on the first cause, so a backlog halt followed by a SEV-1 "
    "integrity failure is released by Clear without the integrity failure ever being surfaced; "
    "this is recorded as not-primary only because ObserveVerification still has no production "
    "caller, and it becomes live the moment one is added."
)

NEW_PARTIAL_RESULTS = (
    "Chain: per-partition hash chain, sequence and previous-hash assignment, batch atomicity, "
    "duplicate-delivery idempotence, and conflict detection on reused identities, all verified. "
    "Retention and deletion: every precondition checked independently, with two-person approval "
    "and self-approval refused, verified. Checkpoints: signed over a range, refusing a hole, a "
    "wrong count, and a chain that does not resume from its checkpoint, verified. Integrity "
    "verification: tamper, deletion, reorder, replay, signature failure, and restore detection all "
    "pass, and every finding is SEV-1. AC4 is partially implemented rather than absent: a Sink "
    "port with a SQL-backed implementation, an Exporter that gives the guard's backlog a producer, "
    "and a Clear that refuses while evidence is unexported instead of appearing to succeed. "
    "Defects found and fixed: 4 of 41 model mutations were build failures that the harness had been "
    "counting as detections, so two prior evidence records overstated their coverage; the one claim "
    "among them - that a refusal is not a state change - was enforced by no test until "
    "TestARefusedRequestWritesNoAuditRecord was added; that mutation was itself a no-op because it "
    "drew the partition from the zero Record on the branch it injected into; an audit mutation "
    "tested a property that could not fail because the language already provides the copy it "
    "claimed the code was making; and the hash-copy test asserted a property the language "
    "guarantees rather than the code."
    " || "
    "SITUATION NOW, correcting the previous ending of this field, which is kept above for the same "
    "reason. Resolved since it was written: the composition root exists and constructs both the "
    "sink and the exporter, so the backlog is drained in the running process; the sink writes signed "
    "checkpoints in the same transaction as its records, which is what restore reads to detect a "
    "truncated archive; the transaction and commit paths are exercised against live PostgreSQL; "
    "Clear's error return is handled at its call sites; and the empty-batch short circuit is covered "
    "by TestExportingNoRecordsTouchesNothing and TestAnEmptyBatchIsNotOpenedAsATransaction rather "
    "than being unobservable. The audit truncation anchor also has a mutation gate, "
    "scripts/mutation_check_anchor.py, which makes the sink store records without checkpointing "
    "them and requires the five sink checkpoint tests to notice, crediting a detection only on a "
    "--- FAIL line rather than a non-zero exit. That gate exists because the previous fix's tests "
    "all inserted their own checkpoint, so a test that supplied the thing whose absence it existed "
    "to detect could not detect that absence."
    " || "
    "REMAINING, in severity order. The backlog in front of the sink is in-memory, so accepted but "
    "unexported records do not survive process death and AC4's durable-buffering claim is "
    "unearned; closing it needs a write-ahead log and is a design decision. Independent immutable "
    "retention is unimplemented: one sink is constructed where docs/22 section 4 requires two "
    "independent copies. The checkpoint signer is in-process and ephemeral, so checkpoints from a "
    "previous process cannot be verified against a restarted process's ring; harmless while the "
    "restore compares sequence and hash, but it means the signature is currently decorative. A "
    "driver error during Commit is unsimulated, and a commit whose outcome the caller cannot "
    "determine is a distinct hazard from a clean commit. Clear latches on the first cause, so a "
    "SEV-1 integrity failure arriving after a backlog halt is never surfaced; unreachable only "
    "because ObserveVerification has no production caller. WI-141 remains IN_PROGRESS."
)


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")
    data = json.loads(original)

    items = data["items"]
    matches = [i for i in items if i.get("id") == "WI-117"]
    if len(matches) != 1:
        print(f"SETUP FAILED: expected exactly one WI-117, found {len(matches)}")
        return 1
    item = matches[0]

    if item.get("blocker") == NEW_BLOCKER:
        print("unchanged: WI-117 blocker already carries the correction")
        return 0
    if item.get("partial_results") == NEW_PARTIAL_RESULTS:
        print("unchanged: WI-117 partial_results already carries the correction")
        return 0

    before_blocker = item.get("blocker", "")
    before_partial = item.get("partial_results", "")
    item["blocker"] = NEW_BLOCKER
    item["partial_results"] = NEW_PARTIAL_RESULTS

    # The file is UTF-8, no BOM, LF line endings, two-space indent, and non-ASCII characters stored
    # literally rather than as \u escapes. Every one of those is reproduced here explicitly, because
    # a round-trip that silently flips any of them would corrupt content this update is not even
    # meant to touch.
    TARGET.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    # Re-read and confirm the update landed and the rest of the document is intact.
    after = json.loads(TARGET.read_text(encoding="utf-8"))
    written = [i for i in after["items"] if i.get("id") == "WI-117"][0]
    if written["blocker"] != NEW_BLOCKER or written["partial_results"] != NEW_PARTIAL_RESULTS:
        print("VERIFY FAILED: the fields did not round-trip through the file")
        return 1

    untouched = [
        i["id"]
        for i in after["items"]
        if i.get("id") != "WI-117"
        and json.dumps(i, sort_keys=True) != json.dumps(
            [x for x in items if x.get("id") == i.get("id")][0], sort_keys=True
        )
    ]
    if untouched:
        print(f"VERIFY FAILED: these unrelated items changed: {untouched}")
        return 1

    non_ascii_after = sum(1 for c in TARGET.read_text(encoding="utf-8") if ord(c) > 127)
    print(f"  updated WI-117 blocker ({len(before_blocker)} -> {len(written['blocker'])} chars)")
    print(f"  updated WI-117 partial_results "
          f"({len(before_partial)} -> {len(written['partial_results'])} chars)")
    print(f"  every other work item byte-identical: {not untouched}")
    print(f"  non-ASCII characters preserved: {non_ascii_after}")
    print(f"  item count unchanged: {len(after['items'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
