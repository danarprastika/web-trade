"""Record EV-073: an independent review found a critical defect in WI-171's own fix, plus three
smaller ones. This entry also corrects a specific false claim made in EV-072.

Evidence is append-only, so a claim in EV-072 that turned out to be untrue cannot be edited; it is
corrected here and the correction is cross-referenced from WI-171.

Idempotent, following scripts/record_ev072.py.
"""

import io
import json
import pathlib

BRAIN = pathlib.Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"

EVIDENCE_ID = "EV-073"
STAMP = "2026-10-02T11:40:00Z"
WORK_ITEM = "WI-171"

CLAIM = (
    "An independent review of the WI-171 change set found four defects, one of them critical and "
    "one of them falsifying a claim EV-072 made. The critical one is a hole the change set opened "
    "rather than closed: the guard exempted bounded reverts on the strength of a sentence about "
    "DownTo that was not true, and `-direction down -to 1` therefore destroyed the audit schema "
    "unguarded - the exact outcome WI-171 exists to prevent. All four are fixed and the guard now "
    "covers every down."
)

METHOD = (
    "The review was delegated read-only to a code-reviewer subagent with explicit instructions to "
    "verify each claim rather than trust it, and - importantly - to decide independently whether "
    "the two findings I had refused to fix were wrongly dismissed. It returned four findings and "
    "confirmed both refusals.\n\n"
    "Every finding was then checked by hand against the source before acting, which is the same "
    "discipline EV-072 records applying to a summary. The critical finding is the reason this "
    "entry exists and it is worth stating precisely how it was established.\n\n"
    "I had written, in main.go and in a test, that a bounded revert 'reverts above a bound and "
    "does not take the ledger or the audit schema with it'. The reviewer read migrate.go and "
    "found DownTo's own doc comment: 'the plan is the applied migrations above version, newest "
    "first'. On the real set - 0001_ledger, 0002_audit, 0003_authz, 0004_model_registry - that "
    "makes `-to 1` plan versions 4, 3 and 2, and version 2 is 0002_audit.sql, whose down body is "
    "DROP TABLE IF EXISTS audit_records CASCADE. I confirmed this by reading the same two places. "
    "The bound below 0002 is not a case that spares the audit schema; it is the case that destroys "
    "it while appearing bounded. An unbounded down destroys exactly the same tables. The bound "
    "chooses how much is reverted and has no bearing on whether a destructive down body runs, so "
    "it cannot be the thing that decides whether the guard applies."
)

RESULT = (
    "The guard now applies to every `-direction down`, bounded or unbounded. `up` and `status` are "
    "still exempt, which is correct: they are how a database is first reached, and TestThe"
    "GuardDoesNotApplyToUpOrStatus holds that line. The permitted-path message now reports what "
    "will actually be reverted - 'every applied migration', or 'every applied migration above "
    "version N' when a bound is given - because the previous message said 'reverts every applied "
    "migration' on a bounded run, which was a second way the old code lied about itself.\n\n"
    "TestABoundedRevertIsNotGuarded became TestABoundedRevertIsGuardedToo, using `-to 1` "
    "specifically rather than a bound that would have been harmless under both the old rule and the "
    "new one, since a test exercising only `-to 4` passes either way and therefore certifies "
    "nothing. The mutation gate now certifies the exemption coming back: one of its nine "
    "properties reinstates `parsed == migrate.Down && *to == 0 && !givenTo` and requires "
    "TestABoundedRevertIsGuardedToo to fail. The source-check test asserts the bare condition "
    "`if parsed == migrate.Down {` is present, so the narrowing cannot be reintroduced on the "
    "strength of a plausible-sounding comment - which is how it was introduced.\n\n"
    "The gate immediately caught an error in the new mutation: I had also listed "
    "TestAnUnboundedRevertAgainstAProductionDatabaseIsRefused as covering it, and the gate "
    "reported that this test 'passed against a broken guard'. It was right - reinstating the "
    "exemption leaves the unbounded path guarded - so the listing was claiming a detection that "
    "does not exist and was removed.\n\n"
    "The medium finding is a correction to EV-072. That entry claims the harness and the command "
    "'cannot drift apart'. They could. integration/harness_test.go built its own "
    "DestructivePolicy literal field for field instead of calling migrate.IntegrationOptInPolicy, "
    "so editing IntegrationOptInPolicy would have left the harness untouched while "
    "destructive_test.go - which asserts on the function - stayed green. The harness now delegates. "
    "The literal was character-identical to the function's return, so this is behaviour-preserving.\n\n"
    "Full sweep after all four fixes: gofmt clean; vet clean; unit -race green on all 6 modules "
    "(11 packages in control-plane); live PostgreSQL integration green at 127.1s including the new "
    "sink-atomicity and destructive-guard tests; all four mutation gates PASS - destructive-migrate "
    "9 properties, anchor 5, drain 2, fan-out 6; tests/ci 124 passed; G5 report regenerated and "
    "re-verifying 94 artifact digests."
)

