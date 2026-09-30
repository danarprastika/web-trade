"""One-off: append EV-031 and record WI-118 as BLOCKED.

WI-118 is a gate report, and the report's verdict is FAIL. That is not a shortfall in the
verification; it is the result of it. docs/11_EXECUTION_GATES.md states that a gate is PASS
only when every listed criterion is satisfied and that partial completion is FAIL, not a
percentage. All nine mechanical criteria of G1 hold, but two of the six fields the same
document requires in every gate report cannot be produced by an automated agent: a named
human reviewer, and a commit that contains the work. Recording this item as COMPLETED would
contradict the report it points at, so it is recorded as BLOCKED with the blocker stated and
the mechanical results preserved alongside it.

Idempotent and auditable, like record_ev026.py through record_ev030.py, and written without a
BOM because a BOM at the start of a JSONL line corrupts the record.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-031"
STAMP = "2026-09-29T11:15:00Z"

BLOCKER = (
    "Two of the six fields docs/11_EXECUTION_GATES.md requires in every gate report cannot be "
    "produced by an automated agent, and docs/11 forbids partial completion. (1) reviewer: a "
    "named human reviewer; an automated agent recording itself as the reviewer would satisfy "
    "the field and none of its purpose, and the same package already treats an unattested "
    "specification as not passed at G0.8. (2) commit: HEAD is 15d978ff5658c0646a63ce5ecc74b"
    "998e8bc05a4, but 23 paths in the working tree are untracked or modified, including every "
    "Go source and migration this gate covers, so the referenced commit does not contain the "
    "work being certified. No commit was requested or made. Both are cleared by human action: "
    "commit the work, then have a named reviewer attest."
)

CLAIM = (
    "All nine mechanical criteria of the G1 domain-foundation gate in docs/11 hold against the "
    "repository, each verified by running a command rather than by inspecting an artifact: "
    "canonical IDs, timestamps, money and quantity types, errors, envelopes, idempotency, "
    "configuration boundaries, migrations, and domain tests. 801 tests report PASS across six "
    "Go modules. The gate report itself is complete in every field that can be produced "
    "mechanically, including per-criterion command output and SHA-256 digests of every "
    "artifact. The gate verdict is nevertheless FAIL, because the reviewer and commit fields "
    "are outstanding and the specification forbids recording a gate as passed on partial "
    "completion."
)

METHOD = (
    "Read docs/11_EXECUTION_GATES.md for the G1 criteria and the report fields, rather than "
    "deriving them from the work item text, and mapped each of the nine criteria onto the "
    "artifacts that implement it: contracts/go for canonical IDs (Identifier), timestamps "
    "(Timestamp), money and quantity (Money, Quantity, Decimal), errors (ErrorCode, "
    "ContractError) and envelopes (CommandEnvelope, EventEnvelope); contracts/go/envelope.go "
    "plus components/oms and services/control-plane/ledger plus the unique index in "
    "0001_ledger.sql for idempotency; services/control-plane/config for configuration "
    "boundaries; services/control-plane/migrate with the real files in db/migrations for "
    "migrations; and every *_test.go in the workspace for domain tests. Wrote "
    "scripts/verify_gate_g1.py, in which no criterion is marked PASS by inspection: each names "
    "its artifacts, runs the command that exercises them, and inspects the real output. Each "
    "criterion carries the SHA-256 digest of every artifact and a roll-up digest over the set. "
    "Wrote scripts/mutation_check_gate_g1.py, which breaks one criterion's actual control and "
    "requires that criterion to report FAIL, restoring every file byte-for-byte. Then rendered "
    "the report as both JSON and Markdown, leading with the verdict and the reason for it."
)

RESULT = (
    "9 of 9 mechanical criteria PASS; overall gate verdict FAIL. Canonical IDs, timestamps, "
    "money/quantity, errors, envelopes, idempotency, configuration boundaries and migrations "
    "each verified by go test in the module that implements them. Domain tests: 801 tests "
    "report PASS, distributed contracts/go 90, components/oms 91, components/risk-engine 136, "
    "services/control-plane 484, and zero in components/reconciliation and adapters/venues. "
    "The two zeroes are reported as declared placeholders rather than hidden: both modules "
    "contain only a doc.go package comment and no implementation, and adapters/venues names G8 "
    "in its own package documentation, so their implementation belongs to WI-131 and WI-132 "
    "rather than to G1. scripts/mutation_check_gate_g1.py reports all 4 criteria detecting "
    "their failure: a float32 introduced into Money, contracts/go/identifier.go deleted, "
    "config/sign.go deleted, and the 0002_audit.sql down body emptied. Report written to "
    ".kilo/ecc/project-brain/evidence/wi-118/G1-gate-report.md and g1-gate-report.json."
)

DEFECTS = (
    "Three defects were found in the gate verifier itself, all of which had produced a "
    "misleading reading. First, the package counter searched for output lines that *end* with "
    "'ok' when go test prints 'ok  <package>  <elapsed>', so it reported '0 package(s) ok' for "
    "every module that was in fact passing. Every criterion's evidence line therefore read as "
    "though nothing had run, in a document whose entire purpose is to show what ran. The count "
    "now keys on the line prefix. Second, the domain-test criterion required every module to "
    "report a passing test, which failed components/reconciliation and adapters/venues. The "
    "first reading of that was a genuine gap; the second was not. Both modules contain only a "
    "package comment, and adapters/venues documents its own scope as G8, so demanding tests "
    "of them under G1 was the criterion over-reaching rather than the modules being untested "
    "by neglect. The check is now structural rather than a hardcoded list: a module with no "
    "passing test passes only if it contains no implementation file beyond doc.go, and it is "
    "reported as a placeholder with a digest, so the next person to add reconcile.go without "
    "a test fails this gate automatically. Third, a mutation in the mutation harness preserved "
    "the down body it was meant to remove, by re-appending the original tail after the marker, "
    "and so reported the migrations criterion as undetected when nothing had actually been "
    "broken. The harness had reported a MISSED for a criterion that was in fact sound, which is "
    "the failure mode worth naming: a check that reports failure for the wrong reason is "
    "indistinguishable, from the outside, from a real finding, and would have sent the next "
    "person to re-audit a criterion that needed no work."
)

SIGNIFICANCE = (
    "The general point is the one this gate exists to police, applied to the gate itself. A "
    "green report and a hollow report are the same document when the only evidence is the word "
    "PASS, so every criterion here names the command that produced it and every criterion was "
    "shown to go red when its control was removed. The placeholder rule is worth carrying "
    "forward for the same reason: classifying an untested module requires asking whether it "
    "holds implementation, not whether its name appears in a list, and either answer has to be "
    "visible in the report."
)

CAVEATS = (
    "The gate cannot be recorded as PASS, and this item is therefore BLOCKED rather than "
    "COMPLETED. The outstanding fields are the reviewer and the commit, both of which need "
    "human action: commit the working tree, then have a named reviewer attest to the report. "
    "The evidence status is PARTIALLY_VERIFIED for the same reason, which is the accurate "
    "description of nine verified criteria attached to a report that is not a pass. Four further "
    "limitations are worth stating. The criterion for timestamps checks both that the canonical "
    "layout is present in the source and that the UTC rejection is expressed, alongside running "
    "the tests; it does not attempt to prove the canonical form against an external "
    "specification, because no such document is referenced by docs/11 for that detail. The "
    "money, errors, envelope, and configuration evidence lines are descriptions of what the "
    "named test files cover rather than restatements of each assertion, so a reader who wants "
    "the per-assertion detail must read the test files named in the artifact list. The "
    "migrations criterion verifies reversibility, explicit transaction wrapping, and the "
    "absence of DROP in an up body through real_migrations_test.go against the repository's own "
    "files, but the live apply, revert, and re-apply rehearsal against a real PostgreSQL 17 is "
    "EV-029 and is not re-run here. The domain-test criterion counts tests that report PASS; "
    "it does not assert a coverage threshold, because docs/11 does not specify one for G1 and "
    "inventing one would be a criterion the specification does not contain. No specification "
    "file was modified, docs/ remains clean and all manifest digests still verify, G0.8 human "
    "attestation remains outstanding, and no commit has been made."
)

ARTIFACTS = [
    "scripts/verify_gate_g1.py",
    "scripts/mutation_check_gate_g1.py",
    ".kilo/ecc/project-brain/evidence/wi-118/G1-gate-report.md",
    ".kilo/ecc/project-brain/evidence/wi-118/g1-gate-report.json",
]

RECORD = {
    "schema": "ecc.project-brain/evidence/v7",
    "evidence_id": EVIDENCE_ID,
    "recorded_at": STAMP,
    "recorded_by": "team-lead",
    "work_item": "WI-118",
    "claim": CLAIM,
    "status": "PARTIALLY_VERIFIED",
    "method": METHOD,
    "result": RESULT,
    "defect_found_and_fixed": DEFECTS,
    "significance": SIGNIFICANCE,
    "caveats": CAVEATS,
    "exception": BLOCKER,
    "artifacts": ARTIFACTS,
    "supersedes": [],
}

EVENT = {
    "schema": "ecc.project-brain/event/v7",
    "event_id": "EVT-WI-118-BLOCKED",
    "recorded_at": STAMP,
    "recorded_by": "team-lead",
    "work_item": "WI-118",
    "event": "work_item_blocked",
    "status": "BLOCKED",
    "evidence_ref": EVIDENCE_ID,
    "summary": (
        "WI-118 G1 domain foundation gate report produced. All 9 mechanical criteria verified by "
        "running their commands, 801 tests PASS across six Go modules, and all 4 criteria shown "
        "to go red when their control is removed. Gate verdict is FAIL, not PASS: the reviewer "
        "and commit fields required by docs/11 are outstanding, and docs/11 forbids recording a "
        "gate as passed on partial completion. HEAD does not contain the work being certified "
        "and 23 paths are untracked, and a named human reviewer cannot be produced by an agent. "
        "Cleared by committing the working tree and obtaining a named reviewer's attestation. "
        "Three defects fixed in the verifier, including an evidence line that read '0 package(s) "
        "ok' for passing modules and a mutation that reported a criterion as undetected without "
        "having broken it."
    ),
}


def append_jsonl(path: Path, record: dict) -> None:
    with io.open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=True) + "\n")


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
        if item["id"] == "WI-118":
            desired = {
                "status": "BLOCKED",
                "evidence_ref": [EVIDENCE_ID],
                "blocker": BLOCKER,
                # The mechanical results are preserved on the item itself, so a resume that
                # reads only work-items.json still learns that nine criteria hold and that
                # only the two human-dependent fields are outstanding.
                "partial_results": (
                    "9 of 9 G1 mechanical criteria verified; 801 tests PASS across six Go "
                    "modules; 4 of 4 criteria proven to fail when their control is removed. "
                    "Gate verdict FAIL pending the reviewer and commit fields."
                ),
            }
            for key, value in desired.items():
                if item.get(key) != value:
                    item[key] = value
                    changed = True
    if changed:
        io.open(work_path, "w", encoding="utf-8", newline="\n").write(
            json.dumps(doc, indent=2, ensure_ascii=True) + "\n"
        )
        print("WI-118 -> BLOCKED")
    else:
        print("WI-118 already BLOCKED")

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
