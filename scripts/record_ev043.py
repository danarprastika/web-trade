"""One-off: append EV-043 recording the WI-141 durable workload-identity wiring.

Closes the third caveat of EV-042, which it named as "the largest gap left in the work
item": WorkloadRegistry was still entirely in-memory, so the containment widening that
EV-040 introduced and that is the point of the compromise response was invisible across a
restart. An identity revoked in the database was still live in the only place authentication
actually consults.

Idempotent, append-only, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-043"
STAMP = "2026-09-30T07:10:00Z"

WORK_ITEM = "WI-141"

CLAIM = (
    "Workload identity issuance and revocation now persist durably before the in-memory "
    "state changes, and a refused durable write changes nothing at all. The store is a "
    "narrow two-method port with no read and no delete, because the direction that matters "
    "for a revocation is that evidence survives: the issued row is retained after the "
    "identity is revoked so an operator disputing the revocation can find the subject. "
    "This is what makes the containment claims of EV-040 checkable across a restart of the "
    "write path - previously the only proof that a revocation happened was the mutation of "
    "a Go map."
)

METHOD = (
    "Declared IdentityStore in identity_store.go with InsertIdentity and InsertRevocation "
    "and nothing else, mirroring the shape store.go established for the model registry: the "
    "port is the smallest set of operations the caller needs, so an adapter cannot be handed "
    "a query the schema's guards do not cover. Added a compile-time assertion that "
    "SQLIdentityStore satisfies dbgen.Querier, which is what keeps the narrow port and the "
    "nineteen generated queries from drifting apart unnoticed. Wired it through MintContext "
    "and RevokeContext rather than through the non-Context Mint and Revoke, so the durable "
    "write is cancellable and the existing Context-free signatures keep their nineteen "
    "callers. Wrote thirteen tests, of which the ones that matter assert a property by "
    "breaking it: that a refused store issues nothing, that a refused revocation leaves the "
    "identity live, and that the durable record still contains the identity after revocation. "
    "Added M39 to M42 to the mutation harness. The harness then found real defects twice, "
    "once in a test and once in itself, and is the reason the restore path was hardened."
)

RESULT = (
    "identity_store.go defines IdentityStore, MemoryIdentityStore with failure injection and "
    "inspection helpers, and SQLIdentityStore over a narrow generated-query interface, plus "
    "the compile-time compatibility assertion against dbgen.Querier. The store has no read "
    "and no delete, and the port comment says why: issued rows are kept rather than replaced "
    "on revoke, so a revoked identity remains a reviewable fact. Mint persists the identity "
    "before adding it to the live map and Revoke persists the revocation before recording it "
    "locally, so a store that refuses issues or changes nothing and a retry after the "
    "underlying fault clears succeeds. The in-memory map and the durable row are no longer "
    "allowed to disagree in the direction that leaves a revoked credential authenticating. "
    "148 model tests, up from 135, race-detector clean, go vet clean, gofmt clean, all 13 "
    "gates PASS with 45 database assertions and a clean-catalog down/up rehearsal. The "
    "mutation harness is 41 of 41 applied, 41 detected, 0 survived, 0 skipped, byte-for-byte "
    "restored."
)

DEFECTS = (
    "Four defects, two found by the mutation harness and two by running the tool, and the "
    "second pair is the more serious because one of them left the working tree holding an "
    "injected bug. First, M42 initially passed as 'detected' with no FAIL line printed, "
    "because the replacement text referred to a name that does not exist at that scope; the "
    "package failed to compile and the harness scored a build break as a detection. This is "
    "the same trap recorded in EV-042 for M36, unchanged and therefore worth restating: the "
    "summary line cannot distinguish a test that failed from a package that would not build, "
    "and only the printed FAIL line separates them. The mutation was rewritten to compile. "
    "Second, and worse, the harness's own restore path did a single write per file and let "
    "the error propagate. On Windows a transient sharing violation surfaces as OSError errno "
    "22, which happens for uninteresting reasons - a go process from the run that just "
    "finished still had the file mapped - and when it happened the finally block failed the "
    "same way, so the tree was left holding mutation 24. The next baseline check failed for a "
    "reason that had nothing to do with the work in progress, and the injected defect would "
    "have been discovered by whoever ran the suite next, as an unexplained failure. The fix "
    "is a retrying restore that raises on exhaustion and reports the filenames it could not "
    "restore instead of letting the exception escape a finally block. Third, I caused the "
    "lock myself: a diagnostic piped the harness through Select-Object -Last, which closes the "
    "pipeline and kills the upstream process before its restore runs, reproducing the same "
    "left-mutated outcome deliberately. The lesson is that any pipe which terminates early "
    "turns this harness from a verifier into a corrupter. Fourth, auditing the id sequence "
    "while writing this record found M13 missing, with no comment explaining the gap and no "
    "duplicate anywhere in the sequence. The reason is genuinely not known and has been "
    "written down as not known rather than reconstructed; the gap was left in place because "
    "renumbering would silently repoint every id after the hole, and EV-042 and its "
    "predecessors cite these ids."
)

SIGNIFICANCE = (
    "Two general forms. The first is that a control whose only record is process memory has "
    "no memory across its own restart, and the process is the thing that restarts. Every "
    "revocation and every containment widening in this work item had been proven by mutating "
    "a map and reading it back in the same process, which is a real test of a map and not a "
    "test of the control. EV-040's widening - contain every workload serving the same exact "
    "model version - is the single most safety-critical behaviour in the compromise response, "
    "and it was composed entirely of writes that a restart erases. The second form is the "
    "one the harness defects illustrate, and it is the more transferable: a verification tool "
    "that mutates the tree is itself a writer, so it needs the same failure semantics the "
    "code under test needs. A restore that gives up on a transient error does not merely lose "
    "a test result; it converts the verifier into an undetected source of defects, which is "
    "strictly worse than having no verifier, because the record it produces claims coverage "
    "that the tree no longer has. The general rule is that a tool which restores state on "
    "exit must fail loudly when it cannot, and must not be driven through a pipeline that can "
    "kill it before it runs its restore."
)

CAVEATS = (
    "Five limitations, and the first is severe enough that the durability claim has to be "
    "read narrowly, for the same reason and by the same mechanism as EV-042's. First, and most "
    "important: IdentityStore is write-only. WorkloadRegistry still reconstructs nothing on "
    "startup, so after a restart it authenticates against an empty live set and will refuse "
    "identities that the database records as validly issued. That direction is safe - it "
    "fails closed, and a registry that cannot verify a credential will not honour one - but "
    "it means the durable revocation is currently a forensic record and not a control that "
    "takes effect across a restart. The concrete residual risk is unchanged from EV-040: a "
    "compromised model version whose revocations are durable but whose live set is rebuilt "
    "from memory is contained only until the process that observed the compromise exits. "
    "Rehydration is blocked for a concrete reason rather than deferred: like the model "
    "registry, the audit chain is in-memory, so restoring revocations without the chain would "
    "reissue sequence numbers that persisted records already occupy. Second, the audit append "
    "and the durable identity write are still not in one transaction, so a refused durable "
    "write leaves a SUCCEEDED audit record describing a revocation that did not take effect. "
    "The in-memory mutation is correctly refused, so no credential is affected, but the trail "
    "over-reports by one record. Third, no integration test runs this Go code against a live "
    "PostgreSQL, for the same driver reason as EV-042: every pgx v5 release from v5.0.0 to "
    "v5.11.0 requires an untagged pgservicefile, so scripts/verify_toolchain.py cannot be "
    "satisfied with any of them, and there is no waiver mechanism. SQLIdentityStore is proven "
    "against a fake querier, so the real transaction, commit, and mid-commit driver-error "
    "paths are untested. What is verified is that the statements are accepted by real "
    "PostgreSQL through EV-041's 45 assertions, that the generated accessors compile and match "
    "the schema through sqlc vet, and that the ordering and refusal behaviour hold against a "
    "store that can fail. Fourth, Mint and Revoke still default to context.Background() for "
    "the existing callers, so a caller holding a context and using those will not cancel its "
    "durable write; the Context variants exist and are what this record's tests exercise. "
    "Fifth, and unchanged from earlier records: Authenticate performs no cryptographic "
    "verification, so an identity is trusted on the strength of a name; Contain does not "
    "itself perform the model's lifecycle quarantine, so the four compromise actions are each "
    "verified but their atomicity is neither implemented nor verified; containment quarantines "
    "only the artifacts named in the declaration rather than every artifact of the affected "
    "version; and workload_revocations.evidence_ref remains free text rather than a foreign "
    "key to a forensic store. Also unchanged: the mutation harness remains a verification "
    "activity rather than a release gate, consistent with EV-032, EV-034, EV-037, EV-039, "
    "EV-040, EV-041 and EV-042. No specification file was modified, docs/ remains clean, "
    "nothing was staged, and nothing was committed."
)

ARTIFACTS = [
    "services/control-plane/model/identity_store.go",
    "services/control-plane/model/identity_store_test.go",
    "services/control-plane/model/identity.go",
    "scripts/mutation_check_model.py",
    "scripts/record_ev043.py",
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
    "event_id": "EVT-WI-141-WORKLOAD-IDENTITY-PERSISTENCE",
    "recorded_at": STAMP,
    "recorded_by": "team-lead",
    "work_item": WORK_ITEM,
    "event": "work_item_implemented",
    "status": "RECORDED",
    "evidence_ref": EVIDENCE_ID,
    "summary": (
        "Workload identity issuance and revocation now persist durably before the in-memory "
        "state changes, so a refused store issues or changes nothing and a retry after the "
        "fault clears succeeds. The store is a two-method port with no read and no delete, "
        "mirroring store.go, and issued rows are retained after revocation so a disputed "
        "revocation still has a reviewable subject; a compile-time assertion keeps the port "
        "and the nineteen generated queries from drifting. Wired through MintContext and "
        "RevokeContext so the durable write is cancellable without breaking existing "
        "callers. 148 model tests, up from 135, race clean, 41 of 41 mutations detected with "
        "byte-for-byte restore, all 13 gates PASS. Two of the four defects here are in the "
        "harness itself and the second is the serious one: its restore path did a single "
        "write per file, and a transient Windows sharing violation - reported as OSError "
        "errno 22 - left the tree holding mutation 24, so the next baseline failed for a "
        "reason unrelated to the work in progress and the injected defect would have been "
        "found by whoever ran the suite next, as an unexplained failure. The restore is now "
        "retrying and reports by filename when it cannot restore. I caused the same outcome "
        "once deliberately by piping the harness into Select-Object -Last, which kills the "
        "process before its restore runs. The general form is that a tool which mutates the "
        "tree is itself a writer and needs the same failure semantics as the code under "
        "test; a restore that gives up converts the verifier into an undetected source of "
        "defects while still claiming coverage. Also: M13 is missing from the mutation id "
        "sequence with no recorded reason, the gap is left rather than renumbered so earlier "
        "evidence keeps pointing at the mutations it was written about, and M42 first passed "
        "as detected only by a compile failure with no FAIL line - the same trap as EV-042's "
        "M36. NOT DONE, and the most severe limitation: IdentityStore is write-only, so a "
        "restarted registry authenticates against an empty live set. That fails closed and is "
        "safe, but it means the durable revocation is a forensic record rather than a control "
        "that takes effect across a restart, so EV-040's containment widening is still lost "
        "with the process that observed the compromise. Rehydration is blocked, not deferred: "
        "the audit chain is in-memory and would reissue sequence numbers that persisted "
        "records already occupy. There is still no cross-store transaction, so a refused "
        "durable write leaves a SUCCEEDED audit record for a revocation that did not happen. "
        "No Go-to-PostgreSQL integration test exists because no driver satisfies the pinning "
        "gate, so the real transaction and commit paths are untested against a fake querier. "
        "WI-141 stays IN_PROGRESS; gate verdict FAIL."
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
    "that carries reason and evidence into the refusal and blocks re-minting, and with both "
    "issuance and revocation persisted durably before the in-memory state changes. "
    "Persistence: 0004_model_registry.sql provides a durable registry, workload identity, "
    "revocation, and idempotency store whose constraints are proven against a real "
    "PostgreSQL 17 with 45 assertions; 19 sqlc queries preserve the audit-causation and "
    "blast-radius-from-recorded-revocations properties in SQL; the journal's writes go "
    "through a two-method Store port with a SQL-backed implementation over the generated "
    "accessors, so the audit-before-state ordering, the atomicity of the two-statement "
    "transition, and a refused write leaving in-memory state untouched are each proven "
    "against a store that can fail; and WorkloadRegistry's issuance and revocation go through "
    "a two-method IdentityStore that has no read and no delete, with issued rows deliberately "
    "retained after revocation so a disputed revocation still has a reviewable subject. "
    "148 model tests race-clean, 109 research tests, 41 of 41 mutations detected with "
    "byte-for-byte restore, all 13 gates PASS. Defects found and fixed: registration was "
    "outside the declared transition set; VerifyDeclaration's rules were structurally "
    "untestable; the quarantine-exit check was narrower than its own comment; the reported "
    "containment population was a function of when the record was written rather than of "
    "what had happened; Contain accepted a caller boolean asserting revocation had happened; "
    "the mutation harness applied mutations cumulatively and could not attribute its own "
    "verdicts; a verification script reported ALL 0 ASSERTIONS PASSED while asserting "
    "nothing, and now treats a zero total as a hard failure; the 0004 migration was missing "
    "its migrate:down marker and its COMMIT; the idempotency trigger guarded UPDATE but not "
    "DELETE, making a prunable ledger that would let a retried request transition twice; the "
    "audit-linkage test checked only transition rows and never the registration row; two "
    "mutations were 'detected' only by a compile failure with no test having run, which the "
    "harness summary reports identically to a real detection; and the harness's own restore "
    "path did a single write per file, so a transient Windows sharing violation left the "
    "working tree holding an injected mutation - the restore now retries and reports by "
    "filename, because a verifier that mutates the tree is a writer and needs the same "
    "failure semantics as the code it verifies. Also found: the mutation id sequence is "
    "missing M13 with no recorded reason, left in place rather than renumbered because "
    "earlier evidence cites these ids. REMAINING, in severity order: IdentityStore is "
    "WRITE-ONLY, so a restarted WorkloadRegistry authenticates against an empty live set and "
    "refuses identities the database records as validly issued - safe, because it fails "
    "closed, but it means a durable revocation is a forensic record rather than a control that "
    "takes effect across a restart, and EV-040's containment widening is still lost with the "
    "process that observed the compromise; rehydration is blocked rather than deferred because "
    "the audit chain is in-memory and would reissue sequence numbers that persisted records "
    "already occupy; there is no cross-store transaction for either the model or the identity "
    "path, so a refused durable write leaves a SUCCEEDED audit record describing a change that "
    "did not take effect; no integration test runs this Go code against a live PostgreSQL "
    "because no driver satisfies the pinning gate - every pgx v5 release requires an untagged "
    "pgservicefile and no waiver mechanism exists - so SQLIdentityStore's transaction, commit, "
    "and mid-commit driver-error paths are untested against a fake querier; Mint and Revoke "
    "still default to context.Background() for the existing callers; Authenticate performs no "
    "cryptographic verification; Contain does not itself perform the model's lifecycle "
    "quarantine, so the four compromise actions are each verified but their atomicity is "
    "neither verified nor implemented; containment quarantines only the artifacts named in the "
    "declaration rather than every artifact of the affected version; and "
    "workload_revocations.evidence_ref is free text rather than a foreign key to a forensic "
    "store. Gate verdict FAIL; work item remains IN_PROGRESS."
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
