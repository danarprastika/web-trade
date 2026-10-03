"""Close WI-171 and open WI-172.

WI-171 is complete: the guard moved to the shipped command and a mutation gate certifies its
nine properties. WI-172 carries the F5 residue - the schema does not require total checkpoint
coverage - which was deferred by explicit human decision rather than left as an untracked note.

Idempotent. Writes BOM-free UTF-8 with \\n line endings and preserves the existing key order.
"""

import io
import json
import pathlib

BRAIN = pathlib.Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
STORE = BRAIN / "work-items.json"


def main() -> bool:
    doc = json.loads(STORE.read_text(encoding="utf-8"))
    items = doc["items"]

    by_id = {i["id"]: i for i in items}

    wi171 = by_id["WI-171"]
    wi171["status"] = "COMPLETED"
    wi171["priority"] = "high"
    wi171["write_scope"] = [
        "services/control-plane/migrate",
        "services/control-plane/cmd/migrate",
        "services/control-plane/integration",
        "scripts",
        ".github/workflows",
    ]
    wi171["evidence_ref"] = ["EV-072"]
    wi171["completed_results"] = [
        "The evaluator moved from integration/harness_test.go - a _test.go file that "
        "`go run ./cmd/migrate` never executes - into services/control-plane/migrate/"
        "destructive.go as exported API. The harness is now thin wrappers over it, so the "
        "command and the test cannot drift apart.",
        "cmd/migrate/main.go evaluates the target before sql.Open and exits 2 on refusal, so "
        "a refused destruction names the database it protected without contacting it. The exit "
        "code is 2 rather than 0 because a refusal reporting success is worse than no guard for "
        "anything scripted around the command.",
        "The guard applies to unbounded `down` only: parsed == migrate.Down && *to == 0 && "
        "!givenTo. `up`, `status` and a bounded `-to` are unaffected, which is correct - the "
        "first two are not destructive and a bounded revert has a defined target.",
        "The opt-in is necessary but not sufficient. IntegrationOptInPolicy has "
        "OptInOverrides: true because the harness needs to be able to destroy its own "
        "disposable database; CommandOptInPolicy has it false, so on the shipped command both "
        "the target match and the exact opt-in are required. This is F8, and it was the defect "
        "the prose described but the code did not implement.",
        "scripts/mutation_check_destructive_migrate.py certifies all nine properties, each "
        "noticed by a failing assertion rather than a broken build. It requires a mutation to "
        "compile before running any test under it, because it mutates source that other tests "
        "in the package also run. Gate result: PASS.",
        "The gate's crash recovery was validated by a real occurrence: an earlier run was "
        "killed mid-mutation, left destructive.go permissive, and the next run reported the "
        "orphan marker and restored the file before testing anything.",
        "F3 closed by TestAcceptingZeroRecordsNeitherUnhaltsNorDowngradesTheFinding, which "
        "pins that Accept(0) neither unhalts the guard nor downgrades a recorded finding, and "
        "that Clear afterwards still reads the escalated cause.",
        "F7 confirmed already complete. The only remaining SEV-1_AUDIT_INTEGRITY literals are "
        "in tests, and guard.go:22-23 documents that they are constructed by hand so a typo in "
        "the constant cannot make a test pass vacuously.",
        "CI runs the gate as its own step. The workflow bash gate parses 43 run blocks, PASS.",
    ]
    wi171["notes"] = (
        "Closed as planned: a move plus an exit code, not a rewrite. Three findings carried "
        "forward from the previous review were re-investigated and did not survive - F5's "
        "Go-side half is refuted by restore_test.go:283 and journal_test.go:118, which "
        "deliberately assert that a chain extending past its last checkpoint verifies, because "
        "Chain owns linkage and Anchor owns attestation; and F7 was already done. F5's schema "
        "residue was real and is WI-172, deferred by explicit human decision rather than "
        "folded into a destructive-command change.\n\n"
        "The gate caught three defective mutations in my own work, the worst being a "
        "`&& false` that left `parsed == migrate.Down` visible to the source check written to "
        "detect its removal - a mutation that satisfied the very test aimed at it. Two "
        "source-position claims were consequently removed and the ordering property moved to a "
        "behavioural assertion, because a string index in a file proves where a name appears "
        "and not what executes first."
    )

    if "WI-172" not in by_id:
        items.append(
            {
                "id": "WI-172",
                "phase": 2,
                "title": "The audit schema does not require total checkpoint coverage",
                "status": "PENDING",
                "priority": "medium",
                "acceptance_criteria": [
                    "Every committed audit record is covered by a checkpoint, so no record can "
                    "sit in the store with no signature attesting to it",
                    "The requirement is enforced by the database rather than only by the Go "
                    "write path, since 0003_authz.sql:11 already identifies a second writer that "
                    "does not go through the Go package as the threat this schema exists for",
                    "The enforcement does not break the legitimate write path: a deferred "
                    "constraint trigger on audit_records AFTER INSERT must still admit the "
                    "records-plus-checkpoint transaction SQLSink.Export commits",
                    "Verified against live PostgreSQL, not only by reading the migration",
                    "Negative controls prove a second writer inserting an uncovered record is "
                    "refused, by a failing assertion rather than a broken build",
                ],
                "source": "Adversarial review finding F5, re-investigated during WI-171; "
                "db/migrations/0002_audit.sql:251-254; services/control-plane/audit/sink.go:221-227; "
                "db/migrations/0003_authz.sql:11",
                "reproduction": "0002_audit.sql's audit_checkpoints_coverage trigger fires only "
                "on INSERT into audit_checkpoints, and validates checkpoint -> records: the "
                "count and boundary hashes of the range a checkpoint claims. Nothing requires "
                "the reverse. The only AFTER INSERT trigger on audit_records is "
                "audit_records_chain_link, which checks hash linkage alone. A second writer "
                "holding INSERT on audit_records can therefore commit a record that is "
                "correctly linked but covered by no checkpoint, and Verify - which also only "
                "checks checkpoint -> records, at verify.go:162-170 - reports the database "
                "clean. The record is present, internally consistent, and unattested, and "
                "nothing says so. Total coverage does hold in the shipped product, because "
                "SQLSink.Export is the only production write path and it inserts the records "
                "and their signed checkpoints in one transaction, but it holds only there.",
                "notes": "Deferred by explicit human decision during WI-171 rather than fixed "
                "in place. A migration against the compliance-critical audit schema has real "
                "blast radius: every fixture that seeds records without checkpoints would need "
                "to change, and it belongs with the deferred schema and durability work rather "
                "than beside a destructive-command change.\n\n"
                "Scope that this item must NOT take, established by reading the tests: "
                "Verify must not be made to require total coverage. restore_test.go:283 appends "
                "past the last checkpoint and requires OK, and journal_test.go:118 verifies "
                "records with nil checkpoints, because Chain owns linkage and Anchor owns "
                "attestation and Chain.Append has no signer. The earlier F5 finding, which "
                "proposed exactly that, would have inverted three deliberate tests and made a "
                "core API unusable. The 0003 architecture decision also warns against "
                "deferring the checkpoint to Export, since that reopens the unanchored-tail "
                "window restore.go:125-171 exists to refuse.\n\n"
                "The honest limit of this finding: it is reasoning from the migration text, not "
                "an observation against live PostgreSQL, and its importance depends on a second "
                "writer existing at all.",
                "dependencies": [],
            }
        )

    out = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    with io.open(STORE, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(out)

    print("WI-171 COMPLETED, WI-172 recorded")
    return True


if __name__ == "__main__":
    main()