"""Record EV-074: a second independent review of the WI-171 fix, and a defect the fix introduced
in cmd/migrate's own tests.

The most useful thing in this entry is not the defect. It is that the defect was invisible to
every check I had run, including a green mutation gate, because those tests skip when DATABASE_URL
is unset - so "cmd/migrate tests pass" was true and meaningless.

Idempotent, following scripts/record_ev073.py.
"""

import io
import json
import pathlib

BRAIN = pathlib.Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"

EVIDENCE_ID = "EV-074"
STAMP = "2026-10-02T12:05:00Z"
WORK_ITEM = "WI-171"

CLAIM = (
    "A second, focused independent review of the corrected WI-171 guard confirmed the critical hole "
    "is closed on all six axes it was asked about, and found that the fix had broken four of "
    "cmd/migrate's own live tests. Those tests were green before and after, because they skip when "
    "DATABASE_URL is unset - so the break was invisible to every gate in the repository, including "
    "the one written for this change."
)

METHOD = (
    "Because I introduced the defect the first review found, I had the fix re-verified rather than "
    "self-certified. The second review was read-only and narrower: six specific questions about the "
    "corrected guard, plus an explicit instruction to answer the question that matters most after "
    "'is the hole closed' - whether the new bounded-revert test is genuine or passes for the wrong "
    "reason.\n\n"
    "Its answer to that was the second defect. cmd/migrate's live tests create a scratch database "
    "named migrate_cli_<pid>_<hex>. That name ends in a hex suffix, so it matches neither the "
    "guard's disposable suffix list (_test / _tests / _it / _ci) nor its prefix rule (test_). "
    "Under the corrected guard - which applies to every down - every live down run in that package "
    "was refused before reaching a statement.\n\n"
    "I reproduced this directly rather than taking it on trust: running `go test ./cmd/migrate/` "
    "with DATABASE_URL set fails four tests, with the guard's refusal message naming the scratch "
    "database as 'not named like a disposable one'. Running the same command without DATABASE_URL "
    "passes, because disposableDSN skips when the variable is unset. That is the whole defect. "
    "Every previous report of this package being green was green in the skip."
)

RESULT = (
    "Fixed two ways, both necessary under the strict command policy, which requires the disposable "
    "name AND the opt-in. The scratch database is now test_migrate_cli_<pid>_<hex>, which matches "
    "the prefix rule, and a single cliEnv helper adds MIGRATE_ALLOW_DESTRUCTIVE=1. The helper is "
    "applied uniformly across the live tests rather than only to the four that run down, so no test "
    "in the file can quietly start depending on the guard's default; the tests that actually own "
    "the guard's behaviour live in destructive_guard_test.go and deliberately run without the "
    "variable.\n\n"
    "`go test -count=1 ./cmd/migrate/` now passes with DATABASE_URL set, 26.3s, and the four revert "
    "tests genuinely exercise a real down against a real database.\n\n"
    "The review confirmed the first fix on every axis it checked: no flag combination reaches a "
    "destructive down body without the guard having run; -dry-run still returns before the guard "
    "and provably has no effect; the scope message is truthful in both bounded and unbounded form "
    "and strconv is the only added symbol; the removed code in destructive.go was genuinely "
    "unreachable with no behaviour change; and the harness delegation preserved the permissive "
    "policy exactly.\n\n"
    "Full sweep after both rounds: gofmt clean; vet clean; race tests green on all 6 modules with "
    "DATABASE_URL set so the live tests actually ran; integration 64 passed / 0 skipped / 0 "
    "failed; all four mutation gates PASS; tests/ci 124 passed; project brain PASS; evidence 0 "
    "drifted; bash gate PASS across 43 run blocks; toolchain 14 of 14; G5 report regenerated over "
    "the final tree and re-verifying 94 artifact digests."
)

DEFECT_FOUND_AND_FIXED = (
    "Two, both mine, both introduced by the fix for the first one.\n\n"
    "First - four live tests in cmd/migrate were broken by the corrected guard and nothing "
    "reported it. TestABoundedRevertStopsAtTheTarget, TestAnUnboundedRevertStillRevertsEverything, "
    "TestARevertToAVersionThatIsNotAppliedIsRefused and TestARevertToAnUnknownVersionIsRefused "
    "each drive a real down against a scratch database whose name did not announce itself "
    "disposable. Fixed by renaming to the test_ prefix form and passing the opt-in.\n\n"
    "Second - TestABoundedRevertIsGuardedToo omits the two assertions its sibling refusal tests "
    "carry, namely the exit-code check and the absence of 'connecting to the database' in stderr. "
    "The review judged it non-vacuous - if the guard were skipped the run would reach sql.Open "
    "against an invalid host and print no marker, so the test fails - but weaker than its "
    "siblings, and the weakness is recorded here rather than left as an unremarked asymmetry.\n\n"
    "Also observed, not mine and not fixed: TestTwoConcurrentRunsSerialiseOnTheAdvisoryLock "
    "(migrate/live_test.go:241) failed once during a full-module -race run with 'the second run "
    "returned while the first still held the lock', then passed three times in isolation and twice "
    "in the same full-module run. It is timing-sensitive against a shared database and this change "
    "set does not touch it. Recorded as WI-175 rather than described as a pass."
)

