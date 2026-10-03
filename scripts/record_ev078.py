"""Record EV-078: WI-176 - the advisory-lock flake was an unscoped pg_locks query, not host timing.

Split out of EV-075 because the Project Brain requires an evidence record *owned* by each
completed work item. EV-075 remains the session-level account owned by WI-173.

Idempotent, append-only, written without a BOM.
"""

import io
import json
import pathlib

BRAIN = pathlib.Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"

EVIDENCE_ID = "EV-078"
STAMP = "2026-10-02T20:12:00Z"
WORK_ITEM = "WI-176"

CLAIM = (
    "TestTwoConcurrentRunsSerialiseOnTheAdvisoryLock no longer fails because the machine was busy. "
    "Its cause was a cluster-wide lock count used to synchronise on database-scoped state, and a "
    "failure now means the lock genuinely did not serialise."
)

METHOD = (
    "The first diagnosis was wrong and the record should say so plainly, because the wrongness is "
    "the useful part.\n\n"
    "The test failed intermittently under -race: three times across this session, always inside a "
    "six-module `go test -race ./...` loop, never in more than twenty runs of the migrate package "
    "alone or of the full control-plane module. I attributed it to a bare select over two channels, "
    "which Go resolves at random when both are ready - so choosing secondDone while firstDone was "
    "also ready produced a failure message claiming the second run had returned while the first "
    "still held the lock, when in fact both had simply finished. That nondeterminism is real and the "
    "fix is correct: 'while the first still holds the lock' now requires checking that the first is "
    "genuinely still running, rather than inferring it from which channel the select chose.\n\n"
    "After that fix the test still failed in the six-module loop, which is what proved the diagnosis "
    "wrong. Rather than guess a second time I made every failure message carry its own evidence: "
    "elapsed time, whether the first runner had finished, and how many sessions hold an advisory "
    "lock. The next occurrence answered the question outright:\n\n"
    "  the second run returned while the first still held the lock, after 3.099s with 2 advisory\n"
    "  lock holder(s): second err=<nil> second applied=[0001_hand.sql] first finished=false\n\n"
    "Two lock holders at once, and the second run having applied the migration. That is not a "
    "timing artefact - it says the second runner acquired the lock and executed while the first "
    "still held one.\n\n"
    "waitForAdvisoryLock counted `pg_locks WHERE locktype = 'advisory'`, which is cluster-wide. Every "
    "test in the package locks on the same key, 0x7765627472616465, against one shared PostgreSQL "
    "instance - and the repository runs every package against that single server. So any other "
    "concurrently running test's lock satisfied the wait. The wait returned before this test's first "
    "runner had locked anything, the second runner started unblocked, won the race for the real "
    "lock, and applied the migration itself.\n\n"
    "The comment above the helper stated the premise that hid this: 'Any advisory lock in a freshly "
    "created disposable database belongs to the test, so the count is the whole signal.' That is "
    "true of the database and false of the cluster, and the two were never distinguished."
)

RESULT = (
    "The fix is one WHERE clause: restrict the count to locks whose database is the current one. "
    "advisoryLocksInThisDatabase is used by both waitForAdvisoryLock and the failure diagnostics, "
    "because an unscoped count in the diagnostic would have made it actively misleading - which is "
    "how it managed to mislead in the first place.\n\n"
    "Proven directly rather than argued, since an intermittent failure cannot be demonstrated by "
    "repetition. Holding an advisory lock in a second database on the same server and querying from "
    "the first:\n\n"
    "  unscoped (what the test used to do): 1\n"
    "  scoped   (what it does now):          0\n\n"
    "The old query is satisfied by another database's lock; the new one is not. That experiment is "
    "the evidence of elimination; the three clean six-module passes afterwards are corroboration "
    "only, and are recorded as such.\n\n"
    "The test kept its detection power. Replacing lockRunSQL with a no-op, so the runner never "
    "takes the lock, still fails it - at waitForAdvisoryLock, in 15.2s, with 'the first run never "
    "took the advisory lock, so nothing was actually serialised'. Both before and after the change "
    "the file was restored byte-for-byte and confirmed against HEAD."
)

DEFECT_FOUND_AND_FIXED = (
    "1. services/control-plane/migrate/live_test.go: waitForAdvisoryLock counted advisory locks "
    "cluster-wide instead of per-database, so a concurrent test's lock satisfied this test's wait "
    "and the second runner started before the first had locked anything.\n"
    "2. The comment above that helper asserted a premise that was true of the database and false of "
    "the cluster, which is why the query looked correct in review.\n\n"
    "Corrected while investigating rather than being the defect: the bare select over the two "
    "runner channels, which could report a false violation when both runs had finished. That was a "
    "real bug in the test and it is fixed, but it was not the cause, and the first version of the "
    "comment in the file claimed it was - including a failure rate I had no evidence for."
)

SIGNIFICIFICANCE = (
    "A flake that only appears when other packages are testing is not a flake. It is a "
    "synchronisation step that reads state wider than the thing it is synchronising on, and the "
    "symptom - intermittent failure under load - is the least informative possible presentation of "
    "that bug.\n\n"
    "The lesson is about method rather than about SQL. Two hours went into reproducing this by "
    "running the test again, on the reasoning that a failure which does not reproduce is not worth "
    "fixing properly. What actually found it in one run was adding fields to the failure message so "
    "that the failure carried its own evidence. A message that cannot explain itself forces the next "
    "reader to reproduce the failure, and an intermittent failure is expensive to reproduce by "
    "definition.\n\n"
    "Any other test in this suite that only fails when other packages are testing at the same time "
    "is a candidate for the same cause and should be checked for cluster-wide reads before being "
    "written off as host load."
)

CAVEATS = (
    "Three consecutive six-module race passes after the fix is corroboration, not proof of "
    "elimination. The elimination rests on the direct experiment above; the original failure rate "
    "was roughly one in three six-module loops, so three passes is a weaker sample than would be "
    "comfortable on its own.\n\n"
    "The failure was only ever observed inside the six-module loop, so it depended on concurrent "
    "load across packages rather than within the migrate package. CI runs modules in a loop within "
    "one job, which matches that condition, so this is a real CI risk rather than a purely local "
    "one - but it has not been observed on a GitHub runner.\n\n"
    "The diagnostic fields added to the failure messages were kept, not removed once the cause was "
    "found. They are what made the cause findable and they make the next occurrence diagnosable "
    "without this analysis."
)

EXCEPTION = (
    "No exception. The file edited is the one the item was filed against."
)

ARTIFACTS = [
    ".kilo/ecc/project-brain/evidence.jsonl",
    ".kilo/ecc/project-brain/work-items.json",
    "services/control-plane/migrate/live_test.go",
    "scripts/record_ev078.py",
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