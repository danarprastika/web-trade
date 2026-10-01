"""One-off: append EV-061.

Closes the gap EV-060 disclosed. That record established a gate-satisfying driver can reach
PostgreSQL but stated, honestly, that the migrations and queries had never been run. They have
now been: four migrations applied to a clean database, 40 sqlc queries prepared against the
resulting schema, the generated struct's field order compared to the live column order, and a
real row round-tripped through the two queries the rehydration path depends on.

No product code changed. This record is verification of code that already existed.

Idempotent, append-only, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-061"
STAMP = "2026-10-01T07:40:00Z"

WORK_ITEM = "WI-141"

CLAIM = (
    "The SQL layer beneath the rehydration work is now verified against a real PostgreSQL 17.11 "
    "server, which EV-060 explicitly did not claim. All four migrations apply cleanly to an empty "
    "database; all 40 named sqlc queries prepare against the resulting schema; the generated "
    "ModelRegistry struct's 18 fields match the live column order position for position, which is "
    "the contract ListAllModels's SELECT * depends on; and a real RETIRED row round-trips through "
    "GetModel while ListAllModels returns it and ListActiveModels does not, confirming the "
    "terminal-state blindness those two queries were separated to handle."
)

METHOD = (
    "Built five scripts, each with a control that must fail before any pass is believed. "
    "apply_migrations_up.py resets the database and applies the up half of each migration, "
    "importing the repository's own migration_bodies splitter rather than reimplementing the "
    "up/down convention. verify_queries_live.py first PREPAREs a query naming a column that does "
    "not exist and requires it to be rejected, then PREPAREs all 40 named queries. "
    "verify_column_order.py compares the generated struct's json-tag order to the live ordinal "
    "positions, and verify_column_order_control.py feeds that comparator a swapped list, a "
    "truncated list and the real list, requiring the first two to be flagged and only the third "
    "to pass. verify_queries_roundtrip.py inserts a real row, reads it back, and deletes it. Ran "
    "the whole chain twice from a reset database to confirm it is reproducible rather than "
    "order-dependent."
)

RESULT = (
    "Schema: 15 tables across public plus 2 in ledger, from 0001 through 0004, all applied with "
    "ON_ERROR_STOP=1 and exit 0. Queries: 40 of 40 prepared, 0 failed, across audit.sql (11), "
    "ledger.sql (8) and model_registry.sql (21); the harness control naming a nonexistent column "
    "was rejected first, so the pass is discriminating. Column order: 18 live columns against 18 "
    "struct fields, identical in order. Round trip: GetModel returned 18 columns with the expected "
    "model_id and state; ListAllModels returned 1 row; ListActiveModels returned 0. Two findings "
    "along the way, both in my own harness rather than in the repository. First, piping a whole "
    "migration file through psql runs its migrate:down section after migrate:up, so the down "
    "section dropped everything the up section had just built and the database was left empty "
    "with exit 0 - a silent no-op that would have read as success. The file split at line 338 and "
    "353 is the explanation, and the repository's own splitter is the fix. Second, the round-trip "
    "insert was twice refused by check constraints, model_registry_digest_shape for four columns "
    "requiring 64-character lowercase hex and model_registry_id_prefixed for the mdl_ prefix and "
    "34-character limit, plus model_registry_owner_differs_from_author; my probe data was wrong "
    "and the database was right."
)

DEFECT_FOUND_AND_FIXED = (
    "None in the repository. Three in my own verification work, all caught before being recorded "
    "and all of the same kind as the over-generalisation EV-060 corrected: a check that had not "
    "been tested for the ability to fail. A migration runner that reported success while leaving "
    "the database empty, because it applied both halves of each file. A column-coverage check that "
    "flagged six false positives, because it treated a query selecting a column subset as a "
    "defect and mis-parsed a comment as a table name. And a migration script that was not "
    "re-runnable, because CREATE SCHEMA IF NOT EXISTS is idempotent while CREATE SEQUENCE is not, "
    "so a second run failed on the first sequence. All three were fixed before anything was "
    "written down: the splitter is now the repository's own, the coverage heuristic was replaced "
    "by the positional comparison that matches what SELECT * actually requires, and the runner "
    "owns its own database reset. No product code changed and no test changed behaviour."
)

SIGNIFICANCE = (
    "The durable layer is the one part of WI-141 that no test could previously reach. Every model, "
    "audit and identity test in this work item runs against an in-memory fake, because the Go "
    "modules have no PostgreSQL driver, so the SQL that the real system would execute had never "
    "been parsed by a database at all. That is a wider blind spot than the missing driver, and it "
    "is the one thing EV-060's caveat pointed at. Closing it found the constraints load-bearing "
    "rather than decorative: the database refused twice, and a migration file that reports exit 0 "
    "while creating nothing is exactly the failure mode that a fake-backed test suite cannot "
    "surface, because the fake accepts whatever shape the Go code hands it. The most useful "
    "result is also the smallest: ListAllModels returns a retired model and ListActiveModels does "
    "not, on a real server. That is the specific claim EV-049's rehydration rests on, and it had "
    "been argued from the query text and never observed."
)

CAVEATS = (
    "Four limitations, and this record verifies SQL rather than wiring. First, and most "
    "important: the Go control plane still cannot reach this database. Everything here was driven "
    "by psql and by temporary scripts, not by services/control-plane, so SQLSink, SQLStore, "
    "SQLIdentityStore and SQLChainReader remain unexercised against a live server and their "
    "transaction, commit, isolation-level and mid-commit-error paths are still unproven. That "
    "requires the driver decision reserved to the project owner and taken in EV-060, and it is "
    "why G5.7 remains FAIL. Second, PREPARE proves a statement parses, resolves and plans; it "
    "does not prove it returns correct values, which is why the round-trip probe exists and why "
    "it covers GetModel, ListAllModels and ListActiveModels rather than all 40. The other 37 are "
    "verified to resolve and to be syntactically sound, not to be semantically correct. Third, "
    "the column-order check covers ModelRegistry only, because it is the struct behind a SELECT *; "
    "the other queries project named columns and are positionally safe by construction. Fourth, "
    "the schema was applied to a scratch database called wi141_verify inside a local container, "
    "not to webtrade_test, and no migration was run through services/control-plane/migrate, so "
    "this says nothing about the Go migrator's own behaviour. Unchanged: WI-141's acceptance "
    "criteria remain verified, the G5 verdict remains FAIL and this record attests to neither, "
    "audit-acceptance and registry-persistence atomicity remain WI-121's, the schema-version "
    "forward problem remains human-owned, the unqualified audit and authz tables remain WI-117's, "
    "RISK-14's deferred scaling findings are open, no specification file was modified, docs/ "
    "remains clean at zero changes, nothing was staged, and nothing was committed."
)

EXCEPTION = ""

ARTIFACTS = [
    "scripts/apply_migrations_up.py",
    "scripts/verify_queries_live.py",
    "scripts/verify_column_order.py",
    "scripts/verify_column_order_control.py",
    "scripts/verify_queries_roundtrip.py",
    "scripts/record_ev061.py",
]

SUPERSEDES = []


def record() -> bool:
    store = BRAIN / "evidence.jsonl"

    line = json.dumps(
        {
            "schema": "ecc.project-brain/evidence/v7",
            "evidence_id": EVIDENCE_ID,
            "recorded_at": STAMP,
            "recorded_by": "team-lead",
            "work_item": WORK_ITEM,
            "claim": CLAIM,
            "status": "VERIFIED",
            "method": METHOD,
            "result": RESULT,
            "defect_found_and_fixed": DEFECT_FOUND_AND_FIXED,
            "significance": SIGNIFICANCE,
            "caveats": CAVEATS,
            "exception": EXCEPTION,
            "artifacts": ARTIFACTS,
            "supersedes": SUPERSEDES,
        },
        ensure_ascii=False,
    )

    if store.exists():
        for existing in store.read_text(encoding="utf-8").splitlines():
            if existing.strip() and json.loads(existing).get("evidence_id") == EVIDENCE_ID:
                print("unchanged: " + EVIDENCE_ID + " already recorded")
                return False

    with io.open(store, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")
    print("recorded " + EVIDENCE_ID)
    return True


if __name__ == "__main__":
    record()
