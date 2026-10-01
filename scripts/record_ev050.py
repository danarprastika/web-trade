"""One-off: append EV-050 recording identity rehydration, and a security control that was
lost on every restart.

The third and last write-only port now has a reader, and with it the compromise path stops
being an in-memory-only control. Also records a design error this work made and corrected:
Restore initially refused snapshots whose issuance and revocation rows were both present, and
that state is the normal one.

Idempotent, append-only, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-050"
STAMP = "2026-09-30T17:10:00Z"

WORK_ITEM = "WI-141"

CLAIM = (
    "Workload identity revocation now survives a restart, which closes the last of the three "
    "write-only ports and removes the only security control this codebase held purely in "
    "memory. Before this, a process that restarted had an empty revocation map, the "
    "re-mint refusal found nothing, and a workload whose compromise had been recorded months "
    "earlier could be issued a fresh credential - silently, through the maintenance path "
    "rather than the attack path. All three durable surfaces are now readable: the audit "
    "sink, the model registry, and the identity store. It is also recorded that Restore was "
    "first written to refuse a snapshot containing an identity that was both issued and "
    "revoked, and that this state is the normal durable one - the store keeps the issuance row "
    "beside the revocation on purpose - so the check was wrong and had to be replaced by the "
    "removal rule it was standing in for."
)

METHOD = (
    "Located the vulnerability before writing anything, by reading the guard rather than the "
    "gap: MintContext refuses a re-mint by looking the identity up in the registry's revocation "
    "map, so the whole control reduces to whether that map is populated. Established the shape "
    "from the two tables rather than from the Go struct, since a registry that can reconstruct "
    "itself from the durable record does not need the store to be authoritative. Read the "
    "existing queries and found the same gap EV-049 found in the registry: there is no way to "
    "load all identities, because ListValidIdentitiesForModelVersion filters to currently "
    "valid ones. That filter is the dangerous direction specifically here - an expired or "
    "revoked identity missing from the load becomes mintable again. Added two unfiltered reads "
    "and implemented the snapshot reader and the registry restore. Wrote the primary test "
    "first, against the actual failure rather than against the new code, so that it would fail "
    "without the restore and pass with it."
)

RESULT = (
    "The compromise path is now durable and the test says so in the way that matters. The "
    "primary test does not assert that a revocation is present; it asserts that re-minting the "
    "revoked identity after a restart fails, that the failure is an ErrCompromised refusal so a "
    "caller can tell it from a validation error, and that the recorded reason comes back with "
    "it - because a compromise response that cannot say why is one that has to go and find out. "
    "Ten further refusals are covered: duplicate issuance, duplicate revocation, unattributed "
    "revocation, an identity with no model binding, an unknown scope, rows naming a model that "
    "is not an identifier, read failures, a missing reader, and load-order stability across "
    "repeated loads of the same durable state. All ten mutations applied to the new code were "
    "detected against a verified-pristine baseline, with both modified files restored "
    "byte-for-byte, and all 13 project gates pass."
)

DEFECT_FOUND_AND_FIXED = (
    "One, in code written minutes earlier, and it is the instructive one. Restore initially "
    "refused a snapshot in which an identity appeared both as a live issuance and as a "
    "revocation, on the reasoning that such an identity is valid and revoked at once and the "
    "registry cannot represent that. The reasoning is sound and the premise is false. "
    "IdentityStore's own contract is explicit that a revocation is additive: the identity row "
    "is left in place and the revocation is written beside it, because a responder needs to "
    "see what the compromised identity held and a revocation citing a subject that no longer "
    "exists anywhere is not evidence. So every real revocation produces exactly the state I had "
    "decided was a contradiction, and the check would have refused every snapshot worth "
    "restoring - including, pointedly, the snapshot of a compromise that had just been "
    "contained. The rule the store deliberately does not apply is the one Restore has to: the "
    "registry holds only what it would still answer yes to, so a revoked identity is loaded and "
    "then removed. The failing test caught this, which is the argument for having written the "
    "test against the real failure rather than against the new code: a test written to confirm "
    "that Restore works would have been written to match the check, and would have passed. The "
    "replacement test pins the correct behaviour - issued and revoked together restores as "
    "revoked, not live, and cannot then be re-minted - which is a stronger statement than the "
    "one it replaced."
)

SIGNIFICANCE = (
    "The substantive point is where a security control lives. Revocation was authoritative, "
    "enforced under a lock, documented as the response to a compromise - and held only in a "
    "process's heap. Every property the codebase insists on for that control was true, and the "
    "one property that would have mattered was not: it did not survive. There is no test that "
    "could have found this, because the behaviour was correct for as long as the process ran, "
    "and the registry's own tests all passed throughout - they exercised revocation against the "
    "same map that revocation had written. This is the third instance across EV-047 through "
    "EV-050 of the same shape: write-only was treated as a security property when in two of the "
    "three cases it was the absence of a recovery path wearing a security costume. The "
    "resolution was identical each time and never involved loosening the write port - add a "
    "separate read-only interface, keep the delete refusals, and let the read side be tested "
    "without the write side. The pattern worth carrying forward is that a control described in "
    "terms of what the type does, rather than of what the process can reconstruct, is a control "
    "with a restart-shaped hole in it."
)

CAVEATS = (
    "Four limitations. First, unchanged from EV-046, EV-048 and EV-049: no Go process has "
    "connected to PostgreSQL and called the identity snapshot reader, and "
    "ListAllWorkloadIdentities and ListAllWorkloadRevocations have never been executed by "
    "anything except sqlc's type checking. The mapping is verified against the generated dbgen "
    "types and the 45 database assertions in db-0004-model-registry cover the statements and the "
    "schema, but the Go mapping itself remains unproven against a live instance. Second, nothing "
    "constructs a RehydratedWorkloadRegistry and no composition root exists, so as with the "
    "journal this is explicit rather than automatic, and a caller must invoke it. Calling it "
    "without a reader is refused rather than producing an empty registry, which is the safe "
    "direction - an empty registry reports no revoked identity as revoked - but the burden is "
    "still the caller's. Third, revocation records carry a revoked_by column which the write "
    "side fills with the constant control-plane and the read side discards. That is a "
    "deliberate existing decision, recorded in the write side's own comment as being the right "
    "place for the responder to be recorded - the audit chain - and a second copy here would give "
    "two places to disagree about who responded to a compromise. It is restated here because a "
    "column read and dropped is exactly the kind of thing a later reader will mistake for a bug. "
    "Fourth, the schema-version forward problem from EV-048 and EV-049 is unchanged and now "
    "constrains three stores. Also unchanged: the mutation harness was run as a verification "
    "activity and its script and scratch files were deleted; no specification file was modified; "
    "docs/ remains clean; nothing was staged; and nothing was committed. WI-141 remains "
    "IN_PROGRESS with its G5 evidence incomplete and human G4 review outstanding."
)

EXCEPTION = ""

ARTIFACTS = [
    "services/control-plane/model/identity_restore.go",
    "services/control-plane/model/identity_restore_test.go",
    "services/control-plane/model/identity_read.go",
    "services/control-plane/model/identity_store.go",
    "services/control-plane/model/identity.go",
    "services/control-plane/db/queries/model_registry.sql",
    "db/migrations/0004_model_registry.sql",
    "scripts/record_ev050.py",
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