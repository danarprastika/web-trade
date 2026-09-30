"""One-off: append EV-040 recording the WI-141 G5 compromise-containment widening.

Completes AC4: containment now revokes every workload serving the compromised model version,
not only the detected one, and the reported blast radius is a function of the revocations
recorded rather than of when the record was written.

Idempotent, append-only, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-040"
STAMP = "2026-09-29T18:58:00Z"

WORK_ITEM = "WI-141"

CLAIM = (
    "AC4's compromised-worker response is complete rather than merely sufficient. "
    "Containment now widens from the detected workload to every workload serving the same "
    "exact model version, and the response names the whole population it reached. The previous "
    "behaviour revoked exactly the identity that was detected, which is precise and incomplete: "
    "the compromised thing is the model version, and the siblings bound to it can still answer "
    "with the same compromised artefact."
)

METHOD = (
    "Started from the caveat EV-038 recorded against ContainedModelVersions, which was that it "
    "was a query with no caller and that precision is not completeness. Read identity.go to "
    "establish what the registry could answer and found the gap was larger than the caveat "
    "stated: ContainedModelVersions answers the backwards question - which versions already "
    "have a revoked identity - while widening needs the forward one, which other identities are "
    "serving this version. Added IdentityOf, IdentitiesServingVersion and "
    "ContainedIdentitiesForVersion, then changed Contain. The tests were written to assert both "
    "halves of the property, that siblings are reached and that unrelated workloads are not, "
    "because a widening rule with only the first half tested is a rule that will eventually be "
    "widened too far. Mutation-tested the three claims with scripts/mutation_check_model.py."
)

RESULT = (
    "identity.go gains IdentityOf, which reports the binding the registry recorded for an "
    "identity, and IdentitiesServingVersion, which reports every currently valid identity bound "
    "to one exact model version, excluding revoked and expired ones so the result is the "
    "population containment actually has to act on rather than every identity ever issued. "
    "Contain revokes the named identity, then revokes each sibling returned by that lookup, and "
    "reports ContainedIdentities and ContainmentWiden alongside the existing four actions. The "
    "model and version used for the widening are read from the registry's own record of the "
    "identity, never from the declaration, so a responder who misstated the version could not "
    "silently contain the wrong population in either direction; and the widening stops at the "
    "exact version, because a workload serving a different version of the same model has "
    "different output and one serving a different model is unrelated. Widening to the whole "
    "model id would revoke workloads with no relationship to the compromise, which destroys "
    "availability and makes the containment unreviewable. identity.go also gains "
    "ContainedIdentitiesForVersion, which reads the revocations actually recorded rather than "
    "the live set, and that is what the response reports. 122 model tests including four "
    "covering the widening and its boundary, race-detector clean, go vet clean, gofmt clean, and "
    "all 12 release gates PASS. The mutation check is now 32 of 32 applied, 32 detected, 0 "
    "survived, 0 skipped, with every file restored byte-for-byte."
)

DEFECTS = (
    "One defect, and it was in the first version of this work rather than in what it replaced. "
    "Contain built its reported population from the sibling set it had just acted on. That is "
    "correct on the first response and wrong on every subsequent one: the siblings the first "
    "response revoked are excluded from the live set, so a second responder - or a replayed "
    "automation - computed an empty set and produced a CompromiseResponse claiming containment "
    "reached one workload when it had in fact reached three. The test for idempotent retry "
    "caught it. The consequence is the specific failure this line of work exists to prevent: an "
    "incident record that understates its own blast radius, written by a responder who had done "
    "nothing wrong, because the record was a function of when it was written rather than of what "
    "had happened. The fix is ContainedIdentitiesForVersion, which derives the reported set from "
    "the revocations recorded, so the record is stable across retries. Note what this is not: it "
    "is not that retrying containment was unsafe, since Revoke is idempotent and the siblings "
    "stay revoked. It is that the second response described a different and smaller event than "
    "the first, and the second response is the one an investigator would read."
)

SIGNIFICANCE = (
    "The general form here is that a report of what was done must be derived from the record of "
    "actions, never from the state of the world at the moment of reporting. Those coincide on a "
    "first run and diverge on every retry, which is exactly when a second pair of eyes arrives. "
    "The general failure is a report that is a function of its own timing: it is plausible, it "
    "is produced by correct code, and it is wrong only in the case nobody would think to check, "
    "because the first run is the run anyone verifies. It is worth noting the shape of the "
    "detection too - the assertion that failed was an idempotency test, not a security test. "
    "The containment logic was correct, the widening was correct, and the boundary was correct; "
    "what was wrong was a field in the response describing the result, and it was found by a "
    "test whose stated purpose was that a retry does not fail."
)

CAVEATS = (
    "Five limitations, stated rather than buried. First, and unchanged from EV-039: the "
    "workload registry, the model registry, the audit chain, and the idempotency ledger are all "
    "in-memory. Widening increases the damage a restart does, because a revocation that does not "
    "surive a process boundary is not a revocation, and now there are more of them to lose. This "
    "remains the largest open item in the work item. Second, the widening is driven by the "
    "registry's in-memory view of which identities exist, so a workload whose identity was issued "
    "by a process that has since restarted is invisible to the lookup and is not widened to. "
    "That is a direct consequence of the first and is not fixed by anything in this record. "
    "Third, ContainedModelVersions is still keyed on a model and reports versions with at least "
    "one revocation, which answers a different question from what a version-wide quarantine "
    "would need: it does not say whether the model's artifacts for that version are themselves "
    "quarantined, and containment quarantines the artifacts named in the declaration only. If a "
    "version was served by three workloads, this response names one set of artifacts. Fourth, "
    "Contain still does not perform the model's lifecycle quarantine. It applies the transition "
    "that promotion blocking follows from, and the journal added in EV-039 is now able to carry "
    "out that transition with an audit record, but the two are separate calls and nothing "
    "sequences them, so a caller that revokes and then fails to quarantine has completed half a "
    "response. AC4's four actions are each verified individually; the atomicity of the response "
    "as a whole is not verified and is not implemented. Fifth, the mutation harness remains a "
    "verification activity rather than a release gate, because thirty-two sequential Go test runs "
    "are too slow for every sweep, consistent with EV-032, EV-034, EV-037 and EV-039. No "
    "specification file was modified, docs/ remains clean, nothing was staged, and nothing was "
    "committed."
)

ARTIFACTS = [
    "services/control-plane/model/compromise.go",
    "services/control-plane/model/compromise_test.go",
    "services/control-plane/model/identity.go",
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
    "event_id": "EVT-WI-141-CONTAINMENT-WIDENING",
    "recorded_at": STAMP,
    "recorded_by": "team-lead",
    "work_item": WORK_ITEM,
    "event": "work_item_implemented",
    "status": "RECORDED",
    "evidence_ref": EVIDENCE_ID,
    "summary": (
        "AC4 completed: containment now widens from the detected workload to every workload "
        "serving the same exact model version. Revoking only the detected identity was precise "
        "and incomplete, because the compromised thing is the model version and the siblings "
        "bound to it could still answer with the same compromised artefact. The model and "
        "version come from the registry's own record of the identity, never from the "
        "declaration, and the widening stops at the exact version so that workloads serving "
        "different output are not revoked with it. One defect found, in the first version of "
        "this work: the reported blast radius was built from the sibling set just acted on, "
        "which is correct on the first response and wrong on every retry, because the siblings "
        "the first response revoked are excluded from the live set. A second responder would "
        "have written an incident record claiming containment reached one workload when it had "
        "reached three. The reported set is now derived from the revocations actually recorded, "
        "so the record is a function of what happened rather than of when it was written. The "
        "test that caught it was an idempotency test, not a security test. 122 model tests, race "
        "clean, 32 of 32 mutations detected with byte-for-byte restore, all 12 gates PASS. The "
        "in-memory gap is now wider, because a revocation that does not survive a restart is not "
        "a revocation and there are more of them. WI-141 stays IN_PROGRESS; gate verdict FAIL."
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
                    "AC1 registry/audit/idempotency verified: journal.go is the registry's only "
                    "write path and writes the lifecycle state only after the audit chain accepts "
                    "the record describing it. AC2 no model authorizes its own execution "
                    "verified. AC3 tool permission-denial, model rollback, and lineage verified. "
                    "AC4 all four compromise actions verified, with containment now widening "
                    "from the detected workload to every workload serving the same exact model "
                    "version, and the reported blast radius derived from the revocations "
                    "recorded rather than from the live set so it is stable across retries. "
                    "Identity: short-lived workload identity bound to one exact model version, "
                    "with immediate idempotent revocation that carries reason and evidence into "
                    "the refusal and blocks re-minting. 122 model tests race-clean, 109 research "
                    "tests, 32 of 32 mutations detected with byte-for-byte restore, all 12 gates "
                    "PASS. Defects found and fixed: registration was outside the declared "
                    "transition set; VerifyDeclaration's rules were structurally untestable so "
                    "its empty-source guard could be deleted with the suite green; the "
                    "quarantine-exit check was narrower than the comment stating it; the "
                    "reported containment population was a function of when the record was "
                    "written rather than of what had happened; Contain accepted a caller boolean "
                    "asserting revocation had happened; the mutation harness applied mutations "
                    "cumulatively and could not attribute its own verdicts. REMAINING: the "
                    "workload registry, model registry, audit chain, and idempotency ledger are "
                    "all in-memory, so a restart loses them together and widening makes that gap "
                    "worse rather than better; a workload whose identity was issued by a process "
                    "that has since restarted is invisible to the widening lookup; containment "
                    "quarantines only the artifacts named in the declaration, not every artifact "
                    "of the affected version; Contain does not itself perform the model's "
                    "lifecycle quarantine, so the four actions are each verified but their "
                    "atomicity is neither verified nor implemented; ContainedModelVersions does "
                    "not say whether a version's artifacts are quarantined; Authenticate performs "
                    "no cryptographic verification. Gate verdict FAIL; work item remains "
                    "IN_PROGRESS."
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
