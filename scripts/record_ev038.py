"""One-off: append EV-038 recording the WI-141 G5 workload identity implementation.

Records the identity component of G5 as verified, and records the three defects the work
surfaced: one in production code that was a declaration of a security property rather than an
enforcement of it, one in the mutation harness itself that made its own results unattributable,
and one dead mutation retained after the defect it tested for was removed.

Idempotent, append-only, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-038"
STAMP = "2026-09-29T17:12:00Z"

WORK_ITEM = "WI-141"

CLAIM = (
    "The identity component of gate G5 is implemented and verified. docs/25 section 5 requires "
    "a short-lived workload identity with immediate revocation, bound to the exact model "
    "version it serves so that a revocation is precise. services/control-plane/model/identity.go "
    "implements all three as enforced properties of a WorkloadRegistry, and the compromise "
    "response now performs the revocation rather than being told that it happened."
)

METHOD = (
    "Re-read docs/25 section 5 for the zero-trust workload identity requirement and the "
    "docs/25 section 6 failure-mode row for a compromised workload, alongside the G5 identity "
    "clause in docs/11, before writing anything. Reviewed compromise.go as it stood after "
    "EV-037, because the identity work changed a signature there and the first question is "
    "whether the existing shape already expressed the requirement. Wrote identity.go, then "
    "identity_test.go, then changed Contain, then the compromise tests, then extended "
    "scripts/mutation_check_model.py with five identity mutations and one containment "
    "mutation. Ran the mutation check three times: the first run reported a skipped mutation "
    "whose anchor was demonstrably present, which was investigated rather than accepted, and "
    "led to the harness defect below."
)

RESULT = (
    "identity.go defines WorkloadScope (a closed set of two: SERVE_INFERENCE and "
    "PRODUCE_ARTIFACTS, where producing is not deciding), WorkloadIdentity, Revocation, "
    "Presentation, and WorkloadRegistry. Mint issues an identity bound to a model id, an exact "
    "model version, and a scope, with a fixed WorkloadTTL of one hour and an injected clock, so "
    "expiry is a constant and is not caller-settable. Authenticate refuses an unknown identity, "
    "an identity presented for a different model or a different version of the same model, an "
    "expired identity, and a revoked identity - and the refusal for a revoked identity carries "
    "the recorded reason and evidence, so an operator is pointed at the incident rather than at "
    "the clock. Revoke records a Revocation with reason, evidence reference, and the model "
    "version it covered; it is idempotent, returning the original record on a repeat, and it "
    "refuses an identity that was never issued, because a revocation for a nonexistent workload "
    "would put a fabricated incident in the audit chain. A revoked identity cannot be re-minted. "
    "ContainedModelVersions answers what a model's compromised identities actually covered, "
    "which is the first question an investigation asks. Contain changed from taking a boolean "
    "reporting that the caller had already revoked the identity to taking the WorkloadRegistry "
    "and performing the revocation, and CompromiseResponse now carries the resulting Revocation "
    "rather than a flag asserting one exists. 99 model tests, go vet clean, gofmt clean, and all "
    "12 release gates PASS. The mutation check is now 21 of 21 applied, 21 detected, 0 "
    "survived, 0 skipped, with every file restored byte-for-byte."
)

DEFECTS = (
    "Three defects, one in production code and two in the verification harness. First, and the "
    "one that matters: Contain took a bool named revoked reporting that the caller had already "
    "revoked the compromised workload's identity, and on true returned a CompromiseResponse "
    "with WorkloadIdentityRevoked set. A caller passing true without revoking anything would "
    "have produced a response asserting, in a field an incident record would read as fact, that "
    "a workload identity had been revoked when no such record existed anywhere in the system. "
    "The signature made the security property uncheckable: nothing distinguished a caller that "
    "had performed the first required response from one that had not, and the four required "
    "actions were checked by three assertions and one caller-supplied boolean. Contain now takes "
    "the WorkloadRegistry, performs the revocation, and returns the recorded Revocation, so the "
    "response can point at what it did; a nil registry is refused rather than treated as a "
    "claim, and the response verifies that the revocation it received covers the identity it "
    "was asked about. Second, and the one worth carrying forward: scripts/"
    "mutation_check_model.py applied mutations cumulatively. Files were captured once before the "
    "loop and restored only in a finally block after every mutation had run, so each mutation "
    "was applied to a tree that already contained the previous mutations to the same file. Six "
    "of the new mutations target identity.go, and a test failure under the sixth could have "
    "been caused by any of the five before it. The script was reporting which mutation was "
    "detected while being structurally unable to know. This is the same failure mode the script "
    "itself warns about in its skipped-mutation output - an unverified claim reported as a pass - "
    "one level up, in the tool that produces the claims. The loop now restores the pristine tree "
    "before and after every mutation, so each is measured in isolation. Third: M13 asserted that "
    "Contain refuses an unrevoked identity by neutering its !revoked branch. That branch no "
    "longer exists, because the boolean is gone, so the mutation was retained in the suite as a "
    "permanent SKIP - a rule stated but neither confirmed nor refuted, which is worse than "
    "removing it, because a reader scanning the list sees a documented guarantee. M13 was "
    "removed and superseded by M20, which mutates the new code path so that the response "
    "constructs a Revocation without performing one, and is detected by a test that checks the "
    "compromised identity no longer authenticates afterwards."
)

SIGNIFICANCE = (
    "The first defect is a class worth naming: a security property expressed as a parameter. "
    "Contain's bool was not a bug in the revocation logic; the revocation logic was correct and "
    "mutation-tested. The defect is that 'the identity was revoked' was supplied by the caller as "
    "a fact rather than produced by the function as a result, which means the function's own "
    "signature declared that the property was unverifiable. Every test that passed against it "
    "was testing a caller's honesty. The general form: a control that reports a security outcome "
    "must be able to name the record that proves it, and a function that accepts the outcome as "
    "an argument has given that proof away. The second defect is the same shape in the tooling, "
    "which is why it is worth writing down: the mutation harness reported per-mutation verdicts "
    "it could not attribute, and would have continued reporting them indefinitely, because a "
    "harness that is structurally cumulative produces plausible output. The general form: a "
    "verification tool must be tested for the property it claims to provide, and 'each mutation "
    "is measured independently' is a testable property that nothing was testing. Both were found "
    "only because a mutation was skipped that should not have been, and the skip was treated as a "
    "defect to diagnose rather than a nuisance to remove."
)

CAVEATS = (
    "Seven limitations, stated rather than buried. First, Authenticate takes a Presentation "
    "struct and checks it against the registry; it does not perform or verify any cryptographic "
    "proof. What is modelled is the binding between an authenticated principal and an exact "
    "model version, and the binding of that principal to a short life and to revocation. The "
    "token format, its signature, and its transport are not implemented and are not tested, so "
    "the property this work establishes is 'a workload that authenticates is bound to one model "
    "version and dies within an hour', not 'an attacker cannot forge a workload identity'. "
    "Second, the registry is in-memory. A restart loses every identity and every revocation, "
    "and a restart is exactly the window in which a revoked workload would be able to re-mint "
    "itself, because the refusal in Mint is a refusal based on remembered revocations. This is "
    "the most serious of the seven and it is a persistence gap, not a design choice: revocation "
    "that lives only in the process that issued it is not revocation. Third, WorkloadRegistry "
    "has no concurrency protection; Mint, Revoke, and Authenticate mutate and read shared maps "
    "and a concurrent Authenticate alongside a Revoke is a data race. It is a pure decision "
    "layer today, single-threaded by its tests, and needs a mutex or an actor before it is "
    "called from more than one goroutine. Fourth, ContainedModelVersions is a query with no "
    "caller: nothing in the platform yet uses it to widen a compromise, and the automatic "
    "quarantine of sibling identities serving the same version is not implemented. Revoking one "
    "identity is precise, which is what was asked for, but precision is not completeness and a "
    "compromised model may have been served by identities nobody has revoked. Fifth, Mint takes "
    "the identity name from the caller and there is no issuance policy, no rotation, and no "
    "short-lived credential in the sense docs/25 means by it - the identity is long-lived and the "
    "credential is the identity name. What is short-lived here is the window in which the name "
    "is honoured. Sixth, scopes are recorded on the identity and are not consulted by "
    "Authenticate; they are governance metadata, and a workload holding ScopeServeInference is "
    "not prevented from attempting a governed tool call by anything in this package. The test "
    "asserting that a workload scope confers no lifecycle authority passes because the lifecycle "
    "refuses a service actor independently of scope, which is the right design and is not the "
    "same as scope enforcement, and because the set of scopes is two rather than the four the "
    "gate's prose could be read to imply, with no MARKET_DATA scope and nothing that would let "
    "one exist. Seventh, the model package still has no persistence and still "
    "does not write its audit events to the audit chain in a transaction with a state change, "
    "both carried forward from EV-037. No specification file was modified, docs/ remains clean, "
    "nothing was staged, and nothing was committed."
)

ARTIFACTS = [
    "services/control-plane/model/identity.go",
    "services/control-plane/model/identity_test.go",
    "services/control-plane/model/compromise.go",
    "services/control-plane/model/compromise_test.go",
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
    "event_id": "EVT-WI-141-WORKLOAD-IDENTITY",
    "recorded_at": STAMP,
    "recorded_by": "team-lead",
    "work_item": WORK_ITEM,
    "event": "work_item_implemented",
    "status": "RECORDED",
    "evidence_ref": EVIDENCE_ID,
    "summary": (
        "G5 workload identity implemented at services/control-plane/model/identity.go: a "
        "short-lived identity bound to one exact model version, with immediate revocation that "
        "carries its reason and evidence into the refusal, is idempotent, and prevents re-minting "
        "the same name. Contain now performs the revocation against a WorkloadRegistry and "
        "returns the recorded Revocation instead of accepting a caller boolean asserting it "
        "happened. Three defects found and fixed. The Contain signature made the first required "
        "response unverifiable: a caller passing true without revoking anything produced an "
        "incident record claiming a workload identity had been revoked when no such record "
        "existed. The mutation harness applied mutations cumulatively and restored only at the "
        "end, so it reported per-mutation verdicts it was structurally unable to attribute; it "
        "now restores the pristine tree around each mutation. A dead mutation was retained as a "
        "permanent SKIP after the branch it tested for was removed, stating a guarantee it could "
        "neither confirm nor refute; it was removed and superseded. 99 model tests, 21 of 21 "
        "mutations detected with byte-for-byte restore, all 12 gates PASS. The registry is "
        "in-memory and concurrent access is unprotected, so revocation does not survive a restart; "
        "WorkloadRegistry needs persistence and a mutex before it is used from more than one "
        "goroutine. WI-141 remains IN_PROGRESS; gate verdict FAIL."
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
                    "AC4 all four compromise actions verified with the revocation now performed "
                    "rather than asserted. Identity: short-lived workload identity bound to one "
                    "exact model version, with immediate idempotent revocation that carries "
                    "reason and evidence into the refusal and blocks re-minting. 99 model tests, "
                    "109 research tests, 21 of 21 mutations detected with byte-for-byte restore, "
                    "all 12 gates PASS. Defects found and fixed: Contain accepted a caller "
                    "boolean asserting revocation had happened; the mutation harness applied "
                    "mutations cumulatively and could not attribute its own verdicts; a dead "
                    "mutation was retained as a permanent SKIP. REMAINING: WorkloadRegistry is "
                    "in-memory with no mutex, so revocation does not survive a restart and "
                    "concurrent access is a data race; Authenticate performs no cryptographic "
                    "verification; ContainedModelVersions has no caller, so no automatic "
                    "widening of a compromise to sibling identities; no persistence and no "
                    "audit-chain transaction. Gate verdict FAIL; work item remains IN_PROGRESS."
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
