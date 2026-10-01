"""One-off: append EV-056.

EV-055 recorded that five project gates could not run because the Docker daemon was down. This
records that they did run, and pass. Short by design: it changes a verification status, not a
claim about the code, and EV-055's caveat about the Go/PostgreSQL boundary still stands.

Idempotent, append-only, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-056"
STAMP = "2026-10-01T02:26:00Z"

WORK_ITEM = "WI-141"

CLAIM = (
    "The five gates EV-055 recorded as unrunnable were run, and all thirteen pass against a live "
    "PostgreSQL. This changes no code and no claim about the code; it closes a verification "
    "status that EV-055 left open, so that a reviewer reading the record is not left believing "
    "five gates are unverified."
)

METHOD = (
    "EV-055 declined to start Docker Desktop, citing the shell rule against Start-Process and "
    "backgrounding patterns. That reasoning was too broad: the rule is about launching processes "
    "detached from the session, and the harness provides a sanctioned tool for long-running "
    "services, which a container daemon is. Started the daemon through it, polled for the server "
    "to answer rather than assuming it had, and re-ran the full gate set unchanged."
)

RESULT = (
    "All 13 gates pass. The five previously blocked gates now report real results rather than a "
    "skip: db-0001-ledger 18 assertions, db-0002-audit 20, db-0003-authz 54, db-0004-model-registry "
    "45, for 137 database assertions executed against a running PostgreSQL, and "
    "migration-rehearsal passed by migrating up, down to a clean catalog, and up again. The other "
    "eight are unchanged and still pass."
)

DEFECT_FOUND_AND_FIXED = (
    "None in the product. The defect was in my own reasoning in EV-055: I read a rule about "
    "detaching processes from a session as a rule against starting a service, and reported a "
    "verification gap as environmental when the sanctioned tool for exactly that job was "
    "available and unused. The cost of that error was real - an hour of gate coverage that had "
    "been available the whole time, and a caveat that would have been read by a reviewer as a "
    "limitation of the work rather than of the harness."
)

SIGNIFICANCE = (
    "EV-051 caught a harness that scored a build failure as a detected mutant, EV-053 caught a "
    "build-failure guard with the same flaw, and EV-054 caught a probe whose finding I nearly "
    "reported without reading the code that refuted it. This is the fourth instance of one shape: "
    "the check reports a result, and the result is wrong for a reason that has nothing to do with "
    "the thing being checked. A gate that cannot run and a gate that has not been run look "
    "identical from the outside, and reporting one as the other is the error - not the "
    "environment. The general lesson is that an unverified item is not the same as an "
    "unverifiable one, and the discipline is to exhaust the available means before writing either "
    "into a permanent record."
)

CAVEATS = (
    "Three limitations, unchanged by this record. First, and the one that matters: no Go process "
    "has connected to PostgreSQL, so the refusal, resolution, and rehydration paths still have "
    "never run against a live timestamptz or a real transaction. The database gates exercise the "
    "schema through their own harness; the Go persistence layer is verified by sqlc "
    "type-checking and by sqlc-vet, which proves the generated code matches the queries and not "
    "that it behaves correctly against a live database. EV-055's boundary stands and this record "
    "does not move it. Second: starting the Docker daemon is a host-level change and the daemon "
    "is still running under session lifetime, so it will stop when this session ends; the gates "
    "are reproducible but not permanently enabled. Third, unchanged: no composition root "
    "constructs any rehydrated object, so rehydration is still explicit rather than automatic; "
    "atomicity between audit acceptance and registry persistence remains WI-121's; the EV-048 "
    "schema-version forward problem remains unresolved and human-owned; RISK-14's six deferred "
    "scaling findings are open; no specification file was modified; docs/ remains clean at zero "
    "changes; nothing was staged; and nothing was committed. WI-141 remains IN_PROGRESS pending "
    "human G4 review."
)

EXCEPTION = ""

ARTIFACTS = [
    "scripts/record_ev056.py",
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