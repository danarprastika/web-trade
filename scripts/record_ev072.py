"""Record EV-072: the destructive-migration guard on the shipped command, and three findings
that did not survive contact with the code.

Follows scripts/record_ev071.py. Idempotent: refuses to append an evidence_id that is already
in the ledger.
"""

import io
import json
import pathlib

BRAIN = pathlib.Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"

EVIDENCE_ID = "EV-072"
STAMP = "2026-10-02T10:15:00Z"
WORK_ITEM = "WI-171"

CLAIM = (
    "The destructive-target guard now protects the shipped migrate command rather than only "
    "the integration test harness that never ran it, and a mutation gate certifies that all "
    "nine of the guard's promises can fail. Three findings carried forward from the previous "
    "review turned out not to be defects at all when checked against the code: two of them "
    "asserted a requirement that three deliberate tests contradict, and one was already done "
    "and documented as intentional. The fourth is real and is now tracked rather than fixed."
)

METHOD = (
    "WI-171 was implemented as a move rather than a rewrite. The rule already existed in "
    "integration/harness_test.go, which is a _test.go file: `go run ./cmd/migrate` never "
    "executes it, so the one thing standing between an operator and DROP TABLE audit_records "
    "CASCADE was present in the repository and absent from the product. The evaluator was "
    "lifted verbatim into migrate/destructive.go as exported API, the integration harness was "
    "reduced to thin wrappers over it so the two cannot drift, and cmd/migrate/main.go "
    "consults it before sql.Open and exits 2 on refusal. The exit code was fixed because a "
    "refusal that reports success is worse than no guard for anything scripted around it.\n\n"
    "The mutation gate was written to the pattern EV-071 established, with one addition: it "
    "requires each mutation to compile before it runs any test under it, because it mutates "
    "source files that other tests in the same package also run, and a non-compiling mutation "
    "makes every test in the package exit non-zero with none of them executing. It takes a "
    "backup of both files and repairs from it if killed.\n\n"
    "Three of my own mutations were defective and the gate reported each as UNCERTIFIED rather "
    "than crediting them. Appending `&& false` left the substring `parsed == migrate.Down` in "
    "the file, so the source check that looks for exactly that string passed against a command "
    "that no longer consulted the guard at all - a mutation that satisfied the very test "
    "written to catch it. The second replaced the guard condition with a redundant second "
    "evaluation after sql.Open, which is behaviourally inert because the first guard still runs, "
    "so the only thing it satisfied was a positional string-index assertion in the test. The "
    "third and fourth failed to compile, one because the replacement reused the name of an "
    "existing parameter. Two source-position claims were then removed from the test and the "
    "ordering property moved to a behavioural assertion - that stderr contains no "
    "'connecting to the database' - because a string index in a file proves where a name "
    "appears, not what executes first.\n\n"
    "F5 and F7 were re-investigated before acting, not implemented as recorded. F5 asserted "
    "that coverage is validated in one direction and not the other. Reading verify.go, "
    "restore.go and 0002_audit.sql confirmed the shape of the observation and then refuted its "
    "significance: restore_test.go:283 appends a record past the last checkpoint and requires "
    "Verify to return OK, and its comment states the design directly - the chain owns linkage "
    "and the anchor owns attestation. journal_test.go:118 verifies OK with nil checkpoints. "
    "Requiring total coverage would have inverted three deliberate tests and made Chain.Append "
    "unusable, on the authority of a one-line summary written the day before. F7 was already "
    "complete: the only remaining literals are in tests, and guard.go:22-23 explains that they "
    "are constructed by hand so a typo in the constant cannot make the test pass vacuously."
)

RESULT = (
    "destructive-migration mutation gate: PASS (all 9 properties are enforced, each noticed by "
    "a failing assertion rather than a broken build). The nine certified properties are that the "
    "command consults the guard at all, that a refusal exits non-zero, that the guard does not "
    "apply to up or status, that a bounded -to is not guarded, that the shipped policy stays "
    "strict, that the opt-in is compared exactly, that a DSN naming no database is refused, that "
    "a query string which redirects the connection is refused, and that the refusal names the "
    "database without leaking the password.\n\n"
    "The gate's crash recovery was validated by a real occurrence rather than by argument. An "
    "earlier run was killed mid-mutation and left migrate/destructive.go with "
    "CommandOptInPolicy() mutated to OptInOverrides: true, which made the shipped strict policy "
    "permissive and failed the migrate package tests. The next run detected the marker, reported "
    "'a previous run of this gate was killed before it could restore, and it had left production "
    "source mutated', restored destructive.go from the backup, and proceeded to test the "
    "unmutated tree. That is the mechanism working on the exact case it was written for.\n\n"
    "F3 is closed. Accept never consults the latch - its contract is that it never discards and "
    "refuses only when full - so Accept(0) returning nil while halted is intended. "
    "TestAcceptingZeroRecordsNeitherUnhaltsNorDowngradesTheFinding pins it, and the test "
    "documents why the opposite reading would be a bug: refusing Accept while halted would stop "
    "the backlog growing under a SEV-1 halt, so records already accepted when the chain broke "
    "would sit in memory with no accounting path able to grow the buffer that must hold them.\n\n"
    "Full sweep after the change set: gofmt clean; vet, unit -race and go mod verify green on "
    "migrate, cmd/migrate and audit; the destructive-migrate gate PASS; the workflow bash gate "
    "PASS across 43 run blocks; the backup marker absent after a clean run; destructive.go "
    "carrying OptInOverrides true only for IntegrationOptInPolicy and false for "
    "CommandOptInPolicy."
)

