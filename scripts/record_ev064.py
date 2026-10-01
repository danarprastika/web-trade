"""One-off: append EV-064, which corrects a false claim in EV-062 and EV-063.

EV-062 and EV-063 each state that the integration suite passed - "16 tests pass, 0 fail" and
"16 of 16 ok on a fresh -count=1 run". That was not what happened. Both runs were invoked with
TEST_DATABASE_URL set, but the harness in integration/harness_test.go reads DATABASE_URL. With
the wrong variable set, every test in the package took the t.Skip branch: 17 skipped, 0 passed,
0 failed, and `go test` still reported "ok" and exit 0.

The failure mode is the one this log already has two entries about (EV-060, EV-061): a check
that was never shown to fail. Here the check reported success, in the most convincing form
available, having executed none of the work it claimed to verify. The skip is deliberate and
correct in the harness - a developer without a database should get a skip, not a false failure -
and the comment there says so, including that CI sets DATABASE_URL so a skip there means the job
lost its service. The defect was in the invocation, not the harness, but nothing in the run
distinguished the two, and 'ok' plus exit 0 plus a hand-counted number all read as success.

The record is written rather than the two prior records amended, because the ledger is
append-only and because a correction that quietly rewrites history is indistinguishable from the
error it is correcting. EV-062's product code and its G5.7 conclusion are unaffected and stand;
what was wrong is the description of how the suite was run, and the true result is 17 passed,
0 failed, 0 skipped.

Also recorded here: the four work items whose evidence_ref disagreed with the evidence log's own
ownership field, and the expansion of the G5 report's artifact digests, which had stopped at the
package boundary and so did not cover any of the code G5.7 rests on.

Idempotent, append-only, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-064"
STAMP = "2026-10-01T10:20:00Z"

WORK_ITEM = "WI-141"

CLAIM = (
    "EV-062 and EV-063 both report that the integration suite passed, and that report was wrong. "
    "Both runs were invoked with TEST_DATABASE_URL set while the harness reads DATABASE_URL, so "
    "every test in the package took its skip branch: 17 skipped, 0 passed, 0 failed, exit 0, and "
    "'ok' from go test. The suite that EV-062's G5.7 conclusion rests on was never actually "
    "executed in either entry. Re-run against the variable the harness reads, the package is 17 "
    "passed, 0 failed, 0 skipped, and EV-062's product code and G5.7 verdict stand unchanged; what "
    "was false is the description of the run, not the result. Two further findings from the same "
    "final pass: four work items listed evidence references that disagreed with the evidence log's "
    "own ownership field, and the G5 report's artifact digests had stopped at the package boundary "
    "and so covered none of the migrate, cmd or integration code that G5.7 depends on."
)

METHOD = (
    "Found by running the suite verbosely and counting result lines rather than reading the one "
    "word go test prints on success. The count that exposed it is the skip count: with "
    "TEST_DATABASE_URL set the package reported PASS=0 FAIL=0 SKIP=17, and a suite that verifies "
    "database rehydration cannot pass zero times. Reading integration/harness_test.go confirmed "
    "the variable is DATABASE_URL at the open helper, that an absent value calls t.Skip with "
    "'DATABASE_URL is not set; skipping live-database tests', and that the file's own comment "
    "states CI sets it so a skip in CI means the job lost its PostgreSQL service. The harness was "
    "therefore right and the invocation was wrong, but the run itself could not tell the "
    "difference: identical output, identical exit code. Re-running with DATABASE_URL set gives "
    "17 passed, 0 failed, 0 skipped, and go test's 'ok' is now backed by work that ran. The 16 in "
    "the two earlier records was a hand-count that no longer corresponds to anything observed, "
    "which is why it is restated here as 17 rather than reconciled. The harness comment is "
    "accurate and was left alone. For the reference drift, scripts/audit_evidence_refs.py was "
    "read before it was trusted: its missing set is owned-but-unlisted and its unreferenced set is "
    "listed-but-not-owned, which is the opposite of what the four findings looked like at first "
    "glance, and the two directions are not symmetric. WI-000 omitted EV-002, EV-003 and EV-004 "
    "that it owns; WI-102 omitted EV-008 and EV-009; WI-107 omitted EV-017; and WI-140 listed "
    "EV-033, which EV-033 itself attributes to WI-118 and which WI-118 already lists."
)

RESULT = (
    "Integration suite with DATABASE_URL set: 17 passed, 0 failed, 0 skipped, exit 0, "
    "go test -count=1 -v -tags=integration ./integration/... . scripts/reconcile_evidence_refs.py "
    "resolved all four drifted items, adding the seven records their owners had not listed and "
    "removing EV-033 from WI-140 only after confirming WI-118 already lists it, so no reference was "
    "destroyed; the script derives every change from the work_item field the records already carry, "
    "refuses to remove a reference that its owner does not also list, and reports that case rather "
    "than acting on it. scripts/audit_evidence_refs.py now reports 0 items drifted against 4 "
    "before, and the script is idempotent, reporting 'unchanged' on a second run. The G5 report's "
    "ARTEFACT_GLOBS were extended past the package boundary to services/control-plane/migrate, "
    "cmd/control-plane, cmd/migrate, integration, and go.mod and go.sum, and the report was "
    "regenerated: 58 artifact digests became 77, verdict still PASS, all seven criteria still PASS, "
    "all 77 digests reverified after write. Full re-verification after every change: gofmt clean; "
    "go vet exit 0 with and without the integration tag; default suite -race 9 packages ok; "
    "toolchain gate 14 of 14; tests/ci 115 passed; project brain gate PASS with its own 21 tests "
    "passed; spec gate 22 passed; contracts VALID; research worker 109 passed; backtest worker 47 "
    "passed; migration rehearsal PASSED with a clean catalog and all 36 expected objects after "
    "revert; scripts/probe_driver_pinning.py still reports libpq PASS, pgx FAIL on the "
    "pseudo-versioned pgservicefile, and all three controls FAIL, so EV-060 remains re-verifiable. "
    "work-items.json remains in HEAD's serialisation, verified by scripts/restore_work_items_style.py "
    "reporting 'unchanged', and still differs from HEAD in exactly the same 8 accounted-for fields. "
    "docs/ clean, nothing staged, nothing committed."
)

DEFECT_FOUND_AND_FIXED = (
    "Three. First, and the serious one, the integration suite did not run in EV-062 or EV-063 while "
    "both records stated that it had: a wrong environment variable name, producing 17 skips "
    "reported as success. This is the same family as EV-060 and EV-061, but it is worse than those "
    "two in one respect. Those checks were capable of failing and had not been made to; this one "
    "was incapable of failing in the observed run, because the code path it exercised was never "
    "entered, and it still exited 0 and printed 'ok'. Second, four work items disagreed with the "
    "evidence log about which records they own, none of them touched by this work and all of them "
    "pre-existing. Third, the G5 report's artifact digest list stopped at the package boundary, so "
    "the report that certifies G5.7 digested the composition root and none of migrate/store_sql.go, "
    "the cmd entrypoint, the integration tests, or the pinned dependencies - the report could not "
    "be used to re-verify the criterion it was written to close."
)

SIGNIFICANCE = (
    "The first defect is the reason this entry exists rather than a quiet edit, and it is worth "
    "stating precisely because the pattern keeps recurring in this repository at three different "
    "levels. A check that has never been observed to fail is not known to work. EV-060 was a driver "
    "argument that had never been run; EV-061 was a migration runner that reported success while "
    "creating nothing. This is a test suite that reported success while executing none of itself. "
    "Each was caught only by a different check than the one that was trusted: the pin probe, an "
    "artifact count, and here a verbose result count. The generalisable lesson is that 'the check "
    "passed' and 'the check ran' are separate facts, and the cheap way to establish the second is "
    "always available - print the result lines, count the skips, look for a suite that passed zero "
    "times. The harness's own skip is correct behaviour and should not be changed: a developer "
    "without a database is better served by a skip than by a false failure, and the comment "
    "explains that CI's own skip is not benign. What is missing is a way to make a skip loud when "
    "the caller believed the work was running, which is a property of the invocation, not of the "
    "test file. The artifact-glob gap matters independently. A gate report is a claim that a "
    "criterion can be re-verified from the repository, and that claim is only as good as its "
    "digest list; digesting the package boundary while the criterion's actual subject sat outside "
    "it produced a report that certified more than it evidenced. The three findings share a root "
    "cause worth naming: each was a verification artifact trusted for the appearance of having been "
    "produced rather than for what it contained."
)

CAVEATS = (
    "Five limitations. First, the correction is a new record rather than an amendment, so the "
    "ledger now contains two records whose '16 tests pass' phrasing is known-false; a reader who "
    "reads EV-062 or EV-063 without EV-064 will be misled, and the honest fix is a reader that "
    "follows supersedes, which does not exist yet. Second, EV-062's and EV-063's own recorded "
    "results for gofmt, go vet, the default suite, the toolchain gate, tests/ci, the project brain "
    "gate, contracts, the workers, the migration rehearsal and the driver probe were re-run here "
    "and are independently confirmed, but their descriptions of how those runs were invoked were "
    "not re-audited; the same class of error would not have been caught by re-running. Third, the "
    "reconciler removed EV-033 from WI-140 on the strength of the evidence log's work_item field; if "
    "that field is itself wrong for EV-033 the correction is in the wrong place, and it was not "
    "traced back to the claim that created the record. Fourth, adding seven references to three "
    "work items changes their evidence_ref arrays, which is the intended effect of the audit but "
    "was not separately reviewed per item, so a reviewer should still confirm that WI-000, WI-102 "
    "and WI-107 own the records now listed on them. Fifth, the graceful SIGTERM drain remains "
    "unproven by test on Windows, cross-store atomicity remains WI-120 and WI-121's and is still "
    "not claimed, the human_reviewer field of the G5 report remains null so WI-141 stays "
    "IN_PROGRESS, and the schema-version forward problem, the unqualified audit and authz tables "
    "(WI-117) and RISK-14's deferred scaling findings remain human-owned. Nothing was staged and "
    "nothing was committed."
)

EXCEPTION = ""

ARTIFACTS = [
    "scripts/reconcile_evidence_refs.py",
    "scripts/audit_evidence_refs.py",
    "scripts/record_ev064.py",
    "scripts/generate_g5_gate_report.py",
    "services/control-plane/integration/harness_test.go",
    "evidence/gates/G5-gate-report.json",
    "evidence/gates/G5-gate-report.md",
    ".kilo/ecc/project-brain/work-items.json",
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
