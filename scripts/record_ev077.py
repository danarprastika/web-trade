"""Record EV-077: WI-175 - a live-database test that skips can no longer report success.

Split out of EV-075 because the Project Brain requires an evidence record *owned* by each
completed work item. EV-075 remains the session-level account owned by WI-173.

Idempotent, append-only, written without a BOM.
"""

import io
import json
import pathlib

BRAIN = pathlib.Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"

EVIDENCE_ID = "EV-077"
STAMP = "2026-10-02T20:02:00Z"
WORK_ITEM = "WI-175"

CLAIM = (
    "A live-database test that skips can no longer produce a green result. All four acceptance "
    "criteria of WI-175 are met, and the property this item protects - that a regression confined to "
    "the live tests cannot pass the verification sweep - is now enforced rather than asserted in a "
    "comment."
)

METHOD = (
    "The defect was located by search rather than assumed: every t.Skip in the repository that is "
    "conditional on DATABASE_URL. There are three, across three packages, and none of them carry a "
    "build tag:\n\n"
    "  cmd/migrate   main_test.go:114                    six live tests call disposableDSN\n"
    "  migrate       live_test.go:36                     the live migration tests\n"
    "  integration   harness_test.go:51, destructive_guard_test.go:280, entrypoint_test.go:495\n\n"
    "Because they carry no build tag they also compile into the `go` job, which has no postgres "
    "service and no DATABASE_URL, and which therefore skipped every one of them while printing a "
    "clean package result. That is the whole defect, and it is why EV-074 could report four "
    "broken tests that every gate had called green.\n\n"
    "The `go` job genuinely has no database, so skipping there is correct and was left alone. What "
    "was not acceptable is that the one job which does have a database - integration, which already "
    "asserts DATABASE_URL is set and that the server is reachable - never checked that its live "
    "tests actually ran. A skip there cannot mean 'no database configured', because the step above "
    "proves it is; it can only mean the tests certified nothing."
)

RESULT = (
    "A new step in the integration job runs all three packages with -v and fails on any skip. "
    "All three rather than only cmd/migrate, because WI-175's fourth criterion asks for exactly "
    "that and a check covering one package would leave migrate and integration able to skip "
    "silently in precisely the same way.\n\n"
    "Failing on any skip is exact rather than approximate here, because every t.Skip in those three "
    "packages is a DATABASE_URL skip - verified by search. That premise is now itself asserted by "
    "test_every_skip_in_the_live_database_packages_is_a_database_skip, so if a package ever grows "
    "a legitimate skip the job fails loudly and the exemption gets written down, instead of the "
    "check being quietly weakened to accommodate it.\n\n"
    "Verified in both directions. With DATABASE_URL unset the detector finds six '--- SKIP' lines "
    "in cmd/migrate and the step fails, which is the behaviour being added. With it set, all three "
    "packages run clean: cmd/migrate 17 passed 0 skipped, migrate 52 passed 0 skipped, integration "
    "29 passed 0 skipped - 98 tests, none skipped, step exits 0.\n\n"
    "The step is itself enforced, because a CI step nothing verifies is the same class of defect "
    "as the skip it was added to catch. Three assertions in tests/ci/test_ci_workflow.py cover it: "
    "all three package paths appear in the script, the skip grep is present, `go test -v` is used "
    "(without -v there are no '--- SKIP' lines to find, so the step would pass having detected "
    "nothing), and a detected skip exits non-zero rather than only annotating.\n\n"
    "The stale comment in main_test.go that explained the original breakage as these tests being "
    "'green only because they skip when DATABASE_URL is unset' is corrected. It was half right and "
    "the half that was wrong mattered: the skip is still the right default, and what was missing "
    "was any enforcement at the job that owns the database."
)

DEFECT_FOUND_AND_FIXED = (
    "1. No CI step anywhere asserted that the live-database tests ran rather than skipped, so a "
    "green integration job was compatible with having executed none of the tests it owns.\n"
    "2. The enforcement added for this item initially covered only cmd/migrate, which satisfies the "
    "symptom and leaves migrate and integration able to skip silently the same way. WI-175's own "
    "fourth criterion asks for all of them.\n"
    "3. A comment in main_test.go attributed WI-171's invisible breakage to the skip itself, "
    "implying the skip was the defect. It was the missing enforcement that was the defect.\n\n"
    "Found while writing the evidence for this item, not while fixing it: EV-075 originally covered "
    "all four items as one record owned by WI-173, which verify_project_brain.py rejects - a "
    "completed item with no evidence_ref of its own is unverifiable - and audit_evidence_refs.py "
    "rejects too, because it reads evidence_ref as evidence the item owns. The tooling caught a "
    "bookkeeping error that a less careful entry would have left in place."
)

SIGNIFICIFICANCE = (
    "This is the fourth recorded instance of the same failure in this repository: a check reporting "
    "success having executed none of itself. The first three produced comments asserting the "
    "invariant; this one produces a step that fails the job, and a test that fails if the step is "
    "removed.\n\n"
    "The generalisable point is that the skip is not the bug. Skipping without a database is a "
    "reasonable default for a developer, and removing it would only trade this failure for a "
    "confusing one. The bug is that the one environment which can prove the tests ran never asked."
)

CAVEATS = (
    "The step runs three packages that the integration job has already run, so the integration "
    "suite is executed twice. That is deliberate - this step exists to inspect the run's output for "
    "skips, not to replace it - but it does cost roughly a minute of CI time.\n\n"
    "The check keys on '--- SKIP' appearing anywhere in those packages. If Go's test output format "
    "ever changed, the grep would silently match nothing and the step would pass having detected "
    "nothing. That is the same class of risk as any output-scraping check and is recorded here "
    "rather than solved.\n\n"
    "Verified locally against a live PostgreSQL. The CI workflow itself has still never run on a "
    "GitHub runner, so the shell function in the new step is unexercised on the platform that will "
    "actually run it."
)

EXCEPTION = (
    ".github/workflows/ci.yml was edited to add the enforcement step, and "
    "tests/ci/test_ci_workflow.py to keep it honest. Both are outside the cmd/migrate package the "
    "defect was filed against; both were required, since the fix is necessarily a CI-level "
    "invariant rather than a change to a test."
)

ARTIFACTS = [
    ".kilo/ecc/project-brain/evidence.jsonl",
    ".kilo/ecc/project-brain/work-items.json",
    ".github/workflows/ci.yml",
    "tests/ci/test_ci_workflow.py",
    "services/control-plane/cmd/migrate/main_test.go",
    "services/control-plane/migrate/live_test.go",
    "services/control-plane/integration/harness_test.go",
    "scripts/record_ev077.py",
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