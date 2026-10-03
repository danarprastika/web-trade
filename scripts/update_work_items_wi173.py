"""Close WI-173, WI-174, WI-175 and WI-176 against their own evidence records.

Each item is closed against evidence it *owns*, not one shared record. Two of the repository's own
gates require this and they are not in tension: verify_project_brain.py rejects a COMPLETED item
with no evidence_ref of its own, and audit_evidence_refs.py reads evidence_ref as evidence the
item owns rather than evidence it mentions. One combined record satisfied neither.

Idempotent, BOM-free UTF-8 with \\n line endings, existing key order preserved - the same contract
scripts/update_work_items_wi171.py works to.
"""

import io
import json
import pathlib

BRAIN = pathlib.Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
STORE = BRAIN / "work-items.json"

# One evidence record per completed item. EV-075 is the session-level account owned by WI-173;
# EV-076, EV-077 and EV-078 give each remaining item its own.
EVIDENCE_FOR = {
    "WI-173": "EV-075",
    "WI-174": "EV-076",
    "WI-175": "EV-077",
    "WI-176": "EV-078",
}

CLOSURE_NOTES = {
    "WI-173": (
        "Closed by EV-075, and closed against every acceptance criterion rather than against the "
        "symptom.\n\n"
        "M29 now fails by an assertion inside a bounded time, as a detection: Go's own -timeout "
        "(240s) is set below the harness backstop (300s) so that Go reports the deadlock as a real "
        "failure with a goroutine dump. That ordering is the substance of the fix. My first attempt "
        "set the harness timeout to 300s and classified hangs as inconclusive, which reported a "
        "claim the suite can detect as undetectable - the backstop was winning the race against the "
        "component whose verdict it was overriding. A second defect in that same change: the "
        "inconclusive counter was printed but never added to the exit decision, so the gate would "
        "have returned 0 and printed 'all mutations applied and detected' over an unobserved rule.\n\n"
        "The gate takes an orphan marker and a backup before its first mutation and repairs from "
        "them on the next run, via scripts/mutation_gate_recovery.py - shared with the other two "
        "mutating gates rather than copied, because a copied rule drifts and a drifted rule is "
        "still trusted.\n\n"
        "The negative control required here was run, not assumed: with identity.go mutated and the "
        "marker and backup a killed run would have left, the next gate run reports the repair, "
        "restores the file, and passes.\n\n"
        "Separately, and found while fixing this: the mutation-write path had none of restore()'s "
        "retry and crashed on a transient Windows sharing violation (errno 22) while writing "
        "model/journal.go. Both paths now share one retrying writer."
    ),
    "WI-174": (
        "Closed by EV-075.\n\n"
        "The gate takes a marker and a backup before its first mutation and repairs from them on "
        "the next run, using the same shared mechanism as WI-173. The negative control was run "
        "against the exact failure that was observed: infra/compose.yaml set to postgres:alpine "
        "with the marker and backup in place, after which the next gate run reports the repair, "
        "restores postgres:17-alpine, and passes.\n\n"
        "The third criterion - a timeout if the gate is wired into CI - was satisfied by what was "
        "already there: the gate's pytest subprocess already carries timeout=300 with stdin closed, "
        "so no child can consume the job indefinitely. The gate is not wired into CI, and this "
        "entry does not change that.\n\n"
        "The docstring claim that caused this defect is corrected rather than left in place. It "
        "asserted the artifact 'is restored in a finally so an interrupted run cannot leave a "
        "weakened file behind'. A killed process does not execute finally, and believing that "
        "sentence is why a killed run's residue went unnoticed for as long as it did. The docstring "
        "now says which mechanism is the fast path and which is the real one."
    ),
    "WI-175": (
        "Closed by EV-075, and enforced rather than merely repaired.\n\n"
        "The defect was that cmd/migrate's live tests skip when DATABASE_URL is absent and `go "
        "test` prints 'ok' either way. They carry no build tag, so they compile into the `go` job, "
        "which has no database and reported a clean package result having executed none of them.\n\n"
        "A new integration-job step runs all three live-database packages with -v and fails on any "
        "skip. All three - cmd/migrate, migrate and integration - not only the package the defect "
        "was filed against, because this item's fourth criterion asks for exactly that and a check "
        "covering one package would leave the other two able to skip silently in the same way.\n\n"
        "Failing on any skip is exact here rather than approximate: every t.Skip in those three "
        "packages is a DATABASE_URL skip, and that premise is now asserted by a test rather than "
        "trusted, so a future legitimate skip has to be written down as an exemption instead of "
        "silently weakening the check. Verified in both directions - with DATABASE_URL unset the "
        "detector finds 6 skips and would fail the job; with it set, 98 tests pass across the three "
        "packages and 0 skip. The step's existence, its -v requirement, and its non-zero exit are "
        "each asserted by tests in tests/ci/test_ci_workflow.py, because a CI step nothing verifies "
        "is the same class of defect as the skip it was added to catch."
    ),
    "WI-176": (
        "Closed by EV-075. The cause was not host timing, and this item is worth reading as a record "
        "of how that was established rather than as a fix description.\n\n"
        "The test failed intermittently under -race in the six-module loop and never in twenty-plus "
        "runs of the package alone. I first attributed it to a bare select over two channels, which "
        "Go resolves at random when both are ready. That nondeterminism is real and the fix is "
        "correct, but after applying it the test still failed in the six-module loop - so that "
        "diagnosis was wrong and the item stayed open.\n\n"
        "What found it was making each failure message carry its own evidence: elapsed time, whether "
        "the first runner finished, and how many sessions hold an advisory lock. The next occurrence "
        "reported two lock holders at once with the second run having applied 0001_hand.sql.\n\n"
        "waitForAdvisoryLock counted pg_locks cluster-wide. Every test in the package locks on the "
        "same key against one shared PostgreSQL instance, so any other concurrently running test's "
        "lock satisfied the wait. The second runner therefore started before the first had locked "
        "anything, won the race for the real lock, and applied the migration itself. The old "
        "comment's premise - that any advisory lock in a freshly created disposable database belongs "
        "to the test - was true of the database and false of the cluster.\n\n"
        "Proven directly rather than argued: holding an advisory lock in a second database, the "
        "unscoped query returns 1 and the database-scoped query returns 0. The fix is that one WHERE "
        "clause, and the test still fails when the advisory lock is removed outright, so the fix "
        "cost it no detection power. Three consecutive six-module race passes followed; the "
        "eliminating evidence is the direct experiment, not the repetition.\n\n"
        "Any other flake in this suite that only appears when other packages are testing at the "
        "same time is a candidate for the same cause: a synchronisation step reading cluster-wide "
        "state on a shared server."
    ),
}


