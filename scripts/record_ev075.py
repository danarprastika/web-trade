"""Record EV-075: WI-173, WI-174, WI-175 and WI-176 closed, and the two false claims that hid them.

The valuable part of this entry is not the four fixes. It is that three of the four defects were
invisible to the tooling by construction, and that in two cases the tooling actively asserted
something untrue about itself.

Idempotent and append-only, following scripts/record_ev074.py. Written without a BOM because a
BOM at the start of a JSONL line corrupts the record it introduces.
"""

import io
import json
import pathlib

BRAIN = pathlib.Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"

EVIDENCE_ID = "EV-075"
STAMP = "2026-10-02T19:40:00Z"
WORK_ITEM = "WI-173"

CLAIM = (
    "All four of the residual gate-hygiene items are closed. WI-173: the model mutation gate no "
    "longer hangs on M29 and no longer leaves model/identity.go mutated. WI-174: the local-env gate "
    "can no longer leave infra/compose.yaml mutated. WI-175: a live-database test that skips can no "
    "longer report success in the job that owns the database. WI-176: the advisory-lock "
    "serialisation test no longer fails for a reason that has nothing to do with serialisation - the "
    "root cause was an unscoped pg_locks query, not host timing."
)

METHOD = (
    "Each item was fixed only after reproducing it, and each fix was then checked for the property "
    "that distinguishes a control from documentation: would this still fail if the behaviour it "
    "claims to catch were removed.\n\n"
    "WI-173. M29 removes the workload registry's mutex release, so the package deadlocks. The gate "
    "ran go test with no timeout, which does not fail - it hangs - so the harness hung holding a "
    "mutated identity.go, the run was eventually killed, and the tree kept the mutation because a "
    "killed process never reaches its own restore. Two distinct fixes were needed and the first was "
    "wrong. I set the harness timeout to 300s and classified a hang as inconclusive; M29 then came "
    "back as inconclusive, and a claim the suite genuinely can detect was reported as undetectable. "
    "The backstop was stealing the verdict. Go's own -timeout now fires first (240s) and reports the "
    "deadlock as a real failure, so M29 is a detection; the harness backstop (300s) exists only for "
    "the case where Go cannot speak and is classified inconclusive - and I found and fixed a second "
    "defect in my own change, where the inconclusive counter was reported but never reached the exit "
    "decision, so a hung mutation would have let the gate print 'all mutations applied and "
    "detected' over a rule it never observed.\n\n"
    "WI-174. The gate's docstring claimed the artifact 'is restored in a finally so an interrupted "
    "run cannot leave a weakened file behind'. A killed process does not execute finally. That claim "
    "was believed until a killed run left postgres:alpine in infra/compose.yaml and the next pytest "
    "run failed on a defect nobody had made. The docstring is now corrected and states plainly which "
    "mechanism is the real one.\n\n"
    "Both gates share scripts/mutation_gate_recovery.py. It was inlined in the destructive-migrate "
    "gate first and then extracted, for the reason check_workflow_bash.py was consolidated: a rule "
    "copied into a second gate drifts, and a drifted rule is worse than none because it is still "
    "trusted.\n\n"
    "WI-176. This one I got wrong first. The test failed intermittently under -race, and I attributed "
    "it to a bare select over two channels that Go resolves at random when both are ready. That "
    "nondeterminism is real and the fix is correct, but it was not the cause: after fixing it the "
    "test still failed in the six-module loop. Rather than guess again I made every failure message "
    "carry elapsed time, whether the first runner finished, and how many sessions hold an advisory "
    "lock - and the next occurrence named the cause directly: two lock holders at once, with the "
    "second run having applied 0001_hand.sql. waitForAdvisoryLock counted pg_locks cluster-wide. "
    "Every test in the package locks on the same key against one shared PostgreSQL, so any other "
    "concurrently running test's lock satisfied the wait, the second runner started before the first "
    "had locked anything, and it applied the migration itself. The old comment's premise - 'any "
    "advisory lock in a freshly created disposable database belongs to the test' - was true of the "
    "database and false of the cluster. Proven directly rather than argued: holding an advisory lock "
    "in a second database, the unscoped query returns 1 and the scoped query returns 0."
)

