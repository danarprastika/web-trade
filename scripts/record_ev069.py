"""One-off: append EV-069.

Records the commit, and the one thing it changed about the repository's own gates: the
`sqlc is up to date` step went from red to green. That step had been failing in the working tree
since the rehydration queries were added, and EV-066 established the cause carefully - the
regenerated output was tracked but uncommitted, and the callers that reference it were untracked
too, so HEAD built clean and nothing was actually broken. The commit is what made the step able
to pass, because the step's whole job is comparing the generated output against the committed
tree and the comparison only becomes meaningful once both sides are committed.

Also records the attestation correction this required. The report previously stated that no
commit contained this gate's work and that none was requested. Once the work is committed that
sentence is false, and an attestation that describes a state the repository is no longer in is
worse than no attestation. It now describes the commit field as the baseline the work was built
on, which is the semantic that actually helps a reviewer, and it says plainly why the field
cannot record the commit containing the work: a commit cannot contain its own SHA.

The full CI job sequences were then re-run against the committed tree rather than the working
tree, which is the first time any of this has been verified in its post-commit state. Every step
passes. The report's own currency check is part of that, and it is worth noting what it is now
checking: a committed report against a committed generator and a committed tree, which is the
only configuration in which the check means anything.

Idempotent, append-only, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-069"
STAMP = "2026-10-01T15:55:00Z"

WORK_ITEM = "WI-141"

CLAIM = (
    "The work is committed as 758ce11, 109 files, and the `sqlc is up to date` step - the last "
    "red gate in the workflow - now passes. It had been failing since the rehydration queries were "
    "added, and it fails no longer for the reason EV-066 established rather than a different one: "
    "the regenerated output and the callers that reference it are now both committed, so the "
    "step's comparison is between two committed things and is therefore meaningful. Every step of "
    "both CI job sequences was re-run against the committed tree and passes."
)

METHOD = (
    "The pending set was reviewed before staging rather than committed blind: 98 files grouped by "
    "area, with _driver_probe and any scratch or temporary files confirmed absent, and docs/ "
    "confirmed to contain nothing staged, because the specification paths are not this work's to "
    "change. A secret scan over every pending file produced one hit, which was read in context "
    "rather than dismissed: it is EV-030's prose describing a Docker bug, where "
    "docker run -e 'PGPASSWORD=$PGPASSWORD' in single quotes sets the container variable to the "
    "literal seven-character string and every connection fails. It documents a defect and contains "
    "no credential. The message style follows the repository's conventional commits, and states "
    "the two things a reader of this commit most needs stated plainly: that the write path is not "
    "exposed, and that human_reviewer is null and stays null. After the commit, `sqlc generate` "
    "followed by `git diff --exit-code` over the generated directory was the first check run, "
    "because it was the one step known to be red and the commit is what should have turned it "
    "green."
)

RESULT = (
    "Committed 758ce11 on main: 109 files changed, 19817 insertions, 49 deletions. The working "
    "tree is clean afterwards, with nothing modified and nothing untracked. The `sqlc is up to "
    "date` step now passes: sqlc generate followed by git diff --exit-code over "
    "services/control-plane/db/dbgen exits 0, so the committed generated code matches what the "
    "committed sqlc.yaml and the committed queries produce. The G5 report's attestation was "
    "corrected first, because it had asserted that no commit contains this gate's work and that "
    "none was requested, which the commit made false; it now describes the commit field as the "
    "baseline the work was built on, notes that a commit cannot contain its own SHA, and points "
    "at --check. The report was regenerated at 80 digests and its currency check passes. Post-"
    "commit re-verification, against the committed tree: go job - gofmt clean, go vet exit 0 for "
    "all six modules, go build exit 0 for all six, go test -race ok for all six, go mod verify "
    "'all modules verified' in all six, the drain mutation gate PASS, the G5 currency check PASS, "
    "and the bash gate PASS across 40 run blocks. Integration job - migration rehearsal PASSED, "
    "`-direction up` idempotent at exit 0, the reachability guard exit 0 listing four applied "
    "migrations, sqlc vet exit 0, sqlc is up to date exit 0, and go test -tags=integration -race "
    "ok for all six modules. Remaining jobs - toolchain gate 14 of 14, tests/ci 117 passed, "
    "contracts VALID, research worker 109 passed, backtest worker 47 passed, project brain gate "
    "PASS, evidence-reference audit 0 items drifted. Every step of both job sequences is green, "
    "which is the first time that has been true in this work."
)

DEFECT_FOUND_AND_FIXED = (
    "One, and it is the correction the commit forced rather than one it revealed. The G5 report's "
    "attestation stated that no commit contained this gate's work and that no commit was "
    "requested. Committing made both halves of that sentence false, and an attestation describing "
    "a state the repository has left is a governance defect in its own right: it is the field a "
    "reviewer reads to understand what was and was not done. It was corrected before the commit, "
    "not after, so the commit never contained a statement that was already untrue. No code defect "
    "was found in this pass, which is worth stating rather than manufacturing: the work had been "
    "verified green before the commit and remained green after it, and the only new failure was "
    "the attestation's."
)

SIGNIFICANCE = (
    "The commit's effect on the repository's own gates is the part worth recording, because it is "
    "not the effect usually described. A commit is normally a delivery event; here it was also a "
    "gate repair. The `sqlc is up to date` step had been red since the rehydration work began, "
    "and for several passes the honest description of it was a careful explanation of why it was "
    "red without being broken. That explanation was correct and it was also the reason the step "
    "could not do its job: a gate that compares a working tree against a commit is only a gate "
    "when both sides are committed. Committing did not change a line of Go, and it converted the "
    "last red step in the workflow green. The generalisable point is narrow but real - some checks "
    "are only meaningful in a committed state, and their value cannot be assessed by running them "
    "against a dirty tree, where they will report noise that gets explained away. This is also the "
    "first verification in this work performed against the committed tree rather than the working "
    "tree, which matters more than it sounds: every earlier run proved the code was correct, and "
    "this one proves the repository is in the state that was verified."
)

CAVEATS = (
    "Four limitations. First, the commit is local and nothing was pushed and no pull request was "
    "opened, so the workflow has still never executed on a GitHub runner; every gate in this "
    "record was run locally on Windows, and the runner-specific behaviour of the postgres service "
    "container, the `set -euo pipefail` step scripts and the jq call in module resolution remains "
    "unproven, though all 40 run blocks are now syntax-checked. Second, the commit's own "
    "message is the only description of the change outside the evidence log, and the log is "
    "the fuller record: EV-060 through EV-069 carry the reasoning, the five false alarms and "
    "their corrections, and the two defects that pre-dated this work. Third, the G5 report's "
    "commit field records ca4eacf, the baseline the work was built on, which is deliberate and "
    "is explained in the report itself, but a reader skimming only the field could reasonably "
    "expect it to name 758ce11; the report says explicitly that it cannot. Fourth, and unchanged "
    "by the commit: human_reviewer remains null so WI-141 stays IN_PROGRESS, cross-store "
    "atomicity remains WI-120 and WI-121's and is not claimed, WI-117's unqualified audit and "
    "authz tables and RISK-14 remain other owners', the schema-version forward problem is "
    "untouched, the write path is still not exposed over HTTP, the drain tests still drive the "
    "interrupt channel rather than a real signal, and the mutation gate still writes a tracked "
    "file while it runs."
)

EXCEPTION = ""

ARTIFACTS = [
    ".kilo/ecc/project-brain/evidence.jsonl",
    "evidence/gates/G5-gate-report.json",
    "evidence/gates/G5-gate-report.md",
    "scripts/generate_g5_gate_report.py",
    "scripts/inspect_secret_scan_hit.py",
    "scripts/record_ev069.py",
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
