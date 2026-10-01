"""One-off: append EV-059.

Corrects a claim this work item has repeated since EV-046. The limitation was described as an
outstanding gap that a driver would close. It is not: it is a deliberate, documented, enforced
supply-chain decision, taken twice, whose alternatives are recorded and whose switching is
reserved to the project owner.

Idempotent, append-only, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-059"
STAMP = "2026-10-01T06:32:00Z"

WORK_ITEM = "WI-141"

CLAIM = (
    "The limitation every record since EV-046 has carried - that no Go process has connected to "
    "PostgreSQL - has been described as a gap a driver would close. It is not a gap. It is a "
    "deliberate, enforced architectural position, decided at least twice, with the code that "
    "would need the driver complete, reviewed, and parked. The Go control plane cannot reach "
    "PostgreSQL in production however it is wired, and that is the current design rather than an "
    "omission. The G5 report's G5.7 criterion is corrected accordingly, and the remaining work on "
    "this item is blocked on a policy decision reserved to the project owner."
)

METHOD = (
    "Checked whether the new composition root was actually enforced before looking for further "
    "work, and in the course of it read CI end to end rather than the parts that had failed "
    "before. Two useful facts: the go job enumerates modules dynamically from go.work and runs "
    "go test -race ./..., so the new package is covered by build, vet and tests without any edit; "
    "and an integration job runs go test -tags=integration, which no Go file declares a tag for, "
    "so it presently re-runs the same suite. Following the integration job to its migration step "
    "surfaced a comment stating that no Go driver can be added, and citing a parked store. "
    "Verified that from three independent directions rather than trusting the comment: the CI "
    "comment itself, the parked store's README, and the pseudo-version rule inside "
    "verify_toolchain.py."
)

RESULT = (
    "verify_toolchain.py refuses a pseudo-version reference as an unpinned one, on the stated "
    "ground that a v0.0.0-... version does not correspond to a tagged release. pgx v5.11.0 pulls "
    "github.com/jackc/pgservicefile, whose only two available versions are both pseudo-versions, "
    "so pgx cannot satisfy the gate. The consequence is stronger than a missing test: the Go "
    "modules carry zero external dependencies and no go.sum in any module, which the parked store "
    "itself flags as a supply-chain posture worth noticing before it changes. docs/00 names the "
    "stack as 'Go, Chi, pgx, sqlc', so pgx is the documented intent; the code needing it exists - "
    "migrate.PgStore and cmd/migrate are complete and reviewed and sit at "
    ".kilo/ecc/project-brain/evidence/wi-106/parked-pgx-store. WI-106 set out three ways forward: "
    "allowlist the pseudo-version, keep Go driver-free, or vendor the driver. It took the "
    "second, because it is the only option requiring no change to an existing control, recorded "
    "that switching is the project owner's call, and verified that reverting the dependency "
    "restored the toolchain gate. G5.7 in the G5 report now states this rather than describing "
    "the decision as merely pending. 58 artifacts, all digests re-verified, 16 cited test names "
    "all present, all 13 gates pass."
)

DEFECT_FOUND_AND_FIXED = (
    "One, in a claim repeated across many records rather than in the code. Since EV-046 this "
    "work item has described the absence of a Go PostgreSQL driver as an open limitation with an "
    "obvious remedy - add the driver, exercise the SQL layer against a live database. EV-058 "
    "sharpened that to 'a dependency decision rather than a missing test', which was still wrong: "
    "it is not an unmade decision but a made one, taken with reasoning, alternatives recorded, and "
    "an enforcement mechanism. Saying 'a decision' implied it was open and available, and would "
    "have invited exactly the unilateral addition of pgx that WI-106 explicitly declined to make "
    "for itself. Corrected in the G5 report's G5.7 detail and verdict basis. No product code "
    "changed; no test changed behaviour."
)

SIGNIFICANCE = (
    "The transferable point is the difference between an unverified item and an unverifiable one, "
    "which EV-056 raised about Docker and which now recurs at a deeper level. Docker was blocked "
    "for an hour because I misread a rule; the driver was carried as a caveat for thirteen "
    "evidence records because I never asked whether the limitation was a decision. Both had the "
    "same shape: a limitation recorded in prose, repeated until it read as background, and never "
    "checked against the repository's own stated position. Reading CI end to end rather than "
    "reacting to the failing part is what found it, and it is the cheapest possible check - the "
    "answer was already written in a comment in a file I had run dozens of times. The second "
    "point is that this is now the honest terminus of WI-141. Its acceptance criteria are "
    "verified, its gate report is written, and its one unmet criterion is blocked on a "
    "supply-chain policy choice between allowlisting a pseudo-version, vendoring a driver, or "
    "keeping Go driver-free. None of the three is a technical difficulty; all three are the "
    "project owner's, and a work item should not make that choice for itself."
)

CAVEATS = (
    "Four limitations. First, this record establishes that the driver gap is a deliberate position; "
    "it does not argue the position is correct. Allowing the pseudo-version is the narrowest "
    "change and has a real argument behind it, since a pseudo-version is an immutable commit hash "
    "rather than a moving reference, and vendoring would end the supply-chain event entirely at "
    "the cost of repository size. Keeping Go driver-free is defensible while the persistence layer "
    "stays unreachable, and less so once the architecture depends on it; that tension is the "
    "owner's to resolve and is stated here rather than argued. Second, WI-141's acceptance "
    "criteria are unaffected and remain verified, and this record changes none of them; what "
    "changes is only the accuracy of a limitation stated thirteen times. Third, the composition "
    "root added in EV-058 is correct and tested, but it composes over ports whose SQL "
    "implementations cannot be reached in production, so its production value is currently "
    "latent rather than realised; that is a consequence of this record's finding and not a defect "
    "in it. Fourth, unchanged: atomicity between audit acceptance and registry persistence remains "
    "WI-121's; the EV-048 schema-version forward problem remains unresolved and human-owned; the "
    "unqualified audit and authz tables that the parked store's related finding leaves open remain "
    "WI-117's; RISK-14's six deferred scaling findings are open; no specification file was "
    "modified; docs/ remains clean at zero changes; nothing was staged; and nothing was committed. "
    "WI-141 remains IN_PROGRESS, the G5 verdict remains FAIL, and this record attests to neither."
)

EXCEPTION = ""

ARTIFACTS = [
    "evidence/gates/G5-gate-report.json",
    "evidence/gates/G5-gate-report.md",
    "scripts/generate_g5_gate_report.py",
    "scripts/record_ev059.py",
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