RESULT = (
    "All seven mutation gates pass with no unverified claims. The model gate is the one that "
    "mattered and it now reports 'applied 41 of 41 mutations; detected 41; survived 0; skipped 0' - "
    "it previously reported one skipped. M35 was that skip: its anchor had gone stale when "
    "journal.go gained a nil-store guard, a recordRefusal correction step and a third level of "
    "indentation, so the mutation matched nothing. Re-anchored in the form the rest of that file "
    "already uses for the same shape of claim, and it is now detected by "
    "TestARestartBetweenARefusalAndItsResolutionKeepsTheEvidenceCoherent. The anchor, not the claim, "
    "had rotted; nothing had weakened.\n\n"
    "The mutation-write path also gained the retry that only restore() had. It crashed on a "
    "transient Windows sharing violation while writing model/journal.go - errno 22 - on a lock the "
    "restore would have retried away. The tree came back clean because the finally block ran, but "
    "the gate died mid-run and left its backup behind; the next run's recovery cleared it, which is "
    "the mechanism working as designed after being built for a different failure.\n\n"
    "Both negative controls WI-173 and WI-174 demand were run. Simulating a killed run - mutated "
    "identity.go plus the orphan marker and backup a killed run leaves - the next gate run reports "
    "'a previous run of this gate was killed before it could restore', restores the file, and then "
    "passes. The same was done for compose.yaml, mutating it to postgres:alpine exactly as the "
    "observed failure did.\n\n"
    "WI-175 is enforced rather than merely fixed. A new integration-job step runs all three "
    "live-database packages with -v and fails on any skip. All three - not just cmd/migrate, which is "
    "where the defect was filed - are covered, because WI-175's own fourth criterion asks for that. "
    "Failing on any skip is exact here because every t.Skip in those three packages is a DATABASE_URL "
    "skip, and that premise is now itself asserted by a test rather than trusted. Verified both ways: "
    "with DATABASE_URL unset the detector finds 6 skips and would fail the job; with it set, 98 tests "
    "pass across the three packages and 0 skip.\n\n"
    "WI-176 is fixed and shown not to have cost the test its teeth: removing the advisory lock "
    "entirely still fails it, at waitForAdvisoryLock, in 15.2s. Three consecutive six-module race "
    "passes - the exact condition that failed before - were clean after the fix.\n\n"
    "Final state: gofmt, go vet, go build and go mod verify clean across all six modules; "
    "go test -race -count=1 ./... passing across all six with a live DATABASE_URL; the "
    "integration-tagged suite passing; python -m pytest tests/ci -q at 140 passed; all seven mutation "
    "gates passing with no skipped or surviving mutations; no mutation residue left in the repository "
    "or in the temporary directory."
)

DEFECT_FOUND_AND_FIXED = (
    "Five, four of which were pre-existing and one of which I introduced while fixing a third.\n\n"
    "1. scripts/mutation_check_model.py ran go test with no timeout, so the M29 deadlock hung the "
    "gate indefinitely holding a mutated identity.go.\n"
    "2. My first timeout fix classified a hang as inconclusive, and Go's -timeout was set equal to "
    "the harness backstop so the backstop won the race and reported a detectable claim as "
    "undetectable.\n"
    "3. My second fix counted inconclusive results and printed them but never added them to the exit "
    "decision, so the gate would have reported success over an unobserved rule.\n"
    "4. scripts/mutation_check_local_env.py's docstring asserted that a finally block prevents an "
    "interrupted run from leaving a weakened artifact. A killed process does not run finally. The "
    "claim was the reason the defect survived as long as it did.\n"
    "5. scripts/mutation_check_model.py applied mutations with a bare write_text while restore() "
    "retried twelve times, so a transient lock killed the gate on the one path that lacked the "
    "protection the other path already had.\n\n"
    "Also corrected rather than carried forward: my own first comment on the advisory-lock fix "
    "claimed it failed 'roughly one run in ten' and that the select was the cause. Both were "
    "unsupported when written, and the second was wrong."
)