DEFECT_FOUND_AND_FIXED = (
    "Four, one critical.\n\n"
    "CRITICAL - the bounded-revert exemption. cmd/migrate guarded only `parsed == migrate.Down && "
    "*to == 0 && !givenTo`, on a comment claiming `-to` 'does not take the ledger or the audit "
    "schema with it'. It takes both. `-to 1` reverts 0002_audit.sql and drops audit_records, "
    "audit_checkpoints and audit_deletion_events, against whatever DATABASE_URL is exported, with "
    "no opt-in and no confirmation. WI-171 was raised for precisely that outcome; the fix shipped "
    "with a hole of the same shape in it. Three things made it worse rather than better: the false "
    "claim was written into the command's own comment as settled fact, a new test "
    "(TestABoundedRevertIsNotGuarded) enshrined the hole as 'a deliberate asymmetry rather than an "
    "oversight', and the mutation gate certified 'a bounded revert is guarded too' - which passed, "
    "because the gate was testing the hole I had just built. Nine green properties, one of them "
    "describing the defect.\n\n"
    "MEDIUM - harness and shipped policy could drift, which falsifies an EV-072 claim. The harness "
    "re-declared the permissive policy instead of calling IntegrationOptInPolicy. Fixed by "
    "delegation.\n\n"
    "LOW - unreachable code in destructive.go: a second `policy.OptInOverrides && optedIn` "
    "override site after the switch, which every path already handled above it. It read as a "
    "deliberate second way in for an auditor to check; there was not one. Removed, with a comment "
    "recording why so it is not readded as though it were meaningful.\n\n"
    "LOW - EXD-014 cited audit/journal_test.go:118, which does not exist; the file is "
    "model/journal_test.go:118. Corrected. The F5 conclusion it supports does not depend on the "
    "path, and the reviewer independently re-derived it.\n\n"
    "Also mine, this round: the mutation-gate entry that listed a test which does not fail under "
    "its mutation, caught by the gate rather than by me."
)

SIGNIFICANCE = (
    "The generalisable finding is about what a passing gate certifies, and it is uncomfortable "
    "because the gate was mine and was working exactly as designed.\n\n"
    "'A bounded revert is guarded too' was a true statement about the code and a false statement "
    "about the requirement. The code did guard bounded reverts - for the value of -to I happened to "
    "be looking at. The requirement was never to guard bounded reverts; it was to stop "
    "0002_audit.sql's down body from running against a database nobody authorised. Certifying the "
    "first instead of the second produced a green gate, a passing test, and a comment explaining "
    "why the hole was correct.\n\n"
    "Every guard in this change set was written from a prose description of what the code does "
    "rather than from reading what the code does. 'DownTo reverts above a bound' was in the "
    "function's own doc comment, three files away, and I did not read it. The independent reviewer "
    "read it in the course of checking my reasoning and found the hole in the first five minutes. "
    "The lesson is not 'review more' - it is that when a safety argument rests on the behaviour of "
    "another function, that function gets read, because the argument is only as good as the "
    "reading and a plausible sentence is indistinguishable from a true one until you check."
)

CAVEATS = (
    "Four limitations. First and unchanged: human_reviewer is still null. The review that found "
    "the critical defect was performed by an agent, and the fix was made by the same agent that "
    "introduced the defect, so the specific concern that a self-fix is not independently checked "
    "applies here with full force.\n\n"
    "Second, the review was scoped to this change set. It did not cover the model package, the "
    "journal, or anything else in the uncommitted tree, so 'no other critical defects' is not a "
    "claim anyone has made and should not be inferred.\n\n"
    "Third, the guard now refuses bounded reverts on production databases, which is a behaviour "
    "change beyond WI-171's original scope of the unbounded form. It is the correct change - the "
    "alternative was a hole - but it means an operator rolling back a single migration against "
    "production must now set the opt-in. No human has confirmed that trade-off; it was made on "
    "the reasoning that the command cannot tell which down bodies are destructive from outside, "
    "and a version list would silently rot as migrations are added.\n\n"
    "Fourth, unchanged and still owned elsewhere: WI-172 (the schema does not require total "
    "checkpoint coverage) and WI-173/WI-174 (two local-only mutation gates that leave tracked "
    "files mutated when interrupted, one of which neutered the workload registry's mutex for part "
    "of this session) are open; cross-store atomicity remains WI-120/WI-121's and OD-4 a human "
    "decision; EXD-011/EXD-012 still gate the write path; ApprovalRecord restoration needs a "
    "schema decision; stash@{0} remains stashed and unreviewed; push authorisation has not been "
    "given; and the CI workflow has still never run on a GitHub runner."
)

EXCEPTION = (
    "integration/harness_test.go's harnessPolicy changed from a struct literal to a call to "
    "migrate.IntegrationOptInPolicy(). The values are identical, so no behaviour changes, but it "
    "is an edit to a file outside the packages the guard lives in."
)

ARTIFACTS = [
    ".kilo/ecc/project-brain/evidence.jsonl",
    ".kilo/ecc/project-brain/work-items.json",
    ".kilo/ecc/project-brain/decisions.md",
    "services/control-plane/cmd/migrate/main.go",
    "services/control-plane/cmd/migrate/destructive_guard_test.go",
    "services/control-plane/migrate/destructive.go",
    "services/control-plane/migrate/migrate.go",
    "services/control-plane/integration/harness_test.go",
    "db/migrations/0002_audit.sql",
    "scripts/mutation_check_destructive_migrate.py",
    "scripts/record_ev073.py",
]

SUPERSEDES = ["EV-072"]


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