SIGNIFICANCE = (
    "The finding worth keeping is about evidence, not code.\n\n"
    "'go test ./cmd/migrate/ passes' was reported repeatedly in this change set, including after "
    "the critical defect was found and fixed, and it was true every time. It was also close to "
    "meaningless: the four tests that drive the actual behaviour of the command against a real "
    "database skip when DATABASE_URL is unset, and DATABASE_URL was not set for the unit-test runs. "
    "So the package that contains the safety-critical change had no live coverage in any local run, "
    "the mutation gate was operating on skipped tests for its behavioural properties, and the "
    "breakage I introduced by fixing the critical defect could not surface until someone happened "
    "to run with a database attached.\n\n"
    "This is the same lesson EV-071 and EV-072 record about gates that credit the wrong signal, "
    "arrived at from the opposite direction: not a gate that reports success falsely, but a suite "
    "whose success is conditional on an environment variable nobody set. A skip is not a pass and "
    "is not an absence of a failure either - it is the absence of evidence wearing the costume of "
    "both. The concrete habit this suggests is to report test counts with skip counts, and to "
    "deliberately run the suite in the configuration where its behaviour is exercised, which is "
    "what finally turned up the regression here."
)

CAVEATS = (
    "Five limitations. First and unchanged: human_reviewer is still null. Both reviews were "
    "performed by an agent and the fixes by the agent that made the defects, so the third-party "
    "check is weaker here than it would be with a person who did not write any of it.\n\n"
    "Second, the second review was scoped to the WI-171 fix. It did not re-examine the FanOut work, "
    "the sink-atomicity tests, or the guard_test.go additions from F3.\n\n"
    "Third, the behaviour change that guarding every down implies has still not been confirmed by "
    "a human: an operator rolling back a single migration against a production database must now "
    "set MIGRATE_ALLOW_DESTRUCTIVE=1 even though the bound limits the damage. The reasoning is "
    "recorded in EV-073 - the command cannot tell which down bodies are destructive from outside - "
    "but it is a policy consequence, not an implementation detail.\n\n"
    "Fourth, WI-172 (schema does not require total checkpoint coverage), WI-173 and WI-174 (two "
    "local-only mutation gates that leave tracked files mutated when interrupted) and WI-175 (the "
    "timing-sensitive advisory-lock test) are open. WI-173 and WI-174 are not merely tidy: one of "
    "them neutered the workload registry's mutex for part of this session, and nothing in the "
    "tooling reported it.\n\n"
    "Fifth, unchanged and still owned elsewhere: cross-store atomicity is WI-120/WI-121's and OD-4 "
    "is a human resequencing decision; EXD-011/EXD-012 gate the write path; ApprovalRecord "
    "restoration needs a schema decision; the schema-version forward problem, RISK-14 and WI-117's "
    "unqualified tables are untouched; stash@{0} remains stashed and unreviewed; push "
    "authorisation has not been given; and the CI workflow has never run on a GitHub runner, which "
    "matters more than usual because the new gate's crash recovery is exactly the code path a "
    "runner timeout would exercise."
)

EXCEPTION = (
    "cmd/migrate/main_test.go was edited outside the guard's own package: the scratch database name "
    "and a cliEnv helper, five call sites. This was required because the corrected guard made those "
    "tests wrong, and leaving them wrong would have meant shipping a change whose own package's "
    "behavioural tests no longer ran."
)

ARTIFACTS = [
    ".kilo/ecc/project-brain/evidence.jsonl",
    ".kilo/ecc/project-brain/work-items.json",
    "services/control-plane/cmd/migrate/main_test.go",
    "services/control-plane/cmd/migrate/destructive_guard_test.go",
    "services/control-plane/cmd/migrate/main.go",
    "services/control-plane/migrate/live_test.go",
    "services/control-plane/migrate/destructive.go",
    "scripts/mutation_check_destructive_migrate.py",
    "scripts/record_ev074.py",
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