SIGNIFICIFICANCE = (
    "The pattern across all four is that each defect was hidden by the mechanism that was supposed to "
    "reveal it. A gate that hangs reports nothing. A gate that restores in a finally looks correct "
    "in review and does nothing for a killed process. A skipped test prints 'ok'. A test that counts "
    "cluster-wide state synchronises on somebody else's lock and fails intermittently, which reads as "
    "'flaky' rather than as a synchronisation bug.\n\n"
    "Three of these were recorded in the work items before this session and were correctly filed. "
    "What was missing was any check that the checks themselves do what they say, which is why the "
    "recovery mechanism got fifteen tests, the skip enforcement got a test asserting the CI step "
    "exists, and the advisory-lock fix had to be proven by deleting the lock.\n\n"
    "The generalisable lesson is the one this repository keeps arriving at, now for the fourth time: "
    "a check that reports success having executed none of itself is the specific failure worth "
    "engineering against, and it is not visible from inside the check."
)

CAVEATS = (
    "The WI-176 root cause was found because the failure reproduced in the six-module loop, not in "
    "the package alone - roughly one run in three of that loop, and never in twenty-plus runs of the "
    "package by itself. Any flake of this shape elsewhere in the suite is a candidate for the same "
    "cause: a synchronisation step that reads cluster-wide state on a shared server.\n\n"
    "The three six-module passes after the fix are evidence, not proof of elimination; the "
    "eliminating evidence is the direct experiment showing the old query is satisfied by another "
    "database's lock and the new one is not.\n\n"
    "scripts/mutation_check_destructive_migrate.py carries a UTF-8 BOM. It is a Python source file, "
    "which Python handles, and the repository's BOM prohibition covers JSON and JSONL evidence "
    "artifacts rather than source, so no gate fails on it. It is cosmetically inconsistent and was "
    "left alone rather than rewritten, because rewriting the file's first bytes for no functional "
    "gain is its own small risk.\n\n"
    "Still open and unchanged: WI-172 (F5 schema-level audit-record coverage, deferred by explicit "
    "human decision), cross-store atomicity under WI-120/WI-121, the ApprovalRecord schema decision, "
    "schema-version forward compatibility, RISK-14, WI-117's unqualified tables, and OD-4's resequencing "
    "decision. stash@{0} remains stashed and unreviewed. Push authorisation has not been given, and "
    "the CI workflow has still never run on a GitHub runner - which matters more than usual here, "
    "because the crash-recovery path is exactly what a runner timeout exercises."
)

EXCEPTION = (
    "services/control-plane/migrate/live_test.go was edited in the migrate package while verifying "
    "WI-176, which is filed against it; that is in scope rather than an exception. The one edit "
    "outside a target package's own concerns was .github/workflows/ci.yml, which needed the new "
    "skip-enforcement step for WI-175, and tests/ci/test_ci_workflow.py plus "
    "tests/ci/test_mutation_gate_recovery.py, which are the permanent enforcement for WI-175 and "
    "WI-173/WI-174 respectively."
)

ARTIFACTS = [
    ".kilo/ecc/project-brain/evidence.jsonl",
    ".kilo/ecc/project-brain/work-items.json",
    "scripts/mutation_gate_recovery.py",
    "scripts/mutation_check_model.py",
    "scripts/mutation_check_local_env.py",
    "scripts/mutation_check_destructive_migrate.py",
    "tests/ci/test_mutation_gate_recovery.py",
    "tests/ci/test_ci_workflow.py",
    ".github/workflows/ci.yml",
    "services/control-plane/migrate/live_test.go",
    "services/control-plane/cmd/migrate/main_test.go",
    "evidence/gates/G5-gate-report.json",
    "evidence/gates/G5-gate-report.md",
    "scripts/record_ev075.py",
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
            "significance": SIGNIFICIFICANCE,
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