DEFECT_FOUND_AND_FIXED = (
    "One defect, the one WI-171 was raised for: the shipped migrate command had no "
    "destructive-target guard. -direction down with no -to reverts the whole applied set, and "
    "0002_audit.sql's down body is DROP TABLE IF EXISTS audit_records CASCADE followed by the "
    "rest of the audit schema, so one flag against whatever DATABASE_URL names destroys the "
    "tamper-evident chain the platform's compliance story rests on. Also fixed: a refusal "
    "exiting 0, which any scripted caller would read as success.\n\n"
    "Three defects in my own work during this change set, all caught by the gate rather than "
    "after: the `&& false` mutation that satisfied the string check written to catch it, the "
    "inert second-evaluation mutation, and two replacements that did not compile. A fourth "
    "claim - that the guard is evaluated before the connection opens - was asserted by a "
    "source-position test and proved false by that same mutation, so the claim was moved to a "
    "behavioural assertion rather than left standing as a passing test.\n\n"
    "Not fixed, deliberately. F5's schema residue is real but is a migration to a "
    "compliance-critical schema with real blast radius on every fixture that seeds records "
    "without checkpoints, so it is recorded as WI-172 rather than smuggled in beside a "
    "destructive-command change."
)

SIGNIFICANCE = (
    "The transferable finding is about the recorder, not the guard. Three of the four carried-"
    "forward findings were wrong or already done, and two of them were wrong because an earlier "
    "review of the diff summarised them in one line without reading what the tests around them "
    "were asserting. Acting on that summary would have inverted three deliberate tests and made "
    "a core API unusable, while looking like the disciplined thing - a previously recorded defect, "
    "now closed. Re-reading a claim against the code that contradicts it is cheaper than "
    "reversing a change to a compliance system, and the contradiction was visible in tests that "
    "had been read once and cited as supporting evidence.\n\n"
    "The second point is that a mutation gate earns its keep on the mutator. The gate caught "
    "three defective mutations, and the worst one - `&& false` - had been written specifically "
    "to test the guard's central test and instead satisfied it. A gate that has only ever caught "
    "defects in someone else's code is not yet known to work."
)

CAVEATS = (
    "Five limitations. First and unchanged: human_reviewer is still null. This change set, like "
    "everything before it in this series, was implemented and reviewed by agents.\n\n"
    "Second, the mutation gate has been run against the current tree only. It has never "
    "executed on a GitHub runner, so its behaviour under CI timeouts is untested - which is the "
    "exact condition its recovery exists for, and the one case where recovery failing would be "
    "worst, because a killed CI run leaves mutated production source. The local occurrence is "
    "evidence that the repair works; it is not evidence that the marker and backup are always "
    "written before the first mutation.\n\n"
    "Third, F5's residue is unproved by execution. It rests on reading 0002_audit.sql: the "
    "coverage trigger fires only on audit_checkpoints INSERT, and the only AFTER INSERT trigger "
    "on audit_records is the chain-link check, so a second writer with INSERT could commit an "
    "unattested record that Verify would report as clean. That reasoning has not been "
    "demonstrated against live PostgreSQL, and the claim that it matters depends on a second "
    "writer existing, which is exactly the threat 0003_authz.sql:11 names but does not "
    "establish.\n\n"
    "Fourth, the integration harness was reduced to thin wrappers over the shared evaluator, "
    "and integration/restart_test.go required a two-site edit in an earlier change for the "
    "required-signer design; the harness refactor itself has not yet been run against live "
    "PostgreSQL in this session.\n\n"
    "Fifth, unchanged and still owned elsewhere: cross-store registry/audit atomicity remains "
    "WI-120 and WI-121's and OD-4 remains a human resequencing decision; ApprovalRecord outcome "
    "restoration needs a deliberate schema decision; durable transactional-outbox support for "
    "audit is EXD-011 and production write exposure stays disabled under EXD-012; the "
    "schema-version forward problem, RISK-14, WI-117's unqualified tables and real-signal "
    "interruption testing are untouched; stash@{0} still holds unattributed transactional-"
    "outbox and audit changes pending human review and was neither popped nor discarded; and "
    "push authorisation has still not been given."
)

EXCEPTION = (
    "The integration harness and the command now share one implementation, which required "
    "rewriting integration/harness_test.go's evaluator as thin wrappers. The behaviour is "
    "unchanged and its tests still pass, but the file no longer contains the logic it did, and "
    "that substitution is visible only through the diff."
)

ARTIFACTS = [
    ".kilo/ecc/project-brain/evidence.jsonl",
    ".kilo/ecc/project-brain/work-items.json",
    "services/control-plane/migrate/destructive.go",
    "services/control-plane/migrate/destructive_test.go",
    "services/control-plane/cmd/migrate/main.go",
    "services/control-plane/cmd/migrate/destructive_guard_test.go",
    "services/control-plane/integration/harness_test.go",
    "services/control-plane/integration/destructive_guard_test.go",
    "services/control-plane/audit/guard.go",
    "services/control-plane/audit/guard_test.go",
    "db/migrations/0002_audit.sql",
    "scripts/mutation_check_destructive_migrate.py",
    "scripts/record_ev072.py",
    ".github/workflows/ci.yml",
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