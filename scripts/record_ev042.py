"""One-off: append EV-042 recording the WI-141 durable store wiring.

Closes the second-largest caveat carried by EV-041: the schema and the generated queries
existed and were proven, but the Go journal still kept its registries in memory and never
called them, so the two layers had been verified separately and never together.

Idempotent, append-only, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-042"
STAMP = "2026-09-30T03:40:00Z"

WORK_ITEM = "WI-141"

CLAIM = (
    "The model journal's writes now go through a store port, and the SQL-backed "
    "implementation of that port writes to the 0004 schema through the generated "
    "accessors. This is what makes the ordering claim falsifiable: until a store that can "
    "fail sat behind the journal, 'the state is written only after the audit chain accepts "
    "the record describing it' was true by construction, because a map cannot fail. The "
    "three properties this adds - ordering, atomicity of the two-statement transition, and "
    "a refused write leaving the in-memory state untouched - could not previously have been "
    "tested and are now each broken deliberately to prove they are enforced."
)

METHOD = (
    "Declared Store as a two-method port in services/control-plane/model/store.go rather "
    "than reaching for dbgen inside the journal, so the journal keeps depending on an "
    "interface it owns and a store cannot be handed a query the 0004 guards do not cover. "
    "Applied it by threading a persist closure through commit rather than by branching on "
    "which operation is happening, because commit is where the ordering guarantee lives and "
    "an ordering guarantee that is reimplemented per operation is two guarantees. Added "
    "RegisterContext and TransactContext alongside the existing Register and Transact so "
    "that a durable write, which is a network call, is cancellable without breaking the 19 "
    "existing callers. Wrote twelve tests, six of which assert a property by breaking it. "
    "Added M34 to M38 to scripts/mutation_check_model.py. Ran the harness, which found a "
    "hole in one of the new tests and a wrong anchor in another."
)

RESULT = (
    "store.go declares Store with InsertModel, ApplyTransition, and Close, and deliberately "
    "has no read, no delete, and no update-by-model-id; the missing read is a limitation "
    "recorded below rather than an oversight. ApplyTransition takes the state change and the "
    "idempotency entry as one call rather than two, because splitting them leaves a window "
    "in which a model has advanced with its transition unrecorded, and a retry would then be "
    "refused as stale with no way to distinguish 'already done' from 'half done'. "
    "store_sql.go implements the port over the generated accessors, taking a narrow "
    "SQLQuerier of three methods rather than the whole dbgen.Querier, and running "
    "ApplyTransition inside a transaction whose commit it owns; NewSQLStoreInTx is named "
    "separately because the difference is who owns the commit, and a mistake there means a "
    "store that silently never persists. It imports database/sql and the accessors and "
    "nothing else, so no driver dependency is introduced - which matters because every pgx "
    "release requires an untagged pgservicefile that cannot satisfy the pinning gate. "
    "commit now spans three stores in a fixed order: audit append, durable write, in-memory "
    "maps, and the in-memory update happens only after the durable write succeeds. The "
    "audit identifier is passed into the persist closure rather than recomputed inside it, "
    "because deriving it in two places is one refactor away from the two copies "
    "disagreeing. 135 model tests, up from 122, race-detector clean, go vet clean, gofmt "
    "clean, all 13 gates PASS. The mutation harness is now 37 of 37 applied, 37 detected, 0 "
    "survived, 0 skipped, byte-for-byte restored."
)

DEFECTS = (
    "Two defects in this work's own verification, both found by the mutation harness rather "
    "than by reading, which is the second time in this work item that has been the case. "
    "First, M36 survived. The test meant to guard the audit-identity linkage between the "
    "registry row and the audit chain checked only the transition rows and never the "
    "registration row, so substituting a wrong audit identity on the registration path left "
    "the suite green - which is exactly the defect the test was written to prevent, sitting "
    "inside the test written to prevent it. The fix was to walk every durable row rather "
    "than only the ones a transition produced. Second, the first version of M36 renamed the "
    "closure's parameter to _, which left the body referring to an undefined name; the "
    "package then failed to compile and the harness reported the mutation as 'detected' with "
    "no test having run. That is not detection, it is a build failure wearing detection's "
    "label, so the mutation was rewritten to substitute a different audit identity - which "
    "compiles, and which the strengthened test then caught. Worth noting that the harness "
    "reported both outcomes as 'detected' in its summary line; only the printed FAIL line "
    "distinguished a real detection from a compile failure, and a reader scanning the "
    "summary would have taken the compile failure for evidence. Separately, the new "
    "mutations were initially numbered M31 to M35, colliding with three existing mutations "
    "of those names, so 'M33' referred to two different defects in the same run."
)

SIGNIFICANCE = (
    "The general form is that a store which cannot fail proves nothing about ordering. "
    "Every guarantee this package had for eight evidence records was checked against maps, "
    "and maps cannot refuse a write - so the checks were real but shallow, in the precise "
    "sense that they could only ever be broken by deleting the code rather than by "
    "breaking the behaviour. The ordering guarantee in particular was unfalsifiable in the "
    "direction that mattered: there was no way to interpose a failure between the audit "
    "append and the state write, because there was nothing there to fail. Adding a failing "
    "dependency turned five comments into five failing tests, and the first two of those "
    "tests were themselves wrong - which is the ordinary outcome of writing a test for a "
    "property that has never needed one, and the reason the mutation harness is not a "
    "formality. The second general form is narrower and about the harness itself: 'detected' "
    "and 'test actually failed' are different claims, and a compile failure satisfies the "
    "first while satisfying none of the second. A harness that conflates them will report "
    "coverage of properties it never exercised, and the summary line is exactly where a "
    "reader looks."
)

CAVEATS = (
    "Six limitations, and the first is severe enough that the word 'durable' in this record "
    "has to be read narrowly. First, and most important: the store is write-only. Reads still "
    "come from the journal's maps, so a restarted journal does not read back what it wrote "
    "and will refuse every transition as an unregistered model. That direction is safe - it "
    "cannot promote a model it cannot verify - but it means the durable rows are currently a "
    "forensic record rather than a recovery source, and the 'a restart still loses the "
    "registry' caveat is reduced rather than closed. The reason is not deferred effort: the "
    "audit chain is still in-memory, so a restarted journal would allocate audit sequence "
    "numbers from an empty chain while the persisted records for the same partition already "
    "occupy 1..n, and the next append would collide with a record that exists. Loading from "
    "the store before the chain can be restored would make that collision more likely, not "
    "less. Second, the audit chain is therefore still in-memory and the cross-store "
    "transaction is still absent. The audit append happens first and the durable transaction "
    "second, with nothing spanning them, so a durable refusal leaves a SUCCEEDED audit record "
    "describing a transition that did not take effect. That is recorded honestly in commit's "
    "comment and is the honest failure direction - a trail that over-reports one failed "
    "transition is recoverable; a trail that under-reports a real one is not - but it is not "
    "the property a single transaction would give. Third, and the largest gap left in the "
    "work item: WorkloadRegistry is still entirely in-memory. The identities and revocations "
    "were not wired, so EV-040's containment widening is still invisible across a restart, "
    "which is the specific failure that gap was recorded against. This record closed the "
    "model-registry half of the in-memory problem and left the workload half untouched, and "
    "the workload half is the more safety-critical of the two. Fourth, no integration test "
    "runs this Go code against a live PostgreSQL, because there is no driver: every pgx "
    "release from v5.0.0 to v5.11.0 requires an untagged pgservicefile that has no tagged "
    "release at all, so the pinning gate cannot be satisfied with any of them. What is "
    "verified is that the statements are accepted by real PostgreSQL (45 database assertions "
    "from EV-041), that the generated accessors compile and match that schema (sqlc vet), "
    "and that the journal's ordering and atomicity hold against a failing store. The step "
    "that has never run is a Go process connecting to a database and calling these methods. "
    "Fifth, SQLStore is proven against a fake querier, so the transaction's rollback path, "
    "the isolation level, and the behaviour of a driver error mid-commit are untested. "
    "Sixth, Register and Transact still default to context.Background() for the 19 existing "
    "callers, so a caller that has a context and uses those will not cancel its durable "
    "write; the Context variants exist and the non-Context ones are the ones still in use "
    "throughout the existing tests. Also unchanged: the mutation harness remains a "
    "verification activity rather than a release gate, consistent with EV-032, EV-034, "
    "EV-037, EV-039, EV-040 and EV-041. No specification file was modified, docs/ remains "
    "clean, nothing was staged, and nothing was committed."
)

ARTIFACTS = [
    "services/control-plane/model/store.go",
    "services/control-plane/model/store_sql.go",
    "services/control-plane/model/store_test.go",
    "services/control-plane/model/journal.go",
    "scripts/mutation_check_model.py",
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
    "event_id": "EVT-WI-141-DURABLE-STORE-WIRING",
    "recorded_at": STAMP,
    "recorded_by": "team-lead",
    "work_item": WORK_ITEM,
    "event": "work_item_implemented",
    "status": "RECORDED",
    "evidence_ref": EVIDENCE_ID,
    "summary": (
        "The model journal's writes now go through a store port with a SQL-backed "
        "implementation over the 0004 schema, which is what makes the ordering guarantee "
        "falsifiable for the first time. Until a store that can fail sat behind the "
        "journal, 'the state is written only after the audit chain accepts the record' was "
        "true by construction, because a map cannot fail; now ordering, transition "
        "atomicity, and a refused write leaving state untouched are each broken "
        "deliberately to prove they are enforced. Store is two methods and deliberately has "
        "no read, no delete, and no update-by-id. ApplyTransition takes the state change and "
        "the idempotency entry as one call because splitting them leaves a window where a "
        "model has advanced with its transition unrecorded and a retry cannot tell 'already "
        "done' from 'half done'. store_sql.go runs it in a transaction whose commit it owns, "
        "takes a three-method querier rather than the whole generated interface, and imports "
        "no driver - which is what kept it clear of the untagged-pgservicefile blocker that "
        "makes every pgx release unpinnable. commit spans three stores in a fixed order and "
        "passes the audit identifier into the persist closure rather than recomputing it. "
        "135 model tests, up from 122, race clean, 37 of 37 mutations detected with "
        "byte-for-byte restore, all 13 gates PASS. Two defects found, both in the new "
        "verification: the audit-linkage test checked only transition rows and never the "
        "registration row, so a wrong audit identity on the registration path left the "
        "suite green; and the first version of that mutation was 'detected' only by a "
        "compile failure, with no test having run - the harness summary calls both "
        "'detected', and only the printed FAIL line separates a real detection from a build "
        "break. NOT DONE, and the most severe limitation here: the store is write-only. "
        "Reads still come from memory, so a restart refuses every transition as "
        "unregistered - safe, but forensic record rather than recovery source - and the "
        "reason is that the audit chain is still in-memory and would reissue sequence "
        "numbers that persisted records already occupy. There is also no cross-store "
        "transaction, so a durable refusal leaves a SUCCEEDED audit record for a transition "
        "that did not happen. WorkloadRegistry remains entirely in-memory, so EV-040's "
        "containment widening is still invisible across a restart - this record closed the "
        "model-registry half of that gap and left the more safety-critical workload half "
        "untouched. No Go-to-PostgreSQL integration test exists because no driver can "
        "satisfy the pinning gate. WI-141 stays IN_PROGRESS; gate verdict FAIL."
    ),
}


def append_jsonl(path: Path, record: dict) -> None:
    with io.open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=True) + "\n")


PARTIAL_RESULTS = (
    "AC1 registry/audit/idempotency verified: journal.go is the registry's only write path and "
    "writes the lifecycle state only after the audit chain accepts the record describing it. "
    "AC2 no model authorizes its own execution verified. AC3 tool permission-denial, model "
    "rollback, and lineage verified. AC4 all four compromise actions verified, with "
    "containment widening from the detected workload to every workload serving the same exact "
    "model version, and the reported blast radius derived from the revocations recorded "
    "rather than from the live set so it is stable across retries. Identity: short-lived "
    "workload identity bound to one exact model version, with immediate idempotent revocation "
    "that carries reason and evidence into the refusal and blocks re-minting. Persistence: "
    "0004_model_registry.sql provides a durable registry, workload identity, revocation, and "
    "idempotency store whose constraints are proven against a real PostgreSQL 17 with 45 "
    "assertions; 19 sqlc queries preserve the audit-causation and "
    "blast-radius-from-recorded-revocations properties in SQL; and the journal's writes now "
    "go through a two-method Store port with a SQL-backed implementation over the generated "
    "accessors, so the audit-before-state ordering, the atomicity of the two-statement "
    "transition, and a refused write leaving in-memory state untouched are each proven "
    "against a store that can fail. 135 model tests race-clean, 109 research tests, 37 of 37 "
    "mutations detected with byte-for-byte restore, all 13 gates PASS. Defects found and "
    "fixed: registration was outside the declared transition set; VerifyDeclaration's rules "
    "were structurally untestable so its empty-source guard could be deleted with the suite "
    "green; the quarantine-exit check was narrower than the comment stating it; the reported "
    "containment population was a function of when the record was written rather than of "
    "what had happened; Contain accepted a caller boolean asserting revocation had happened; "
    "the mutation harness applied mutations cumulatively and could not attribute its own "
    "verdicts; a verification script reported ALL 0 ASSERTIONS PASSED while asserting "
    "nothing, because one unhandled error rolled back the transaction and the summary counted "
    "an empty table - the harness now treats a zero total as a hard failure; the 0004 "
    "migration was missing its migrate:down marker and its COMMIT; and the idempotency "
    "trigger guarded UPDATE but not DELETE, making a prunable ledger that would let a "
    "retried request transition twice; the audit-linkage test for the durable store checked "
    "only transition rows and never the registration row, so a wrong audit identity on the "
    "registration path left the suite green; and one new mutation was 'detected' only by a "
    "compile failure with no test having run, which the harness summary reports identically "
    "to a real detection. REMAINING, in severity order: the store is WRITE-ONLY - reads "
    "still come from the journal's maps, so a restart refuses every transition as "
    "unregistered, which is safe but means the durable rows are a forensic record rather than "
    "a recovery source, and restoring from them is blocked rather than merely deferred because "
    "the audit chain is still in-memory and would reissue sequence numbers that persisted "
    "records already occupy; there is no cross-store transaction, so the in-memory audit "
    "append happens first and a durable refusal leaves a SUCCEEDED audit record describing a "
    "transition that did not take effect; WorkloadRegistry is still entirely in-memory, so "
    "EV-040's containment widening remains invisible across a restart and the more "
    "safety-critical half of the original in-memory gap is untouched; no integration test "
    "runs this Go code against a live PostgreSQL because no driver satisfies the pinning "
    "gate, and SQLStore's rollback path, isolation level, and mid-commit driver errors are "
    "untested against a fake querier; Register and Transact still default to "
    "context.Background() for the 19 existing callers; containment quarantines only the "
    "artifacts named in the declaration, not every artifact of the affected version; Contain "
    "does not itself perform the model's lifecycle quarantine, so the four actions are each "
    "verified but their atomicity is neither verified nor implemented; "
    "ContainedModelVersions does not say whether a version's artifacts are quarantined; "
    "Authenticate performs no cryptographic verification; and "
    "workload_revocations.evidence_ref is a free-text reference rather than a foreign key to "
    "a forensic store. Gate verdict FAIL; work item remains IN_PROGRESS."
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
        if item["id"] == WORK_ITEM:
            refs = item.get("evidence_ref", [])
            if EVIDENCE_ID not in refs:
                item["evidence_ref"] = [*refs, EVIDENCE_ID]
                item["partial_results"] = PARTIAL_RESULTS
                changed = True
    if changed:
        io.open(work_path, "w", encoding="utf-8", newline="\n").write(
            json.dumps(doc, indent=2, ensure_ascii=True) + "\n"
        )
        print(f"{WORK_ITEM} evidence and partial_results updated")
    else:
        print(f"{WORK_ITEM} already up to date")

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
