"""Record EV-076: WI-174 - the local-env gate can no longer leave infra/compose.yaml mutated.

Split out of EV-075 because the Project Brain requires an evidence record *owned* by each
completed work item, not one shared record citing several. EV-075 remains the session-level
account owned by WI-173.

Idempotent, append-only, and written without a BOM: a BOM at the start of a JSONL line corrupts
the record it introduces.
"""

import io
import json
import pathlib

BRAIN = pathlib.Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"

EVIDENCE_ID = "EV-076"
STAMP = "2026-10-02T19:52:00Z"
WORK_ITEM = "WI-174"

CLAIM = (
    "scripts/mutation_check_local_env.py can no longer leave infra/compose.yaml mutated when "
    "interrupted, and its docstring no longer claims a mechanism that cannot work."
)

METHOD = (
    "The docstring was the defect as much as the missing backup was. It asserted the artifact 'is "
    "restored in a finally so an interrupted run cannot leave a weakened file behind'. A killed "
    "process does not execute finally - that is the definition of the failure this item was filed "
    "from - so the claim was not merely optimistic, it was the reason nobody treated the missing "
    "backup as a bug. Reviewing the gate, the restore looked correct.\n\n"
    "So the fix has two halves and the first half is correcting the sentence. The gate now takes an "
    "orphan marker and a backup before its first mutation and repairs from them on the next run, "
    "via scripts/mutation_gate_recovery.py. The docstring now names which mechanism is the fast "
    "path (the finally block, for a run that finishes normally) and which is the real one (the "
    "backup, which survives the process).\n\n"
    "The mechanism was inlined in mutation_check_destructive_migrate.py first and then extracted "
    "into one module shared by all three mutating gates. That is the same reason "
    "check_workflow_bash.py was consolidated: a rule copied into a second gate drifts, and a "
    "drifted rule is worse than no rule because it is still trusted.\n\n"
    "The negative control this item demands was run against the exact observed failure rather than "
    "a convenient one. infra/compose.yaml was set to postgres:alpine - the same unpinned image the "
    "interrupted run left behind - with the marker and backup in place. This was the first negative "
    "control attempted and it did not work, because the marker was written in the wrong shape. The "
    "gate crashed with a bare KeyError instead of refusing cleanly, which exposed a real defect in "
    "the recovery module itself: valid JSON in the wrong shape is as unusable as unreadable JSON, "
    "and was reaching an unhandled error path. Fixed and covered by a test."
)

RESULT = (
    "Verified in the state the defect was observed in. With compose.yaml at postgres:alpine and a "
    "correct marker present, the next gate run prints 'a previous run of this gate was killed "
    "before it could restore, and it had left a tracked file mutated', restores "
    "infra/compose.yaml, and then proceeds normally: all eleven mutations detected and all files "
    "restored byte-for-byte, exit 0. git confirms infra/ matches HEAD exactly afterwards.\n\n"
    "Three defects in the shared recovery module were found by writing its tests and are now "
    "covered: a marker that is valid JSON in the wrong shape raised a bare KeyError instead of "
    "refusing cleanly; a manifest naming a file whose parent directory no longer existed crashed "
    "with FileNotFoundError instead of recreating the path; and the refusal message when a write "
    "genuinely cannot happen did not name the file, which is the only information a reader needs "
    "in order to repair by hand.\n\n"
    "The gate's own third criterion - a timeout if it is ever wired into CI - was already "
    "satisfied and is unchanged: its pytest subprocess carries timeout=300 with stdin closed, so "
    "no child can consume a job. The gate is not wired into CI and this entry does not change that.\n\n"
    "The full gate passes: eleven mutations, all caught by a failing assertion rather than a broken "
    "build, and all three artifacts restored byte-for-byte."
)

DEFECT_FOUND_AND_FIXED = (
    "1. scripts/mutation_check_local_env.py's docstring asserted that a finally block prevents an "
    "interrupted run from leaving a weakened artifact. A killed process does not run finally.\n"
    "2. The gate had no crash recovery at all, so an interrupted run left compose.yaml mutated with "
    "nothing marking it.\n"
    "3. Found while testing the fix, in scripts/mutation_gate_recovery.py: a manifest that is valid "
    "JSON in the wrong shape raised an unhandled KeyError instead of the intended clean refusal.\n"
    "4. Found the same way: a manifest naming a file under a deleted directory crashed with "
    "FileNotFoundError instead of recreating the parent.\n"
    "5. Found the same way: the refusal message for an unwritable target did not name the file."
)

SIGNIFICIFICANCE = (
    "A gate that mutates production files is itself a source of production defects, and the "
    "mechanism protecting the repository was documented in a way that made the gap invisible. The "
    "backup directory now lives outside the repository on purpose: a killed run's residue is "
    "repaired by the next run, not by a person noticing, because the failure mode it repairs is "
    "precisely the one where nothing else runs.\n\n"
    "The negative control failing on the first attempt is the part worth keeping. I wrote the marker "
    "by hand in the wrong shape, and instead of a clean refusal the gate produced a traceback - "
    "which turned out to be a genuine defect in code I had just written. Had I written the control "
    "to match my own implementation's expectations, that defect would have shipped."
)

CAVEATS = (
    "The recovery directory is shared per gate name on the machine, so two concurrent runs of the "
    "same gate on one host would collide. That is a pre-existing property of keeping the backup "
    "outside the repository and is not addressed here; CI runs one instance per job.\n\n"
    "The recovery mechanism is exercised and tested, but a real runner kill has still not been "
    "observed end to end. The CI workflow has never run on a GitHub runner, which matters more than "
    "usual here because a runner timeout is exactly the path that would exercise it."
)

EXCEPTION = (
    "scripts/mutation_check_local_env.py's docstring and imports were edited, and scripts/"
    "mutation_gate_recovery.py was added, neither of which is in the infra/ path this item is "
    "about. Both were required: the docstring correction is part of the fix, and the shared module "
    "is where the mechanism lives after extraction from the destructive-migrate gate."
)

ARTIFACTS = [
    ".kilo/ecc/project-brain/evidence.jsonl",
    ".kilo/ecc/project-brain/work-items.json",
    "scripts/mutation_gate_recovery.py",
    "scripts/mutation_check_local_env.py",
    "tests/ci/test_mutation_gate_recovery.py",
    "infra/compose.yaml",
    "scripts/record_ev076.py",
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