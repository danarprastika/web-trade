"""One-off: append EV-028 and close WI-111.

Follows the same pattern as scripts/record_ev026.py and record_ev027.py: idempotent,
auditable, and kept in the repository so the Project Brain edit is reproducible rather than
an opaque mutation of state.

It writes JSON without a BOM on purpose. PowerShell 5.1 `Set-Content -Encoding UTF8` adds
one, and a BOM at the start of a JSONL line corrupts the record it introduces.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-028"
STAMP = "2026-09-29T05:05:00Z"

CLAIM = (
    "Identity and authorization context enforcement is implemented in "
    "services/control-plane/authz as a Go domain package, and the same role-exclusion matrix, "
    "session lifetimes, and exact-diff approval rules are enforced independently by "
    "db/migrations/0003_authz.sql. Every command is bound to the actor on its "
    "contracts.CommandEnvelope, so authorization cannot be evaluated for one identity and the "
    "command executed as another. Both halves are proven by tests that fail when the control is "
    "broken, not by inspection."
)

METHOD = (
    "Read docs/21 sections 2 through 10 for session classes, phishing-resistant MFA, deny by "
    "default, the role exclusion matrix, exact-diff approval, break-glass, and the policy-bundle "
    "recording requirement, docs/06 for authenticated identity, and ADR-017 and ADR-018 for the "
    "separation of duties and the rule that authorization cannot approve financial risk. "
    "Implemented the Go package across the closed action and role sets, the role exclusion "
    "matrix, scope and grant currency, session classes and step-up, the policy bundle and "
    "evaluator, and exact-diff approval. Wrote a structural test asserting the package cannot "
    "import the Risk Engine, the OMS, the ledger, or any I/O package, since the risk boundary is "
    "only real if it is structural. Wrote the negative policy vectors as reviewable data in "
    "vectors_test.go. Then deliberately mutated the implementation in four ways and confirmed the "
    "suite caught each: dropping the wildcard widening in Scope.Covers, removing the "
    "non-human-impersonation check, removing the command-ID binding, and making the evaluator "
    "read the subject from a handler-supplied field instead of the envelope. Finally wrote the "
    "PostgreSQL migration with 54 assertions and a mutation harness that removes eight database "
    "controls in turn and requires the assertion set to go red for each."
)

RESULT = (
    "Authorization package: 87.2% statement coverage, go test -race -count=1 clean, go vet "
    "clean, gofmt clean. Database: ALL 54 DATABASE ASSERTIONS PASSED against PostgreSQL 17.11, "
    "and scripts/verify_authz_mutation.py reports all 8 mutations detected, so the suite is "
    "proven to distinguish a working guard from an absent one. Full repository gate: toolchain "
    "14/14 PASS, project brain PASS, tests/ci 100 passed, workers/research/tests 35 passed, "
    "docs/ clean with all manifest digests verifying. G0 mechanical verification remains 7/7 "
    "PASS with G0.8 REQUIRES_HUMAN_ATTESTATION and the overall verdict "
    "PENDING_HUMAN_ATTESTATION, unchanged by this work item."
)

DEFECT = (
    "Five defects were found and fixed, none of which was visible from reading the code. "
    "First, Scope.Covers compared scope entries literally, so a wildcard grant covered nothing: "
    "wildcards were simultaneously unusable and, per docs/21 section 4, prohibited for live "
    "financial operations. Wildcard is now grant-side widening and the request stays literal. "
    "Second, nothing stopped a SERVICE or AGENT subject exercising an OWNER grant, so a workload "
    "could impersonate a human; humanOnlyRoles is now a property of the role rather than of the "
    "policy bundle, so no policy edit can route a workload through an operator role. Third, and "
    "most seriously for the claim being made, the AC5 negative vector suite originally asserted "
    "only that a request was refused. Under both of the first two mutations it stayed green, "
    "because an unrelated check happened to catch the same request: the suite was reporting "
    "broken controls as working ones. Every vector now asserts the specific Refusal code and the "
    "harness reports expected-versus-actual, after which the mutations are caught. Fourth, "
    "authz.Request carried its own SubjectID and SubjectType, independent of the envelope's "
    "ActorID and ActorType, so AC1 was not actually satisfied: a command could execute as one "
    "identity while authorization was evaluated for another. AuthorizeCommand now reads the "
    "subject from the envelope and CommandDecision binds the permission to that envelope. Fifth, "
    "authz_check_approval_immutability in the migration was a BEFORE UPDATE trigger returning "
    "NULL, which tells PostgreSQL to skip the update silently rather than refuse it: recording "
    "an approval's application was a no-op that raised nothing, the column stayed NULL, and the "
    "row remained re-appliable forever. A guard that silently discards the write it was meant to "
    "permit is worse than one that refuses it, because the caller believes the approval was "
    "consumed. It now returns NEW."
)

SIGNIFICANCE = (
    "Three of the five defects are the kind that survive a green suite. The negative vector "
    "suite is the general lesson and it is worth carrying to the other work items: a negative "
    "test that asserts only that something was refused will keep passing after the control it "
    "was written for has been deleted, because some other check usually catches the same request "
    "anyway. The suite has to assert why. The envelope binding is the difference between AC1 "
    "being true and AC1 being claimed: 'every command is evaluated server-side' is not a "
    "property of a correct evaluator, it is a property of the evaluator being the only path from "
    "an envelope to an execution. The silent-skip trigger is the database equivalent of the same "
    "class of bug and would not have been found by reading the migration. Three harness defects "
    "were also found and fixed: deferred constraint triggers fired at COMMIT outside the "
    "attempt helper's subtransaction and aborted the whole script, reporting zero assertions "
    "from a migration that was almost entirely working; the migration's prose comments contain "
    "sentence-ending semicolons, so a VALUES(.*?); pattern matched a comment rather than the "
    "rows and reported every session class missing from a table that had all three; and the "
    "verdict was emitted as a NOTICE, which PostgreSQL sends to stderr while the harness reads "
    "stdout, so a fully passing migration looked like it had produced no summary at all. That "
    "last one is worth noting beyond this work item: a harness that reports 'no summary' for "
    "'passed everything' is indistinguishable, from outside, from a broken migration."
)

CAVEATS = (
    "The exclusion matrix and the session-class timeout table are deliberately duplicated "
    "between Go and SQL, because a database guard generated from Go would be unenforceable by "
    "anyone editing a bundle by hand. The cost of that duplication is drift, so "
    "sql_contract_test.go compares the two copies pairwise in both directions and the session "
    "timeouts numerically; that test is the only thing standing between a control that exists "
    "in one layer and a control that exists in both. There is no HTTP layer in the control "
    "plane yet, so AuthorizeExecutor is a value a handler must hold rather than middleware, "
    "which makes skipping it a compile error but does not yet prove any particular transport "
    "calls it. The policy bundle table stores rules as jsonb and the exclusion trigger reads "
    "the rule shape, so a change to the canonical rule serialization must update both. "
    "verify_ledger_db.py reports the server version as 'unknown' on this host; that cosmetic "
    "reporting defect is pre-existing from WI-116 and is not fixed here. The database assertion "
    "harness retries a run that produced no summary, because container startup is occasionally "
    "slow enough to exhaust the readiness probe, and a mutation that cannot be run is reported "
    "as inconclusive rather than as undetected so that a flake is never mistaken for a verdict. "
    "No live venue connectivity, production credentials, or Terraform was involved. G0.8 human "
    "attestation remains outstanding. No commit has been made."
)

RECORD = {
    "schema": "ecc.project-brain/evidence/v7",
    "evidence_id": EVIDENCE_ID,
    "recorded_at": STAMP,
    "recorded_by": "team-lead",
    "work_item": "WI-111",
    "claim": CLAIM,
    "status": "RESOLVED",
    "method": METHOD,
    "result": RESULT,
    "defect_found_and_fixed": DEFECT,
    "significance": SIGNIFICANCE,
    "caveats": CAVEATS,
}

EVENT = {
    "schema": "ecc.project-brain/event/v7",
    "event_id": "EVT-WI-111-COMPLETED",
    "recorded_at": STAMP,
    "recorded_by": "team-lead",
    "work_item": "WI-111",
    "event": "work_item_completed",
    "status": "COMPLETED",
    "evidence_ref": EVIDENCE_ID,
    "summary": (
        "WI-111 Identity and authorization context enforcement completed. Authorization package at "
        "87.2% coverage with all four deliberate implementation mutations caught; 54 of 54 "
        "authorization database assertions pass against real PostgreSQL 17.11 and all 8 deliberate "
        "database mutations are detected; full repository gate green with the spec gate "
        "mechanically complete and G0.8 outstanding. Five defects fixed, including a negative "
        "test suite that reported broken controls as working ones and a BEFORE UPDATE trigger "
        "that silently discarded the write it was meant to permit."
    ),
}


def append_jsonl(path: Path, obj: dict) -> None:
    with io.open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(obj, ensure_ascii=True) + "\n")


def main() -> int:
    evidence_path = BRAIN / "evidence.jsonl"
    existing = [
        json.loads(line)
        for line in io.open(evidence_path, encoding="utf-8").read().splitlines()
        if line.strip()
    ]
    if any(r.get("evidence_id") == EVIDENCE_ID for r in existing):
        print(f"{EVIDENCE_ID} already recorded; nothing appended.")
    else:
        append_jsonl(evidence_path, RECORD)
        print(f"appended {EVIDENCE_ID} to {evidence_path.name}")

    work_path = BRAIN / "work-items.json"
    doc = json.loads(io.open(work_path, encoding="utf-8").read())
    changed = False
    for item in doc["items"]:
        if item["id"] == "WI-111":
            # evidence_ref is a list: the gate iterates it, so a bare string would be
            # read one character at a time as several unknown evidence ids.
            if item.get("status") != "COMPLETED" or item.get("evidence_ref") != [EVIDENCE_ID]:
                item["status"] = "COMPLETED"
                item["evidence_ref"] = [EVIDENCE_ID]
                item["completed_at"] = STAMP
                changed = True
    if changed:
        io.open(work_path, "w", encoding="utf-8", newline="\n").write(
            json.dumps(doc, indent=2, ensure_ascii=True) + "\n"
        )
        print("WI-111 -> COMPLETED")
    else:
        print("WI-111 already COMPLETED")

    events_path = BRAIN / "events.jsonl"
    seen = [
        json.loads(line)
        for line in io.open(events_path, encoding="utf-8").read().splitlines()
        if line.strip()
    ]
    if any(e.get("event_id") == EVENT["event_id"] for e in seen):
        print(f"{EVENT['event_id']} already recorded; nothing appended.")
    else:
        append_jsonl(events_path, EVENT)
        print(f"appended {EVENT['event_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
