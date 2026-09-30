"""One-off: append EV-037 recording the WI-141 G5 model governance implementation.

Records four acceptance criteria as verified, and records the five defects the work
surfaced, four of which were in production code and one of which was a contract mismatch
between the two languages that would have surfaced only at integration.

Idempotent, append-only, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-037"
STAMP = "2026-09-29T16:58:00Z"

WORK_ITEM = "WI-141"

CLAIM = (
    "Gate G5's four components operate with complete audit trails and three of the four "
    "acceptance criteria are verified against a mutation-checked suite. A Go model registry "
    "at services/control-plane/model implements the docs/07 lifecycle as a closed declared "
    "state machine, the required model record, separation of duties, an explicit tool "
    "allowlist, a decision ledger, drift monitoring, and the four-action compromise "
    "response. A Python lineage proposal in workers/research lets the research worker assert "
    "what it built while holding no authority over whether it is registered."
)

METHOD = (
    "Read docs/07 in full, docs/11 gate G5, and the docs/25 sections 5 and 6 matrix rows for "
    "AI/model governance, zero trust, and granular authorization, and the failure-mode row for "
    "a compromised registry or research worker. Read services/control-plane/strategy/"
    "lifecycle.go and contracts/go as the existing patterns to extend rather than invent: the "
    "strategy lifecycle already establishes the shape this package follows, and contracts/go "
    "already reserves PrefixModel. Confirmed the model package is reached by the "
    "go-test-control-plane gate by running the gate's own command with go list ./... rather "
    "than assuming that a new package under an existing module is covered. Wrote the package "
    "as six files, then the tests, then mutation-tested with scripts/mutation_check_model.py."
)

RESULT = (
    "services/control-plane/model holds record.go (the eleven required record fields, "
    "digest validity, a closed required-field sweep), lifecycle.go (the nine documented "
    "states plus QUARANTINED, seventeen declared edges, VerifyDeclaration), tools.go "
    "(allowlist construction, the financial-on-direct-path refusal, revocation), decision.go "
    "(lineage validation and the ledger authority assertion), monitoring.go (the seven "
    "docs/07 signals with mandatory automatic pause), and compromise.go (the four required "
    "actions). workers/research gains lineage.py with LineageProposal, RetrievalRecord, "
    "ToolCallRecord, and build_proposal, plus content_address.hex_digest. AC1 registry, "
    "audit events, and idempotency scopes: verified. AC2 no model authorizes its own "
    "execution: verified, including that omitting the record does not skip the check. AC3 "
    "tool permission-denial, model rollback, and lineage: verified. AC4 compromised worker: "
    "all four actions verified. 89 tests in the model package and 109 in the research worker, "
    "ruff clean and mypy --strict clean on the worker, go vet clean, gofmt clean, and all 12 "
    "release gates PASS. Sixteen mutations were applied to the model package, sixteen were "
    "detected, zero survived, zero were skipped, and every file was restored byte-for-byte."
)

DEFECTS = (
    "Five defects, four in production code and one a cross-language contract mismatch. "
    "First, and the most serious: the transition table declared the quarantine command on "
    "eight edges, but the request lookup was keyed by command alone into a single-valued "
    "map, so only the last edge survived. A request to quarantine a model in REGISTERED was "
    "then rejected as though the command did not belong to the claimed state. The consequence "
    "was silent and inverted: quarantine would have failed from seven of eight states, and a "
    "compromised model sitting in one of them would have remained promotable, which is exactly "
    "the failure docs/25 section 6 is written against. The table was correct, the comment "
    "explained why the edges existed, and the code compiled. The fix introduced a named "
    "transitionKey and a (state, command) lookup, and a MultiSource flag that VerifyDeclaration "
    "requires to be consistent across every edge of a command. Second, QuarantineRequest was "
    "written against the old single-source lookup and broke when the first fix landed; it also "
    "guessed the source state, which its own doc comment said it must not, so it now takes the "
    "state from the caller and resolves the pair. Third, CommandClearQuarantine permitted a "
    "system actor, the inverse of the containment edge. A compromised workload could have "
    "scheduled its own restoration; recovery from a security incident is a human decision, and "
    "the clear path is now human-only and additionally requires an independent approver. "
    "Fourth, LineageProposal declared limitations as both a dataclass field and a property of "
    "the same name, so the property shadowed the field and proposal_digest raised a JSON "
    "serialisation error. Fifth, and the one that would have been found only at integration: "
    "the research worker names its artifacts with a sha256: prefix while the Go model.Digest "
    "accepts exactly 64 lowercase hex characters, so a research-produced dataset fingerprint "
    "would have been rejected by the registry that consumes it. The two languages disagreed "
    "about what a digest is. The fix is on the Python side, because the control plane is "
    "authoritative for the registry wire format and loosening a mutation-checked Go invariant "
    "to accommodate a worker's internal representation would have traded a real check for a "
    "cosmetic convenience. Three of these five were found by the tests written alongside the "
    "code, and the fourth and fifth by tests written to verify claims that turned out to be "
    "wrong."
)

SIGNIFICANCE = (
    "The first defect is the one worth carrying forward. It is a silent failure in the "
    "direction that matters: it made the containment path less effective, it did so for the "
    "majority of states, and every signal a reviewer would normally use was green - the table "
    "was right, the documentation was right, the build was right, and the code compiled. What "
    "caught it was VerifyDeclaration being run as a test over the table's own internal "
    "consistency, which is a check about the mechanism rather than about any behaviour, and "
    "therefore catches the case where the table is fine and the code reading it is not. That is "
    "the class of defect that a behavioural test suite structurally cannot find, because "
    "every behaviour in it was correct at the time it was written. The general form: when a "
    "specification lists N things that must each be possible, an assertion that the N things "
    "are individually well-formed is not sufficient, and the property to assert is the one "
    "that ranges over the N - here, that every non-terminal state can reach QUARANTINED. "
    "That is now both a VerifyDeclaration check and a test, and it is the check that would "
    "have caught the defect before it was written."
)

CAVEATS = (
    "Five limitations, stated rather than buried. First, the gate verdict is FAIL, not PASS: "
    "all four acceptance criteria are mechanically verified, but G5 additionally requires "
    "identity, and the identity component of this work item is not yet in place, so WI-141 "
    "remains IN_PROGRESS. Second, mutation testing is recorded as evidence rather than wired "
    "as a release gate, because sixteen sequential Go test runs are too slow for every sweep; "
    "it is a verification activity, consistent with how EV-032 and EV-034 recorded theirs. "
    "Third, the model package has no persistence. It is a pure decision layer over an "
    "in-memory record, and the sqlc schema for a model registry does not exist yet, so nothing "
    "here survives a restart. The audit event types and idempotency scopes are declared and "
    "tested but not yet written to the audit chain in a transaction with a state change. "
    "Fourth, drift monitoring evaluates a Breached flag supplied by a caller rather than "
    "comparing the observed value against the threshold itself. That is deliberate, because "
    "deciding whether a string is above 0.85 depends on what the number means, but it means "
    "the comparison is not verified here and the automatic-pause guarantee depends on the "
    "supplied flag being correct. Fifth, cross-language digest agreement is pinned by a test "
    "in Python and by Digest.Valid in Go, but the two are separate tests and neither reads "
    "the other, so a change to either representation's rules has to be matched by hand. No "
    "specification file was modified, docs/ remains clean, and nothing was committed."
)

ARTIFACTS = [
    "services/control-plane/model/record.go",
    "services/control-plane/model/lifecycle.go",
    "services/control-plane/model/tools.go",
    "services/control-plane/model/decision.go",
    "services/control-plane/model/monitoring.go",
    "services/control-plane/model/compromise.go",
    "workers/research/src/webtrade_research/lineage.py",
    "workers/research/src/webtrade_research/content_address.py",
    "scripts/mutation_check_model.py",
]

RECORD = {
    "schema": "ecc.project-brain/evidence/v7",
    "evidence_id": EVIDENCE_ID,
    "recorded_at": STAMP,
    "recorded_by": "team-lead",
    "work_item": WORK_ITEM,
    "claim": CLAIM,
    "status": "VERIFIED",
    "method": METHOD,
    "result": RESULT,
    "defect_found_and_fixed": DEFECTS,
    "significance": SIGNIFICANCE,
    "caveats": CAVEATS,
    "exception": "",
    "artifacts": ARTIFACTS,
    "supersedes": [],
}

EVENT = {
    "schema": "ecc.project-brain/event/v7",
    "event_id": "EVT-WI-141-MODEL-GOVERNANCE",
    "recorded_at": STAMP,
    "recorded_by": "team-lead",
    "work_item": WORK_ITEM,
    "event": "work_item_implemented",
    "status": "RECORDED",
    "evidence_ref": EVIDENCE_ID,
    "summary": (
        "G5 model governance implemented at services/control-plane/model: the docs/07 "
        "lifecycle as a closed declared state machine, the eleven-field required model "
        "record, separation of duties, an explicit three-class tool allowlist, a decision "
        "ledger with lineage, seven-signal drift monitoring with mandatory automatic pause, "
        "and the four-action compromise response. workers/research gains a lineage proposal "
        "type that can carry no approval, approver, or promotability field. Five defects "
        "found and fixed, four in production code: a single-valued command map silently "
        "prevented quarantine from seven of eight states, which would have left a compromised "
        "model promotable in those states; a caller of that map then broke; clearing a "
        "quarantine was automatable by the compromised workload itself; a Python dataclass "
        "field was shadowed by a same-named property; and the two languages disagreed about "
        "the digest wire format, so a research dataset fingerprint would have been rejected "
        "by the registry. 89 model tests and 109 research tests, 16 of 16 mutations detected "
        "with every file restored byte-for-byte, all 12 gates PASS. Identity is the remaining "
        "component of G5 and WI-141 stays IN_PROGRESS; gate verdict FAIL."
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
        print(f"appended {EVIDENCE_ID}")

    work_path = BRAIN / "work-items.json"
    doc = json.loads(io.open(work_path, encoding="utf-8").read())
    changed = False
    for item in doc["items"]:
        if item["id"] == WORK_ITEM:
            refs = item.get("evidence_ref", [])
            if EVIDENCE_ID not in refs:
                item["evidence_ref"] = [*refs, EVIDENCE_ID]
                item["partial_results"] = (
                    "AC1 registry/audit/idempotency verified; AC2 no model authorizes its own "
                    "execution verified, including that omitting the record does not skip the "
                    "check; AC3 tool permission-denial, model rollback, and lineage verified; "
                    "AC4 all four compromise actions verified. 89 model tests, 109 research "
                    "tests, 16 of 16 mutations detected with byte-for-byte restore, all 12 "
                    "gates PASS. Five defects found and fixed, including a single-valued "
                    "command map that silently prevented quarantine from seven of eight states "
                    "and a cross-language digest wire-format mismatch. REMAINING: the identity "
                    "component of G5, and no persistence or audit-chain transaction yet. Gate "
                    "verdict FAIL; work item remains IN_PROGRESS."
                )
                changed = True
    if changed:
        io.open(work_path, "w", encoding="utf-8", newline="\n").write(
            json.dumps(doc, indent=2, ensure_ascii=True) + "\n"
        )
        print(f"{WORK_ITEM} evidence and partial_results updated")
    else:
        print(f"{WORK_ITEM} already up to date")

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
