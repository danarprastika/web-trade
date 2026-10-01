"""One-off: append EV-045 recording the WI-117 audit sink and the guard's dead-end fix.

EV-044 recorded that the guard's backlog had exactly one decrement path and no producer, and
reopened WI-117. This record implements the producer, fixes the escape hatch that reported
success while doing nothing, and - the larger part of the work - corrects the verification
itself, which was overstating its coverage in two separate ways.

Idempotent, append-only, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-045"
STAMP = "2026-09-30T11:20:00Z"

WORK_ITEM = "WI-117"
RELATED = "WI-141"

CLAIM = (
    "The audit backlog now has a producer and the operator's escape hatch works. Exporter "
    "writes accepted records to a durable Sink and releases the guard's backlog only after "
    "the sink has committed, which is the ordering the whole control depends on and the one "
    "that was previously unfalsifiable because no producer existed. Guard.Clear now refuses "
    "while an evidence backlog is outstanding, because the earlier unconditional clear set "
    "halted to false with pending at its limit, so the next accepted record re-tripped the "
    "halt immediately: the operator resumed, was halted again, and could not record the fact "
    "that they had cleared. Separately, and accounting for most of the defects below, the "
    "mutation harness was overstating its own coverage and is now instrumented to say so."
)

METHOD = (
    "Implemented sink.go with a Sink port and a SQLSink over the generated AppendAuditRecord "
    "accessor, following the shape store_sql.go established for the model registry: a narrow "
    "querier rather than the whole generated interface, a caller-owned pool, no driver import, "
    "and a transaction per batch with the sink refusing to report success for a partially "
    "written batch. Added Exporter as the type that ties a Guard to a Sink. Before designing "
    "the fix I re-tested EV-044's own claim rather than building on it, by running the "
    "guard through fill-halt-clear-record and observing the outcome, and that is what turned "
    "up the sharper defect described below. Extended scripts/mutation_check_model.py from a "
    "single hardcoded package to a selected one, and in the course of doing so added the "
    "build-failure accounting it had never had. That accounting immediately changed the "
    "meaning of two prior evidence records."
)

RESULT = (
    "Sink has one method, Export, and no update, delete, or upsert - a sink that could modify "
    "or remove evidence would not be a sink. SQLSink writes a batch in one transaction and in "
    "the caller's order, because re-sorting would let the durable order and the chained order "
    "disagree, which is the comparison the integrity verifier exists to make. The hash arrays "
    "are copied rather than aliased, and the mapping from Record to the insert's parameters is "
    "written out field by field with a test comparing the two field sets by name, because a "
    "field added to Record and forgotten in the mapping would be written as a zero value and "
    "the database would accept it: every column in 0002 has either a default or only a NOT "
    "NULL check. Exporter.Export writes first and releases second, and the refusal path leaves "
    "the backlog deliberately untouched. Guard.Clear returns an error now, and refuses only "
    "for an EVIDENCE_BACKLOG halt with records outstanding - an integrity halt is a different "
    "decision, and an operator clearing a chain break must not additionally be told to fix an "
    "unrelated export backlog. 15 new audit tests, 83 in the package, 149 in model, race-clean, "
    "go vet clean, gofmt clean, all 13 gates PASS. Mutation harness: model 41 of 41 applied, "
    "41 detected, 0 survived, 0 skipped, 0 build failures; audit 10 of 10 applied, 10 detected, "
    "0 survived, 0 skipped; both restored byte-for-byte."
)

DEFECTS = (
    "Six defects, and the first three invalidate coverage that two prior evidence records "
    "claimed. First, and the most serious: adding build-failure accounting to the harness "
    "revealed that 4 of the 41 model mutations - M6, M20, M27 and M42 - were not detections at "
    "all. Each broke the build rather than failing a test, and the harness had been reporting "
    "them as detected because 'the tests did not pass' and 'a test failed' are the same "
    "predicate. EV-042 and EV-043 both recorded '41 of 41 detected', and 4 of those 41 had "
    "never executed a test. The build-failure count is now reported separately and is fatal on "
    "its own. Second, once those four were rewritten to compile, one of them - M27, 'a rejected "
    "request still writes an audit record' - SURVIVED. The claim was written in the journal's "
    "comments and in an evidence record and no test enforced it, because the only mutation that "
    "would have caught it had never run. I added TestARefusedRequestWritesNoAuditRecord, which "
    "now catches it. Third, M27 then still survived after that, for a reason worth recording: "
    "the mutation injected a record whose Partition came from rec.Owner, and rec is the zero "
    "Record on that branch because it was just established to be absent, so the chain refused "
    "the injected record on validation. The mutation changed nothing at all, and a mutation that "
    "changes nothing cannot refute anything - it looks like a gap in the code when the gap is "
    "in the mutation. Fourth, in the audit set, A6 tested a property that could not fail. It "
    "claimed the sink aliases the record's hash if the explicit copies in paramsFor are "
    "removed, but paramsFor takes its Record by value, so the language already copies both "
    "fixed-size arrays before any []byte conversion runs. A6 survived correctly, for the wrong "
    "reason. Replaced with A11, which reverses the batch write order and is a real property, "
    "and replaced the test with one that pins the by-value signature directly. Fifth, the "
    "earlier version of that test was worse than the mutation: it asserted the sink copies the "
    "hashes, and widening it to cover both hashes still could not have failed, because the "
    "guarantee is the language's, not the code's. Sixth, Clear's new return value is discarded "
    "by the two pre-existing call sites in guard_test.go, which compiles because Go permits "
    "discarding a return value. TestGuardLatchRequiresAnExplicitClear happens to drain the "
    "backlog before clearing, so it still passes and now covers the correct sequence, but the "
    "discarding is left as-is rather than rewritten, because the alternative is editing tests "
    "outside this change to tidy a lint that Go does not have."
)

SIGNIFICANCE = (
    "The general form is that a verification tool's own output needs to be audited with the "
    "same scepticism as the code it verifies, and that the cheapest scepticism is "
    "distinguishing 'the test failed' from 'the build broke'. Two of them are different "
    "claims. A build break satisfies the first predicate and exercises none of the tests, so a "
    "harness that treats them alike reports coverage of properties it never touched - and it "
    "will do so with a clean summary line, because '41 of 41 detected' is exactly what a "
    "reader scans for. The four mutations this uncovered had been in the harness for several "
    "evidence records, and two of them had been the subject of a written account of fixing a "
    "build-failure-as-detection that did not in fact resolve it. The second general form is "
    "about dead ends. A counter whose only decrement path has no producer is not a control that "
    "is untested; it is a control that cannot be exercised, and its behaviour under load is "
    "not a hypothetical - it is the only behaviour it has. The second half of that is the "
    "escape hatch. An operator who clears a halt, resumes, and is halted again has been told "
    "something false by the control, and cannot write down what happened because the recording "
    "path is the thing that refuses. Refusing the clear, with a message naming the actual "
    "precondition, is strictly more useful than clearing and failing."
)

CAVEATS = (
    "Six limitations. First, and most important: nothing constructs an Exporter. The sink, "
    "the exporter and the guard now compose correctly and are proven against fakes, but there "
    "is still no production code that wires them together, so the backlog is still not drained "
    "by anything at runtime. What this record closes is the structural blocker EV-044 "
    "identified - the missing producer and the ineffective escape hatch - and not the wiring, "
    "which belongs to the composition root and therefore to WI-164 and WI-165. Second, the "
    "SQLSink is proven only against a fake querier. Its BeginTx, its commit, and a driver error "
    "arriving mid-commit are untested, for the same reason as EV-042 and EV-043: no Go database "
    "driver satisfies scripts/verify_toolchain.py, because every pgx v5 release from v5.0.0 to "
    "v5.11.0 requires an untagged pgservicefile and there is no waiver mechanism. The "
    "statements themselves are proven - by db-0002-audit's 20 database assertions against real "
    "PostgreSQL - and the generated accessors are proven to match the schema by sqlc vet, but "
    "no Go process has ever connected to a database and called these methods. Third, Export's "
    "empty-batch short circuit is not mutation-covered, because with a caller-owned "
    "transaction it is unobservable: the write loop is simply not entered. With a real pool it "
    "would avoid opening a transaction for nothing, and there is no way to test that here. "
    "Fourth, the sink is one destination. docs/22 section 4 requires independent immutable "
    "retention, and one PostgreSQL table written by the same process is not independent of that "
    "process; a second sink is a deployment concern the Sink interface now permits but nothing "
    "configures. Fifth, Sink writes records and nothing else: it does not write checkpoints, so "
    "the signed-checkpoint half of the chain is still in memory, and a reader restoring from "
    "the sink alone would get a chain with no signed closure over it. Sixth, Clear's new error "
    "return is ignored at its two existing call sites, as described in the defects. Also "
    "unchanged: the mutation harness remains a verification activity rather than a release "
    "gate, consistent with EV-032, EV-034, EV-037, EV-039, EV-040, EV-041, EV-042, EV-043 and "
    "EV-044; and EV-044's claim that recovery is possible 'only through a manual privileged "
    "Clear' is corrected by this record, because a clear alone does not recover - it needs a "
    "drain that previously had no producer. No specification file was modified, docs/ remains "
    "clean, nothing was staged, and nothing was committed."
)

ARTIFACTS = [
    "services/control-plane/audit/sink.go",
    "services/control-plane/audit/sink_test.go",
    "services/control-plane/audit/guard.go",
    "services/control-plane/model/journal_test.go",
    "scripts/mutation_check_model.py",
    "scripts/record_ev045.py",
]

RECORD = {
    "schema": "ecc.project-brain/evidence/v7",
    "evidence_id": EVIDENCE_ID,
    "recorded_at": STAMP,
    "recorded_by": "team-lead",
    "work_item": WORK_ITEM,
    "claim": CLAIM,
    "status": "VERIFIED",
    "method": METHOD,
    "result": RESULT,
    "defect_found_and_fixed": DEFECTS,
    "significance": SIGNIFICANCE,
    "caveats": CAVEATS,
    "exception": "",
    "artifacts": ARTIFACTS,
    "supersedes": [],
}

EVENT = {
    "schema": "ecc.project-brain/event/v7",
    "event_id": "EVT-WI-117-AUDIT-SINK-IMPLEMENTED",
    "recorded_at": STAMP,
    "recorded_by": "team-lead",
    "work_item": WORK_ITEM,
    "event": "work_item_implemented",
    "status": "RECORDED",
    "evidence_ref": EVIDENCE_ID,
    "summary": (
        "The audit backlog now has a producer: Exporter writes accepted records to a durable "
        "Sink and releases the guard's backlog only after the sink commits, which is the "
        "ordering the control depends on and was previously unfalsifiable. Guard.Clear now "
        "refuses while an evidence backlog is outstanding, because the earlier unconditional "
        "clear set halted to false with pending at its limit and the next accepted record "
        "re-tripped the halt - the operator resumed, was halted again, and could not record "
        "that they had cleared. It refuses only for an EVIDENCE_BACKLOG halt, not an "
        "integrity halt, because those are different decisions. Sink has no update, delete or "
        "upsert; SQLSink writes each batch in one transaction in the caller's order and refuses "
        "to report success for a partial batch; the Record-to-columns mapping is checked by a "
        "test comparing both field sets by name. 15 new audit tests, 83 in the package, 149 in "
        "model, race clean, all 13 gates PASS. Model mutations 41 of 41 applied and detected; "
        "audit 10 of 10; both restored byte-for-byte. THE LARGER PART OF THIS WORK IS A "
        "CORRECTION TO MY OWN VERIFICATION. Adding build-failure accounting to the harness "
        "revealed that 4 of the 41 model mutations - M6, M20, M27, M42 - were not detections "
        "at all: each broke the build, and the harness had been reporting them as detected "
        "because 'the tests did not pass' and 'a test failed' are the same predicate. EV-042 "
        "and EV-043 both recorded '41 of 41 detected' and 4 of those never executed a test. "
        "Build failures are now counted separately and are fatal on their own. Once those four "
        "were rewritten to compile, M27 survived - the claim 'a refusal is not a state change' "
        "was written in the comments and in an evidence record and no test enforced it. Added "
        "TestARefusedRequestWritesNoAuditRecord. M27 then still survived, because it injected a "
        "record whose Partition came from rec.Owner and rec is the zero Record on that branch, "
        "so the chain refused it: the mutation changed nothing, and a mutation that changes "
        "nothing cannot refute anything. In the audit set A6 tested a property that could not "
        "fail, because paramsFor takes its Record by value and the language already copies the "
        "hash arrays; replaced with A11, which reverses the batch write order, and with a test "
        "that pins the by-value signature. NOT DONE: nothing constructs an Exporter, so the "
        "backlog is still not drained at runtime - this closes the structural blocker, not the "
        "wiring, which belongs to WI-164 and WI-165. SQLSink is proven only against a fake "
        "querier: BeginTx, commit, and a mid-commit driver error are untested because no driver "
        "satisfies the pinning gate. The sink writes records but not checkpoints, so a reader "
        "restoring from it would get a chain with no signed closure. One sink is not "
        "independent immutable retention. Export's empty-batch short circuit is not "
        "mutation-covered because it is unobservable with a caller-owned transaction. This "
        "record also corrects EV-044: a clear alone does not recover, it needs a drain that "
        "previously had no producer. WI-117 stays IN_PROGRESS pending the wiring."
    ),
}


def append_jsonl(path: Path, record: dict) -> None:
    with io.open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=True) + "\n")


PARTIAL_RESULTS = (
    "Chain: per-partition hash chain, sequence and previous-hash assignment, batch atomicity, "
    "duplicate-delivery idempotence, and conflict detection on reused identities, all "
    "verified. Retention and deletion: every precondition checked independently, with "
    "two-person approval and self-approval refused, verified. Checkpoints: signed over a "
    "range, refusing a hole, a wrong count, and a chain that does not resume from its "
    "checkpoint, verified. Integrity verification: tamper, deletion, reorder, replay, "
    "signature failure, and restore detection all pass, and every finding is SEV-1. AC4 is "
    "now partially implemented rather than absent: a Sink port with a SQL-backed "
    "implementation over the generated AppendAuditRecord accessor, an Exporter that gives the "
    "guard's backlog a producer, and a Clear that refuses while evidence is unexported instead "
    "of appearing to succeed. 83 audit tests, 15 of them new, race-clean; 41 of 41 model "
    "mutations and 10 of 10 audit mutations applied and detected with byte-for-byte restore; "
    "all 13 gates PASS. Defects found and fixed: 4 of 41 model mutations were build failures "
    "that the harness had been counting as detections, so two prior evidence records overstated "
    "their coverage; the one claim among them - that a refusal is not a state change - was "
    "enforced by no test until TestARefusedRequestWritesNoAuditRecord was added; that mutation "
    "was itself a no-op because it drew the partition from the zero Record on the branch it "
    "injected into; an audit mutation tested a property that could not fail because the "
    "language already provides the copy it claimed the code was making; and the hash-copy test "
    "asserted a property the language guarantees rather than the code. REMAINING, in severity "
    "order: nothing constructs an Exporter, so the backlog is still not drained at runtime and "
    "this work closes the structural blocker rather than the wiring, which belongs to the "
    "composition root in WI-164 and WI-165; SQLSink's BeginTx, commit, and mid-commit driver "
    "errors are untested against a fake querier because no Go database driver satisfies the "
    "pinning gate - every pgx v5 release requires an untagged pgservicefile and no waiver "
    "mechanism exists; the sink writes records but not checkpoints, so a restore from the sink "
    "alone yields a chain with no signed closure over it; a single sink is not the independent "
    "immutable retention docs/22 section 4 requires, though the interface now permits a "
    "second; Export's empty-batch short circuit is unobservable and therefore not "
    "mutation-covered; and Clear's new error return is discarded at its two existing call "
    "sites, which compiles because Go permits discarding a return value. WI-141 remains "
    "IN_PROGRESS: its rehydration blocker is owned by WI-117 and its own acceptance criteria "
    "say nothing about restart or recovery."
)


def main() -> int:
    evidence_path = BRAIN / "evidence.jsonl"
    existing = [
        json.loads(line)
        for line in io.open(evidence_path, encoding="utf-8").read().splitlines()
        if line.strip()
    ]
    if any(r.get("evidence_id") == EVIDENCE_ID for r in existing):
        print(f"{EVIDENCE_ID} already recorded; nothing appended.")
    else:
        append_jsonl(evidence_path, RECORD)
        print(f"appended {EVIDENCE_ID}")

    work_path = BRAIN / "work-items.json"
    doc = json.loads(io.open(work_path, encoding="utf-8").read())
    changed = False
    for item in doc["items"]:
        if item["id"] != WORK_ITEM:
            continue
        refs = item.get("evidence_ref", [])
        if EVIDENCE_ID not in refs:
            item["evidence_ref"] = [*refs, EVIDENCE_ID]
            changed = True
        if not item.get("partial_results"):
            item["partial_results"] = PARTIAL_RESULTS
            changed = True
        blocker = item.get("blocker", "") or ""
        note = (
            " EV-045 implements the sink, the exporter, and a backlog-aware Clear, so the "
            "structural blocker recorded by EV-044 is closed. It remains IN_PROGRESS because "
            "nothing constructs an Exporter: the composition root does not exist yet and "
            "belongs to WI-164 and WI-165, and because SQLSink's transaction, commit, and "
            "mid-commit driver-error paths are still unproven against a live database for the "
            "pinned-driver reason already recorded."
        )
        if "EV-045 implements the sink" not in blocker:
            item["blocker"] = (blocker + note).strip()
            changed = True
    if changed:
        io.open(work_path, "w", encoding="utf-8", newline="\n").write(
            json.dumps(doc, indent=2, ensure_ascii=True) + "\n"
        )
        print(f"{WORK_ITEM} updated")
    else:
        print("work item already up to date")

    events_path = BRAIN / "events.jsonl"
    seen = [
        json.loads(line)
        for line in io.open(events_path, encoding="utf-8").read().splitlines()
        if line.strip()
    ]
    if any(e.get("event_id") == EVENT["event_id"] for e in seen):
        print(f"{EVENT['event_id']} already recorded; nothing appended.")
    else:
        append_jsonl(events_path, EVENT)
        print(f"appended {EVENT['event_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
