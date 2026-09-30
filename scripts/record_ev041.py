"""One-off: append EV-041 recording the WI-141 model-registry persistence layer.

Closes the largest caveat carried by EV-037 through EV-040: the workload registry, model
registry, audit chain, and idempotency ledger were all in-memory, so a restart lost them
together and the containment widening made that gap worse rather than better.

Idempotent, append-only, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-041"
STAMP = "2026-09-29T23:52:00Z"

WORK_ITEM = "WI-141"

CLAIM = (
    "The model registry, workload identities, revocations, and transition idempotency ledger "
    "now have a durable store, and that store refuses the writes whose absence is the whole "
    "point of the domain. The caveat EV-037 through EV-040 each carried is now closed at the "
    "schema: a revocation survives a restart, a revoked identity name can never be re-issued, "
    "and a model record is immutable in place. This is persistence of the *constraints*, not "
    "just of the rows, which is the distinction the earlier records kept pointing at without "
    "being able to close."
)

METHOD = (
    "Wrote db/migrations/0004_model_registry.sql with the four tables and the trigger guards "
    "that make the in-memory guarantees structural, then proved each guard against a real "
    "PostgreSQL 17 through db/tests/0004_model_registry_verify.sql and scripts/verify_ledger_db.py. "
    "Assertions were written as attempt-then-count so a guard that did not fire would leave a "
    "row and be caught, rather than depending on reading an error message. Every write expected "
    "to fail was wrapped so no unhandled error could abort the transaction. Then wrote "
    "services/control-plane/db/queries/model_registry.sql so the schema is exercised by compiled "
    "accessors rather than only by the verification script, and extended "
    "scripts/rehearse_migrations.py to include the new tables and functions so a down body that "
    "silently skipped one of them could not pass rehearsal. Registered the check as a thirteenth "
    "gate in scripts/run_gates.py. Re-checked the parked pgx dependency against the module proxy "
    "rather than trusting the earlier note."
)

RESULT = (
    "db/migrations/0004_model_registry.sql creates model_registry, workload_identities, "
    "workload_revocations, and model_transition_idempotency. The registry refuses a model "
    "missing any of the eleven required fields, a malformed digest, an owner equal to its "
    "author, a non-canonical identifier, and an out-of-set state; refuses every transition that "
    "is not one declared adjacent lifecycle step; refuses a state change citing no audit record; "
    "refuses any in-place edit of version, owner, training fingerprint, or limitations, so a "
    "new model requires a new model_id; and refuses in-place re-registration. Quarantine is "
    "reachable from every non-terminal state and is terminal but for retirement, and retired is "
    "terminal outright, which closes the compromise path from any state including retrospectively. "
    "workload_revocations is append-only against UPDATE and DELETE, requires both a reason and a "
    "forensic evidence reference, and a revoked identity name can never be re-issued - the "
    "narrowest and most important guarantee in the file. "
    "model_transition_idempotency is append-only against UPDATE and DELETE, keys on "
    "(scope, key) so a concurrent retry of one transition produces a unique violation rather "
    "than a second application, and allows the same key in a different scope. "
    "services/control-plane/db/queries/model_registry.sql adds 19 queries with no DELETE and no "
    "arbitrary-state UPDATE; SetModelState requires the audit identifier as a parameter so a "
    "transition whose cause was not recorded cannot be stored, and the containment queries are "
    "shaped so the reported blast radius comes from recorded revocations rather than from the "
    "live identity set, which is the property EV-040 established in Go and which would otherwise "
    "have been quietly lost in SQL. sqlc generate and sqlc vet are clean, go build and go vet are "
    "clean, gofmt reports nothing, the rehearsal applies the full set, reverts to a catalog with "
    "no migration object surviving, and re-applies, and all 13 gates PASS."
)

DEFECTS = (
    "Five defects, all found by the verification rather than by review, which is the argument "
    "for running the real database. First, and the most dangerous: the verification script "
    "reported ALL 0 ASSERTIONS PASSED while having asserted nothing. A single unhandled error "
    "under ON_ERROR_STOP off aborted the transaction, every later statement was refused with "
    "'current transaction is aborted', COMMIT silently became a rollback, and the summary query "
    "counted an empty table and reported that everything it could see had passed. A verification "
    "that asserts nothing is indistinguishable from one that passes everything, and it read as "
    "a pass. scripts/verify_ledger_db.py now treats a zero total as a hard failure and explains "
    "what it looks like, so the trap cannot be re-entered silently by the next migration. "
    "Second, the migration was missing its '-- migrate:down' marker, so the harness applied the "
    "up body and then the down body in one pass and the tables were dropped before a single "
    "assertion ran. This is the exact parser disagreement the harness docstring already warned "
    "about, reproduced in a new file, which is a fair argument that the warning was not strong "
    "enough to prevent it. Third, the up body had BEGIN with no matching COMMIT, so even alone "
    "it was rolled back at end of script. Fourth, the idempotency trigger guarded UPDATE but not "
    "DELETE, so assertion 44 - an applied transition cannot be deleted - genuinely failed. That "
    "was a real gap in the schema rather than a bug in the test: a prunable idempotency ledger "
    "makes a deleted key re-appliable, so a retried request performs the transition twice. "
    "Fifth, the assertion helper was named record, which is a reserved SQL keyword, and its call "
    "sites omitted the SELECT a function call requires; both were parse errors rather than "
    "runtime ones, so the whole script was a rollback and the run reported zero."
)

SIGNIFICANCE = (
    "The general form here is that a passing verification is a claim about how much was "
    "checked, and the count is part of the claim. 'ALL 0 ASSERTIONS PASSED' is a sentence that "
    "reads as success to every parser and every reader, and the defect is not that the "
    "assertions were wrong - they never ran - but that the reporting surface could not tell the "
    "difference. That is why the fix went into the harness rather than only into this script: "
    "the next migration will hit the same trap, and the trap is not specific to this domain. "
    "The second general form is that redundant enforcement is only redundant in one direction. "
    "Every guard here duplicates a Go rule, and the intent is that either layer refusing is "
    "sufficient. The DELETE gap is the case where the duplication was nominal: the trigger "
    "existed, the comment called the table append-only, the Go code could not delete, and the "
    "database still could. Redundancy is only real once each layer is tested independently, and "
    "the database layer can only be tested independently by a real database."
)

CAVEATS = (
    "Six limitations, stated rather than buried. First, and the most important: this closes the "
    "in-memory caveat at the schema, not in the running system. The Go package in "
    "services/control-plane/model still holds its registries in memory and still does not read "
    "or write these tables; the queries are generated, vetted, and correct, but no production "
    "code path calls them yet. A restart still loses the Go-side registry. The durable store "
    "exists and is proven; wiring the journal to it is the next piece of work and is NOT done. "
    "Second, no integration test runs the journal against a real database, so the two layers "
    "have been proven separately and never together: that the schema refuses the prohibited "
    "writes, and that the generated accessors compile and match the schema, but not that the "
    "journal's write sequence is accepted by these specific constraints. SetModelState requires "
    "last_audit_id, and the journal's ordering is that audit append precedes state write, so "
    "the sequences should agree, but 'should' is not a verified claim and it is not verified. "
    "Third, Authenticate still performs no cryptographic verification, unchanged from EV-040; "
    "the identity model is persisted but nothing proves who presented it. Fourth, the revocation "
    "table's evidence_ref is a free-text reference, not a foreign key to a forensic store, so "
    "the linkage is recorded but not enforced and a dangling reference would go unnoticed. "
    "Fifth, the idempotency ledger has no expiry, so its growth is unbounded; that is correct "
    "for an append-only ledger and is a capacity concern rather than a correctness one, but it "
    "is a real one. Sixth, the pgx driver remains unusable: it was re-checked against the module "
    "proxy and every pgx/v5 release from v5.0.0 through v5.11.0 requires "
    "pgservicefile v0.0.0-20240606120523, and pgservicefile has no tagged release at all, so the "
    "dependency-pinning gate cannot be satisfied with any pgx version. This did not block this "
    "work because sqlc is configured for database/sql, so the generated accessors need no new "
    "dependency; wiring them to a real database at runtime does. The mutation harness remains a "
    "verification activity rather than a release gate, consistent with EV-032, EV-034, EV-037, "
    "EV-039 and EV-040. No specification file was modified, docs/ remains clean, nothing was "
    "staged, and nothing was committed."
)

ARTIFACTS = [
    "db/migrations/0004_model_registry.sql",
    "db/tests/0004_model_registry_verify.sql",
    "services/control-plane/db/queries/model_registry.sql",
    "services/control-plane/db/dbgen/model_registry.sql.go",
    "scripts/verify_ledger_db.py",
    "scripts/rehearse_migrations.py",
    "scripts/run_gates.py",
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
    "event_id": "EVT-WI-141-REGISTRY-PERSISTENCE",
    "recorded_at": STAMP,
    "recorded_by": "team-lead",
    "work_item": WORK_ITEM,
    "event": "work_item_implemented",
    "status": "RECORDED",
    "evidence_ref": EVIDENCE_ID,
    "summary": (
        "The model registry, workload identities, revocations, and transition idempotency "
        "ledger now have a durable store whose constraints are proven against a real "
        "PostgreSQL 17. A revocation survives a restart, a revoked identity name can never be "
        "re-issued, a model record is immutable in place, and quarantine is terminal but for "
        "retirement from every non-terminal state. 45 database assertions, 19 generated "
        "queries, migration rehearsal up/down/up clean, all 13 gates PASS. Five defects found, "
        "four of them in the verification of the first. The important one: the script reported "
        "ALL 0 ASSERTIONS PASSED having asserted nothing, because one unhandled error aborted "
        "the transaction and the summary counted an empty table. That reads as success to "
        "every parser, so verify_ledger_db.py now treats a zero total as a hard failure. Also "
        "found: the migration was missing its migrate:down marker so the harness applied up "
        "then down and dropped the tables before any assertion ran; the up body had no COMMIT; "
        "and the idempotency trigger guarded UPDATE but not DELETE, so a prunable ledger would "
        "make a deleted key re-appliable and a retried request would transition twice. That last "
        "one was a real schema gap, not a bad test - redundant enforcement is only redundant "
        "once each layer is tested on its own, and only a real database can do that. NOT DONE: "
        "the Go journal still keeps its registries in memory and does not call these queries, so "
        "a restart still loses the Go-side state; the two layers are proven separately and never "
        "together. pgx remains unusable - re-checked against the module proxy, every release "
        "from v5.0.0 to v5.11.0 requires an untagged pgservicefile that has no tagged release at "
        "all - which did not block this work because sqlc targets database/sql. WI-141 stays "
        "IN_PROGRESS; gate verdict FAIL."
    ),
}


def append_jsonl(path: Path, record: dict) -> None:
    with io.open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=True) + "\n")


PARTIAL_RESULTS = (
    "AC1 registry/audit/idempotency verified: journal.go is the registry's only write path and "
    "writes the lifecycle state only after the audit chain accepts the record describing it. "
    "AC2 no model authorizes its own execution verified. AC3 tool permission-denial, model "
    "rollback, and lineage verified. AC4 all four compromise actions verified, with containment "
    "widening from the detected workload to every workload serving the same exact model version, "
    "and the reported blast radius derived from the revocations recorded rather than from the "
    "live set so it is stable across retries. Identity: short-lived workload identity bound to "
    "one exact model version, with immediate idempotent revocation that carries reason and "
    "evidence into the refusal and blocks re-minting. Persistence: 0004_model_registry.sql adds "
    "a durable registry, workload identity, revocation, and idempotency store whose constraints "
    "are proven against a real PostgreSQL 17 with 45 assertions, plus 19 sqlc queries that "
    "preserve the audit-causation and blast-radius-from-recorded-revocations properties in SQL. "
    "122 model tests race-clean, 109 research tests, 32 of 32 mutations detected with "
    "byte-for-byte restore, all 13 gates PASS. Defects found and fixed: registration was outside "
    "the declared transition set; VerifyDeclaration's rules were structurally untestable so its "
    "empty-source guard could be deleted with the suite green; the quarantine-exit check was "
    "narrower than the comment stating it; the reported containment population was a function "
    "of when the record was written rather than of what had happened; Contain accepted a caller "
    "boolean asserting revocation had happened; the mutation harness applied mutations "
    "cumulatively and could not attribute its own verdicts; a verification script reported ALL 0 "
    "ASSERTIONS PASSED while asserting nothing, because one unhandled error rolled back the "
    "transaction and the summary counted an empty table - the harness now treats a zero total as "
    "a hard failure; the 0004 migration was missing its migrate:down marker and its COMMIT, so "
    "the harness applied up then down and the up body rolled back; and the idempotency trigger "
    "guarded UPDATE but not DELETE, making a prunable ledger that would let a retried request "
    "transition twice. REMAINING: the schema and the generated queries are proven but the Go "
    "journal still holds its registries in memory and does not call them, so a restart still "
    "loses the Go-side state and no integration test runs the journal against a real database - "
    "the two layers have been verified separately and never together; a workload whose identity "
    "was issued by a process that has since restarted is invisible to the widening lookup; "
    "containment quarantines only the artifacts named in the declaration, not every artifact of "
    "the affected version; Contain does not itself perform the model's lifecycle quarantine, so "
    "the four actions are each verified but their atomicity is neither verified nor implemented; "
    "ContainedModelVersions does not say whether a version's artifacts are quarantined; "
    "Authenticate performs no cryptographic verification; workload_revocations.evidence_ref is a "
    "free-text reference rather than a foreign key to a forensic store, so the linkage is "
    "recorded but not enforced; and the idempotency ledger has no expiry, which is correct for "
    "an append-only ledger and a real capacity concern. pgx is unusable and re-confirmed so: "
    "every release from v5.0.0 to v5.11.0 requires an untagged pgservicefile that has no tagged "
    "release at all. Gate verdict FAIL; work item remains IN_PROGRESS."
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
