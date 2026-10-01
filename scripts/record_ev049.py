"""One-off: append EV-049 recording journal rehydration and the two durable stores now cross-checked.

The third read-side gap is closed. Registry state, the audit chain and the spent idempotency
ledger all survive a restart, and - the part worth having - a restore now refuses a registry
that its own audit evidence does not corroborate.

Also records the schema read that rehydration required and did not have, and the correction to
a claim in EV-048 about how forward-compatible the schema version is.

Idempotent, append-only, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-049"
STAMP = "2026-09-30T16:45:00Z"

WORK_ITEM = "WI-141"

CLAIM = (
    "The model journal survives a restart. Registry state, the audit chain and the spent "
    "idempotency ledger are all restored, a restored journal continues the same chain rather "
    "than starting a new one, and - the part that is more than a convenience - a restore "
    "refuses a registry that its own audit evidence does not corroborate. The three write-only "
    "ports this work opened with are now two closed and one remaining: the audit sink has a "
    "reader, the registry store has a snapshot reader, and the identity store still has "
    "neither. Rehydration also required a registry read that did not exist, and adding it "
    "surfaced a design property worth stating plainly: the active-model read is the only "
    "convenient one, and using it for a restore would silently resurrect retired models."
)

METHOD = (
    "Started from what a restart actually needs rather than from the Journal struct. Three things "
    "have to come back: which models exist, what state each reached, and which idempotency keys "
    "were spent. The third is the one that drove the design, because a restored journal without "
    "the ledger does not merely lose history - a retried transition stops being a retry, so a "
    "caller retrying after a restart gets a second execution of an operation that already "
    "committed. Checked whether the state could be reconstructed from the audit chain instead, "
    "and it cannot: stateDigest is one-way, so the chain can verify a state but never supply one. "
    "That settled the shape - the chain restores the evidence, the registry restores the "
    "declarations and states, and neither substitutes for the other. Read the existing queries "
    "before writing the reader and found the gap there: ListModelsInState needs a state supplied "
    "and ListActiveModels deliberately excludes the terminal states, so there was no way to load "
    "the whole registry. Compared adding ListAllModels against enumerating the closed State enum "
    "in Go, and chose the query, because enumerating the enum in Go would add a second place for "
    "the enum and the database CHECK to disagree. Then made the chain authoritative in the "
    "verification rather than the registry, and wrote the tests so that each one fails when the "
    "guarantee it names is deleted."
)

RESULT = (
    "A restart is now survivable and verified as such rather than asserted. The tests build a "
    "journal against a store, do real work through it, then throw away everything in memory and "
    "rebuild from what was written - chain from audit storage, registry from the snapshot - and "
    "check the result. The idempotency test does more than assert that a key is present: it "
    "replays the spent key through the restored journal and confirms the replay returns the "
    "original outcome, cites the original audit record, and appends nothing. A transition applied "
    "after a restart lands on the restored chain at the right sequence, which is the property "
    "that distinguishes a rehydrated journal from a new one. Three refusals are covered and all "
    "three are the interesting cases: a registry claiming a state no audit record established, a "
    "model citing an audit record the chain does not hold, and a model with no audit record at "
    "all. The refusal names the after-digest mismatch rather than reporting a generic conflict, "
    "because the operator seeing this needs to know which of the two stores to believe. The "
    "after-digest comparison strips the ':approval' suffix that commit appends, and a mutation "
    "confirming the whole field is compared instead is detected - so approval transitions are "
    "neither refused nor accepted with the approval unchecked. All nine mutations applied to the "
    "new code were detected against a verified-pristine baseline, with all three modified files "
    "restored byte-for-byte, and all 13 project gates pass."
)

DEFECT_FOUND_AND_FIXED = (
    "Two, both in code this work added. First, ListAllModels did not exist and the only "
    "unfiltered-looking read was deliberately blind to terminal states. That is not a bug in the "
    "query - it is correct for a serving set and exactly wrong for a restore, and the "
    "distinction is invisible unless you ask what a restart loses. A retired model missing from "
    "the registry looks unregistered, and an unregistered model can be registered again, so the "
    "convenient read is the one that would have been chosen by someone not thinking about it, "
    "and it fails in the direction of permitting something that should be forbidden. Second, and "
    "found by a test asserting the right thing: restoring an empty store against an empty chain "
    "returns success, which I had written a test expecting to fail. The test was wrong. An empty "
    "registry and an empty chain are genuinely consistent, and a restore that refused that would "
    "be refusing the ordinary state of a fresh deployment. The test was rebuilt around a populated "
    "registry, which is where the corroboration check actually has something to do. Neither is "
    "recorded as a defect in the pre-existing code, and that is the finding: the rehydration gap "
    "had been carried as a limitation across seven evidence records, and when finally implemented "
    "it required no change to any design decision - only a query that had never been needed and a "
    "caller that had never existed."
)

SIGNIFICANCE = (
    "The corroboration check is the part that makes rehydration worth having rather than merely "
    "convenient, and it is available only because there are two durable stores. A registry that "
    "were its own authority could be restored into memory and would be indistinguishable from "
    "correct until something disagreed with it. Because the audit chain is append-only, "
    "independently verifiable, and the only one of the two whose integrity anyone outside this "
    "process can check, it is the one that gets to say whether a restored state is real. A "
    "registry row claiming PROMOTED while its cited audit record says REGISTERED is a drift, and "
    "the drift is detectable at the moment of restore - which is the last moment at which "
    "detecting it is still cheap. The broader point is about write-only ports. All three of these "
    "ports were write-only, and that was a defensible design in every case: a sink that can "
    "modify evidence is not a sink, a store that can read as well as write is reachable from "
    "code whose job is only to load. But write-only was carried as a limitation on restart, and "
    "the resolution was not to loosen the ports. It was to add separate read-only interfaces, "
    "which keeps the write guards meaningful and makes the read path a thing that can be "
    "tested independently of the write path."
)

CAVEATS = (
    "Five limitations. First, unchanged from EV-046 and EV-048: no Go process has connected to "
    "PostgreSQL and called the snapshot reader. The row mapping is verified against the "
    "generated dbgen types, and the 45 database assertions in db-0004-model-registry cover the "
    "statements and the schema, but the mapping itself is unproven against a live instance. "
    "ListAllModels in particular has never been executed by anything except sqlc's type "
    "checking. Second, rehydration here is explicit rather than automatic: nothing constructs a "
    "RehydratedJournal, and no composition root exists, so a caller must call it deliberately in "
    "the right order - restore the chain, then the journal. Calling it in the wrong order fails "
    "with a clear message rather than producing an empty journal, which is why that is a refusal "
    "and not a silent no-op, but the ordering is still the caller's responsibility. Third, the "
    "approval suffix is stripped for comparison and therefore not verified: Restore confirms that "
    "a state matches the digest prefix of the after-digest, and does not check that the approval "
    "recorded alongside it is one this process would have accepted. Confirming that would mean "
    "reading the approver's identity back out of the chain, which is not implemented. Fourth, "
    "EV-048's forward-compatibility caveat is unchanged and is restated because it now constrains "
    "two stores rather than one: canonicalFields hashes the package schema constant rather than a "
    "per-record value, so a future schema bump makes every existing record un-re-derivable by "
    "design. With seven-year retention that is a real forward problem, it remains unfixed, and it "
    "belongs to a human because the fix changes a security-relevant invariant. Fifth, the identity "
    "store is still write-only, so a WorkloadRegistry that has issued and revoked workload "
    "identities cannot be reconstructed after a restart and will reissue identities it should "
    "recognise as revoked. That is the last of the three, and it is the one with the clearest "
    "security consequence. Also unchanged: the mutation harness was run as a verification activity "
    "and its script and scratch files were deleted, so no stray file is left for the spec gate to "
    "find; no specification file was modified; docs/ remains clean; nothing was staged; and "
    "nothing was committed."
)

EXCEPTION = ""

ARTIFACTS = [
    "services/control-plane/model/restore.go",
    "services/control-plane/model/restore_test.go",
    "services/control-plane/model/store_read.go",
    "services/control-plane/model/store.go",
    "services/control-plane/model/journal.go",
    "services/control-plane/audit/chain.go",
    "services/control-plane/db/queries/model_registry.sql",
    "db/migrations/0004_model_registry.sql",
    "scripts/record_ev049.py",
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
