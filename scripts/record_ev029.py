"""One-off: append EV-029 and close WI-106.

Follows the same pattern as scripts/record_ev026.py through record_ev028.py: idempotent,
auditable, and kept in the repository so the Project Brain edit is reproducible rather than an
opaque mutation of state.

It writes JSON without a BOM on purpose. PowerShell 5.1 `Set-Content -Encoding UTF8` adds one,
and a BOM at the start of a JSONL line corrupts the record it introduces.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-029"
STAMP = "2026-09-29T07:40:00Z"

CLAIM = (
    "The migration set is reversible and rehearsed against a live PostgreSQL 17: the whole set "
    "applies from empty, reverts newest-first to a catalog with nothing left in it, and applies "
    "again, with 27 named objects checked present, absent, and present. sqlc v1.29.0 generates "
    "typed accessors for 19 queries and `sqlc vet` passes, and the generated output is gofmt-clean "
    "and compiles. Idempotency is enforced by a database constraint rather than by application "
    "logic. The runner's ordering, drift detection, and reversibility rules live in a Go package "
    "that needs no database to test, and the same package is tested against the real files in "
    "db/migrations so a migration added without a down body fails a unit test rather than a "
    "rollback."
)

METHOD = (
    "Implemented services/control-plane/migrate as a driver-free package: Parse orders by "
    "numeric version rather than filename, splits a file into up and down bodies at the "
    "`-- migrate:down` marker, and refuses a duplicate version, a malformed filename, and a "
    "comment-only down body. CheckDrift compares the database's applied set against the file "
    "digests and returns a typed ErrDrift, with the digest covering the up body only so a "
    "down-body comment does not read as drift. Plan refuses a down run that cannot revert every "
    "step rather than reverting part of the set and stopping. Wrote fixture tests for each rule "
    "and real_migrations_test.go, which parses the repository's own db/migrations and asserts "
    "every migration is reversible, carries its own BEGIN/COMMIT, and has no DROP in its up "
    "body. Added real down bodies for 0001, 0002, and 0003 via scripts/add_migration_down_bodies.py, "
    "which is idempotent and refuses to write a file whose up body contains a DROP. "
    "Wrote scripts/rehearse_migrations.py, which applies the set, reverts it, asserts the "
    "catalog is clean via information_schema and pg_proc, and reapplies it against PostgreSQL "
    "17.11; that is the result which shows a reversal actually works rather than merely that a "
    "DROP statement ran. Wrote scripts/pgverify.py as the single owner of the container "
    "lifecycle and the marker convention, and refactored scripts/verify_ledger_db.py onto it, "
    "because the harness and the runner had disagreed about where a migration file ends. "
    "Configured sqlc.yaml against db/migrations, wrote 19 queries in "
    "services/control-plane/db/queries, and added services/control-plane/db/contract to assert "
    "every declared query has a generated accessor and vice versa, verified by mutation. "
    "Replaced the CI migration step with the rehearsal and added sqlc generate-drift and "
    "sqlc vet steps, and added scripts/run_gates.py to run all eleven gates with per-gate "
    "evidence. Every check was mutation-tested: the contract test fails on an un-regenerated "
    "query, the rehearsal fails on a reverted conflict target, and sqlc generate fails on an "
    "unknown column or table. Final state: all eleven gates pass, `python scripts/run_gates.py`."
)

RESULT = (
    "ALL 11 GATES PASS on PostgreSQL 17.11. `python scripts/run_gates.py` -> toolchain PASS "
    "(14 checks); project-brain PASS; pytest tests/ci 100 passed; pytest workers/research/tests "
    "35 passed; 0001_ledger ALL 18 DATABASE ASSERTIONS PASSED; 0002_audit ALL 20 DATABASE "
    "ASSERTIONS PASSED; 0003_authz ALL 54 DATABASE ASSERTIONS PASSED; migration rehearsal "
    "MIGRATION REHEARSAL PASSED (up, down to a clean catalog, and up again, 27 objects verified "
    "present/absent/present); go test ./... in services/control-plane all packages ok; "
    "`sqlc generate` exit 0; `sqlc vet` exit 0. The other five Go modules (contracts, oms, "
    "risk-engine, reconciliation, venues) also test clean, so the whole workspace is green. "
    "Two defects were found and fixed rather than recorded as passing: the harness and the Go "
    "runner parsed migration files differently, which made the 0001 down body drop the schema "
    "the up body had just created; and AppendEntry used ON CONFLICT (idempotency_key) while the "
    "unique index is on the pair (source_command_id, idempotency_key), a statement that sqlc "
    "accepts and that PostgreSQL refuses at runtime, confirmed against a live server. "
    "A third was a flakiness bug in the harness itself: pg_isready reports success during "
    "startup recovery, so readiness now also requires a statement to succeed, and the database "
    "gates were re-run to confirm."
)

RECORD = {
    "schema": "ecc.project-brain/evidence/v7",
    "evidence_id": EVIDENCE_ID,
    "recorded_at": STAMP,
    "recorded_by": "team-lead",
    "work_item": "WI-106",
    "claim": CLAIM,
    "status": "RESOLVED",
    "method": METHOD,
    "result": RESULT,
    "limitations": (
        "Two things are deliberately out of scope and are not counted against this work item. "
        "First, no Go PostgreSQL driver is used: pgx pulls github.com/jackc/pgservicefile, which "
        "has only pseudo-versions, and scripts/verify_toolchain.py refuses those as unpinned "
        "references. That gate was not weakened to accommodate a dependency chosen during this "
        "work. The repository therefore keeps zero external dependencies and no go.sum, and the "
        "CI migration gate calls the Python rehearsal rather than a Go command. The complete "
        "driver-backed store and CLI are parked with their rationale in "
        ".kilo/ecc/project-brain/evidence/wi-106/parked-pgx-store/. Second, db/migrations/0002 "
        "and 0003 create unqualified tables in public using a name prefix while 0001 creates a "
        "real ledger schema, which does not match the per-schema ownership in docs/05. Moving "
        "the nine tables is a breaking change needing its own expand/contract migration and was "
        "left alone; it is recorded as an open finding, not as part of WI-106. Also unverified: "
        "the rehearsal exercises the migrations against an empty database, not against a "
        "production volume, so index build time and lock behaviour on large tables are not "
        "covered."
    ),
    "supersedes": [],
    "defect_found_and_fixed": (
        "Four real defects, each found by a check rather than by inspection and each re-verified "
        "after the fix. "
        "(1) The verification harness applied whole migration files while services/control-plane/"
        "migrate split them at the `-- migrate:down` marker, so the two disagreed about where a "
        "file ends. Adding a down body to 0001 made the down statement drop the ledger schema "
        "immediately after the up statement created it, and the suite failed with 'the "
        "verification script produced no summary', an error that points at the assertions rather "
        "than at the migration. Fixed by making scripts/pgverify.py the single owner of both the "
        "container lifecycle and the marker convention, and refactoring verify_ledger_db.py onto "
        "it; all three suites were re-run and 18/20/54 passed. "
        "(2) AppendEntry used `ON CONFLICT (idempotency_key)` while the unique index "
        "entry_idempotency_uniq is on the pair (source_command_id, idempotency_key), because "
        "uniqueness on the key alone would collapse the same key issued under a different "
        "command and lose a financial fact. sqlc parsed the statement and `sqlc vet` passed, "
        "because the clause is syntactically valid against any table; PostgreSQL refuses it at "
        "runtime, confirmed against a live 17.11 server returning 'there is no unique or "
        "exclusion constraint matching the ON CONFLICT specification'. Fixed in the query, and "
        "GetEntryByIdempotencyKey was changed to take both halves of the pair for the same "
        "reason. The rehearsal now matches every conflict target against the live index list, "
        "because that disagreement is invisible to both the generator and the query contract "
        "test. "
        "(3) That new check passed a deliberately reintroduced defect on the first attempt. It "
        "reconstructed unique indexes by reading pg_attribute without grouping by index, merging "
        "every unique index on a table into one column list, and then matched conflict targets "
        "against a suffix of that merged list. It was also matching the words ON CONFLICT inside "
        "the query file's own explanatory comment, which quotes the very statement it explains. "
        "Fixed by reading one row per index through pg_index.indkey with indnkeyatts, matching "
        "row per index through pg_index.indkey with indnkeyatts, matching on an order-insensitive "
        "column set after empirically confirming PostgreSQL accepts either order, and stripping "
        "SQL comments before scanning while preserving string literals. Mutation-tested "
        "afterwards: the reintroduced defect is caught and named. "
        "(4) The harness was flaky in a way that reported a migration failure rather than a "
        "harness failure: pg_isready succeeds while PostgreSQL is still in startup recovery, and "
        "_read_version ignored the return code of its own query, so the first sweep after a cold "
        "Docker cache failed db-0002 with FATAL: the database system is starting up. Readiness "
        "now requires a statement to succeed as well as pg_isready, and _read_version raises "
        "instead of reporting 'unknown version'. The database gates were re-run to confirm. "
        "Two further errors were made and repaired during the work rather than shipped: a "
        "PowerShell append that risked writing a UTF-8 BOM into a migration file, and a first "
        "version of the down-body script that omitted the marker and so wrote DROP statements "
        "into the up body. Both are now guarded in the scripts themselves, so the mistake cannot "
        "recur silently."
    ),
    "artifacts": [
        "services/control-plane/migrate/",
        "services/control-plane/db/queries/",
        "services/control-plane/db/dbgen/",
        "services/control-plane/db/contract/",
        "scripts/pgverify.py",
        "scripts/rehearse_migrations.py",
        "scripts/add_migration_down_bodies.py",
        "scripts/run_gates.py",
        "sqlc.yaml",
        "db/migrations/0001_ledger.sql",
        "db/migrations/0002_audit.sql",
        "db/migrations/0003_authz.sql",
        ".github/workflows/ci.yml",
        ".kilo/ecc/project-brain/evidence/wi-106/parked-pgx-store/README.md",
    ],
}

EVENT = {
    "schema": "ecc.project-brain/events/v7",
    "event_id": "EVT-WI-106-COMPLETED",
    "recorded_at": STAMP,
    "work_item": "WI-106",
    "type": "WORK_ITEM_COMPLETED",
    "summary": (
        "WI-106 closed: migrations reversible and rehearsed up/down/up against PostgreSQL 17.11, "
        "sqlc generating 19 typed accessors with vet passing, 11 of 11 gates green."
    ),
    "evidence_ref": [EVIDENCE_ID],
}


def append_jsonl(path: Path, obj: dict) -> None:
    with io.open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(obj, ensure_ascii=True) + "\n")


def main() -> int:
    evidence_path = BRAIN / "evidence.jsonl"
    existing = [
        json.loads(line)
        for line in io.open(evidence_path, encoding="utf-8").read().splitlines()
        if line.strip()
    ]
    if any(r.get("evidence_id") == EVIDENCE_ID for r in existing):
        # Replaced rather than skipped. An append-only guard would leave a record written by
        # an earlier version of this script in place forever, missing fields that the project
        # brain gate then refuses; converging to RECORD makes re-running this the way to
        # correct the record.
        current = next(r for r in existing if r.get("evidence_id") == EVIDENCE_ID)
        if current == RECORD:
            print(f"{EVIDENCE_ID} already recorded and up to date.")
        else:
            kept = [
                json.dumps(r, ensure_ascii=True)
                for r in existing if r.get("evidence_id") != EVIDENCE_ID
            ]
            kept.append(json.dumps(RECORD, ensure_ascii=True))
            io.open(evidence_path, "w", encoding="utf-8", newline="\n").write(
                "\n".join(kept) + "\n"
            )
            print(f"{EVIDENCE_ID} updated in {evidence_path.name}")
    else:
        append_jsonl(evidence_path, RECORD)
        print(f"appended {EVIDENCE_ID} to {evidence_path.name}")

    work_path = BRAIN / "work-items.json"
    doc = json.loads(io.open(work_path, encoding="utf-8").read())
    changed = False
    for item in doc["items"]:
        if item["id"] == "WI-106":
            # evidence_ref is a list: the gate iterates it, so a bare string would be
            # read one character at a time as several unknown evidence ids.
            if item.get("status") != "COMPLETED" or item.get("evidence_ref") != [EVIDENCE_ID]:
                item["status"] = "COMPLETED"
                item["evidence_ref"] = [EVIDENCE_ID]
                item["completed_at"] = STAMP
                changed = True
    if changed:
        io.open(work_path, "w", encoding="utf-8", newline="\n").write(
            json.dumps(doc, indent=2, ensure_ascii=True) + "\n"
        )
        print("WI-106 -> COMPLETED")
    else:
        print("WI-106 already COMPLETED")

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
