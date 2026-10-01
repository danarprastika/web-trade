"""One-off: append EV-054.

EV-052 and EV-053 both fixed defects that were individually sound and jointly inconsistent. This
record covers the attempt to test that the fixes compose, which neither of the two had done, and
which found no new defect - but did find one unexecuted claim, and produced one near-miss that
is the most useful thing in it.

Idempotent, append-only, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-054"
STAMP = "2026-09-30T21:23:00Z"

WORK_ITEM = "WI-141"

CLAIM = (
    "The fixes in EV-052 and EV-053 compose. Both previous records reported defects found when "
    "individually correct fixes were combined, so the obvious next question was whether the three "
    "fixes now in the tree interfere with each other - and nobody had asked it. Four compositions "
    "were executed rather than reasoned about. Three pass. The fourth appeared to find a real "
    "defect: a journal rebuilt from durable state with no store attached accepts transitions, "
    "appends SUCCEEDED audit records, returns success, and writes nothing. It is not a defect. "
    "The constructor's own comment says a nil store is permitted, means in-memory only, is "
    "deliberately distinct from refusing one, and is guarded by Durable() rather than left to be "
    "inferred. The probe confirmed Durable() reports false. The finding was withdrawn. What "
    "survived is one coverage gap: the claim that repeated refusals are idempotent was asserted by "
    "the review that prompted EV-052, never executed, and had no test. It is now one, and it was "
    "mutation-checked."
)

METHOD = (
    "Did not re-run the previous records' mutations and did not re-read the fixes. Wrote four "
    "scratch probes against compositions rather than units: a store refusing three consecutive "
    "attempts at one transition; a restart taken after a refusal had been resolved; a registration "
    "refused by the store and then retried, which shares the commit path but derives its 'from' "
    "differently from a transition; and a rehydrated journal holding no store. The probe file took "
    "two rounds of corrections before any of it ran, and every correction was the same class as "
    "those in EV-051 and EV-053: it guessed APIs that do not exist. It used audit.Result as a "
    "map[string] key, called a helper that does not exist, assumed RegisterContext returned three "
    "values, and used idempotency keys of two characters against a rule requiring eight. The "
    "fourth correction mattered most: the first probe made the store refuse writes before the "
    "model was registered, so it died in setup. It failed loudly rather than reporting a clean "
    "result, which is the only reason the mistake was visible at all - a probe that had reached "
    "its assertion by accident would have reported one clean result and taught nothing. After the "
    "corrections, the surviving test was kept permanently and mutation-checked by making the "
    "refusal audit id non-deterministic, which is the exact mechanism that makes a repeat "
    "idempotent."
)

RESULT = (
    "Three compositions pass. Repeated refusals produce exactly one REFUSED record across three "
    "attempts, because the refusal audit id is derived from the original record rather than from "
    "the clock, so the repeat is byte-identical and takes the chain's duplicate-delivery branch - "
    "and the model is not left unwritable, because once the store recovers the same request "
    "applies and the chain's last word is SUCCEEDED. A restart taken after a resolved refusal "
    "restores the state the live journal held, with no divergence. A refused registration followed "
    "by a successful retry is coherent, with digest continuity unbroken across all three records: "
    "the refusal carries the attempted outcome as its before-digest and empties as its after, the "
    "resolution carries it back, and a forward walk from the refusal reaches the resolution. The "
    "fourth probe found nothing. One regression test added: TestRepeatedRefusalsAppendOneCorrection"
    "Record, which asserts a single correction record across three refused attempts, that the "
    "model is not wedged once the store recovers, and that the last record is SUCCEEDED. The "
    "mutation that breaks determinism of the refusal audit id produces three REFUSED records and "
    "the test fails by name; it was reverted. 187 model tests, zero failures, race clean, vet and "
    "gofmt clean, all 13 gates pass."
)

DEFECT_FOUND_AND_FIXED = (
    "No code defect. That is the finding, and it is worth stating plainly rather than dressing: "
    "the composition that produced two consecutive serious defects was probed this time and held. "
    "The one substantive change is a test. TestRepeatedRefusalsAppendOneCorrectionRecord, plus a "
    "downStore helper, because the existing suite models a store outage only through "
    "FailNextWrite, which is single-shot - it proves the retry after a blip and cannot say "
    "anything about a store that is down for two attempts running. The review that prompted "
    "EV-052 asserted that repeated refusals are idempotent because the second takes the duplicate "
    "branch; that assertion was true, and it was never executed and had no test, which is a "
    "narrower version of the problem EV-053 describes. The mutation confirms the new test would "
    "catch its absence."
)

SIGNIFICANCE = (
    "The transferable part is the near-miss, not the clean result. The fourth probe produced a "
    "defect report I believed: a journal that reports a successful transition while holding no "
    "durable store, which is precisely the failure this subsystem exists to prevent, and the "
    "asymmetry was real - four of the constructor's five dependencies are validated with written "
    "justifications and the store is not. Had I reported it there, it would have been a confident "
    "defect against a deliberate design decision, justified by evidence, and it would have cost a "
    "regression that a documented guard already covers. What caught it was reading the comment "
    "directly rather than reasoning about whether the code looked right, and the tell was that "
    "the finding was about a missing validation among four present ones - a shape that invites a "
    "completeness argument, which is a warning sign that the fourth may be intentional. This is "
    "the same lesson as EV-051's empty probe output and EV-053's build-failure guard, now at the "
    "level of interpretation rather than tooling: a result the reviewer cannot vouch for is not a "
    "result, and the cheapest way to be wrong here is to be thorough. The second point is about "
    "the shape of the remaining risk. EV-052 and EV-053 fixed two defects that only existed in "
    "composition, so the natural next question was whether the third fix composed with them, and "
    "the answer is that it does. Composition defects are not a permanent property of a codebase; "
    "they are a property of a particular set of changes, and probing them is how that set stops "
    "producing them."
)

CAVEATS = (
    "Five limitations. First, and most important: this record reports no defect found, and a "
    "clean composition result is weaker evidence than a caught one - it shows four probed paths "
    "hold, not that the fixes are correct. Second, the four probes were scratch and are deleted; "
    "only the repeated-refusal case survives as a permanent test. The restart-after-resolution and "
    "refused-registration compositions remain unexercised by the suite and were verified by a "
    "probe that no longer exists, so they rest on this record and on EV-053's tests, which cover "
    "the refusal and resolution records individually but not in sequence with a restart between "
    "them. Third, unchanged from EV-046 and EV-048 onward: no Go process has connected to "
    "PostgreSQL, so none of this has run against a live timestamptz or a real transaction, and "
    "the outbox relation is written and verified only through sqlc type-checking and the "
    "db-0004-model-registry assertions. Fourth, the downStore helper duplicates a capability "
    "MemoryStore nearly has; a FailWrites-while-armed switch on MemoryStore itself would be the "
    "better shape and was not done, because it would change a type other tests depend on and the "
    "gain did not justify the churn. Fifth, unchanged: no composition root constructs any "
    "rehydrated object, so rehydration is still explicit rather than automatic; atomicity between "
    "audit acceptance and registry persistence remains WI-121's; the EV-048 schema-version "
    "forward problem remains unresolved and human-owned; RISK-14's six deferred scaling findings "
    "are open; no specification file was modified; docs/ remains clean; nothing was staged; and "
    "nothing was committed. WI-141 remains IN_PROGRESS pending human G4 review."
)

EXCEPTION = ""

ARTIFACTS = [
    "services/control-plane/model/store_test.go",
    "scripts/record_ev054.py",
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