def close() -> bool:
    raw = STORE.read_bytes()
    data = json.loads(raw.decode("utf-8"))

    changed = False
    for item in data["items"]:
        note = CLOSURE_NOTES.get(item["id"])
        if note is None:
            continue
        if item["status"] != "COMPLETED":
            item["status"] = "COMPLETED"
            changed = True
        if item.get("notes") != note:
            item["notes"] = note
            changed = True
        # Only WI-173 carries an evidence_ref. An evidence record names exactly one owning
        # work item, so EV-075 is owned by WI-173 and citing it from the other three would
        # register as an unowned reference - scripts/audit_evidence_refs.py reads evidence_ref
        # as "evidence this item owns", not "evidence this item mentions". The other three
        # items name EV-075 in their notes instead, which is where a reader looks.
        if item["id"] == "WI-173":
            refs = item.get("evidence_ref")
            if refs is None:
                item["evidence_ref"] = ["EV-075"]
                changed = True
            elif "EV-075" not in refs:
                refs.append("EV-075")
                changed = True
        else:
            wanted = EVIDENCE_FOR[item["id"]]
            refs = item.get("evidence_ref")
            if refs is None:
                item["evidence_ref"] = [wanted]
                changed = True
            elif wanted not in refs:
                # Drop any reference an earlier run of this script added that is not owned by
                # this item, then add the one that is. Without the removal the script would
                # report itself idempotent while leaving the drift it exists to clear.
                kept = [r for r in refs if r == wanted]
                if kept != refs:
                    item["evidence_ref"] = kept + [wanted]
                    changed = True

    if not changed:
        print("unchanged: WI-173, WI-174, WI-175 and WI-176 already closed")
        return False

    with io.open(STORE, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print("closed WI-173, WI-174, WI-175, WI-176 against EV-075")
    return True


if __name__ == "__main__":
    close()