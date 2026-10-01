"""One-off: append EV-070.

Records the response to the review of the two unpushed commits: eleven findings, all fixed, and
the two of them that mattered most were about the repository's own honesty rather than about the
product.

The critical finding is the one this evidence ledger has spent most of its history earning the
right to claim: a truncated audit partition rehydrated as verified. The paging loop ended on a
short page, restore checked only contiguity and hash linkage, and nothing anchored the expected
head - so deleting the newest rows of a partition produced a shorter, still-valid, still-verified
chain. The system whose entire purpose is refusing unverifiable state was reporting unverifiable
state as verified. The fix needed no migration: audit_checkpoints already existed in migration
0002 as a signed, guarded, append-only record of where each partition got to, and the generated
GetLatestAuditCheckpoint query already read it. The anchor was there. Nobody had asked.

The two gate findings are the same class the ledger records as EV-067 and believed fixed. The
drain mutation gate treated any non-zero `go test` exit as a detection, so a mutation that broke
compilation was credited as proof the drain is tested - it would have certified coverage it never
measured. The bash gate printed PASS for zero run blocks. The first is now closed by porting the
discrimination the sibling mutation harness in the same commit already had; the second by
consolidating two copies of one rule into the script, with the pytest test delegating rather than
reimplementing, so they cannot drift apart again.

Two findings are recorded as honestly as the two CRITICAL ones. The integration suite ran a full
migration Down - DROP SCHEMA CASCADE - against whatever DATABASE_URL named, so a developer
pointing it at a shared DSN lost four schemas. It now refuses a database that does not announce
itself disposable, and an unset opt-in fails loudly rather than skipping, because re-introducing
a silent skip is the defect EV-064 was recorded for. And the migrate CLI's status direction ran
CREATE SCHEMA before its read-only branch; it now probes pg_catalog and issues no DDL at all,
proven here by running it against a virgin database and counting zero tables afterwards.

Also recorded: the ledger read was N+1 - one query per model on the startup path - and is now two
queries whatever the registry size, with a call-count assertion pinning it, because a reader that
regressed to per-model would return an identical Snapshot and only the count would notice.

Two findings were dropped rather than fixed, and that is recorded as carefully as the fixes. One
was rated medium by the reviewer who raised it and is unreachable today because
ObserveVerification has no production caller. The other was claimed to let a hand-edited query
copy drift while still reporting PASS; checking it showed the opposite - adding a column makes
that script fail loudly on the arity assertion - so the stated failure mode was wrong and fixing
it would have been noise.

human_reviewer remains null. An agent reviewing its own work is not the independent check the
field exists for, and the re-review that matters has not happened.

Idempotent, append-only, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-070"
STAMP = "2026-10-02T00:20:00Z"

WORK_ITEM = "WI-141"

CLAIM = (
    "An independent review of the two unpushed commits raised eleven findings across six tracks. "
    "All eleven are fixed, and the two that mattered most were about this repository's honesty "
    "rather than about the product: a truncated audit archive rehydrated as verified, and two "
    "gates that could report success while verifying nothing. The critical fix required no "
    "migration - the durable anchor was already in the database and already queryable; nobody "
    "had asked for it."
)

METHOD = (
    "The diff was 111 files and 20108 changed lines, so all six tracks were reviewed - security, "
    "business logic, deploy safety, performance, duplication, dead code - with security, business "
    "logic and deploy safety first, then the remainder. Nine findings came back and every one was "
    "re-checked by hand against the source before being accepted, which was not a formality: two "
    "were dropped as a result. The guard.go latch finding was rated medium by the reviewer who "
    "raised it and is unreachable because ObserveVerification has no production caller. The "
    "verify_queries_roundtrip.py finding claimed a hand-copied column list could drift while still "
    "reporting PASS; reading the code showed the opposite, since adding a column makes that script "
    "fail on the arity assertion, so the stated failure mode was wrong and acting on it would have "
    "been noise. The surviving nine were then fixed in five parallel work streams with disjoint "
    "write scopes, and two claims were proved directly rather than accepted from a report: the "
    "migrate status direction was run against a freshly created database and the catalog was then "
    "counted to confirm it created nothing, and the regeneration of the generated query layer was "
    "run twice to confirm it is stable rather than merely different."
)

RESULT = (
    "Nine findings fixed and verified. The critical one: audit rehydration now reads each "
    "partition's signed checkpoint from the audit_checkpoints table that migration 0002 already "
    "created, and refuses to start when the rehydrated head is behind the checkpoint or its hash "
    "does not match, with fourteen tests including one that pins the limitation for readers that "
    "cannot supply an anchor. The in-batch duplicate audit_id hole in Append is closed before the "
    "commit loop, so a batch the chain accepts is now a batch restore can rehydrate. The startup "
    "context reaches every rehydration read, after enumerating all five and finding three that had "
    "been discarding it. A restored idempotency outcome now reconstructs ModelID, EventType, "
    "IdempotencyScope and FailureBehavior from the recorded edge, so a retry after a restart "
    "returns what the same retry would have returned before one; ApprovalRecord is reported as a "
    "genuine schema gap rather than invented. The migrate CLI's status direction is now read-only, "
    "proven by running it against a virgin database and counting zero tables created; runs are "
    "serialised on a session-level advisory lock released on every path including a panicking "
    "migration; and a new -to bounds a revert, refusing an unknown or unapplied version rather "
    "than rounding it. The integration suite refuses a destructive reset against a database that "
    "does not name itself disposable, and an unset opt-in fails loudly because a silent skip is "
    "EV-064's defect. Both vacuous gates are closed, the bash rule consolidated into one "
    "implementation with the pytest test delegating to it. The ledger read is two queries instead "
    "of one per model, pinned by a call-count assertion. Full sweep after the fixes: gofmt clean; "
    "vet, build, unit -race, integration -race and go mod verify all 6 of 6 modules; sqlc vet 0 and "
    "regeneration stable; toolchain 14 of 14; migration rehearsal up, down to a clean catalog and "
    "up again; tests/ci 124 passed, up from 117; contracts VALID; research 109; backtest 47; "
    "project brain PASS; evidence audit 0 drifted; all five proof scripts hold. The G5 report was "
    "regenerated over the fixed tree and now digests 87 artifacts, up from 80."
)

DEFECT_FOUND_AND_FIXED = (
    "Nine defects, two of which are the substance of this record. First, tail truncation of an "
    "audit partition passed restore: readPartition stopped on a short page, restore verified only "
    "contiguity and hash linkage, and with no anchored head a deleted tail left a shorter chain "
    "that verified clean, so the process reported verified state it had not verified - and the "
    "comments in restore.go and reader.go already claimed truncation was refused. Fixed against the "
    "existing signed checkpoint, with no new table. Second, the drain mutation gate credited any "
    "non-zero test exit as a detection, so a mutation that broke compilation, or a drain test "
    "already failing at HEAD, would print [detected] and pass; it now runs an unmutated baseline "
    "and distinguishes a failing assertion from a build failure, a discrimination its sibling "
    "harness already had. Also fixed: status performed DDL; migrate up was unserialised; rollback "
    "was unbounded and CASCADE-destructive; the integration reset could destroy any database it "
    "was pointed at; the startup deadline was discarded where it is documented; restored "
    "idempotency outcomes lost five fields; the in-batch duplicate audit_id check did not exist "
    "while a comment said it did; the bash gate passed on zero blocks; and the ledger read was N+1 "
    "on the startup path. Separately, two of my own mistakes during this work, both caught: "
    "recording EV-069 needed two rounds of fixing unterminated string literals in the recorder "
    "script, and one verification block of mine silently omitted DATABASE_URL and reported three "
    "bogus exit codes until it was repeated properly."
)

SIGNIFICANCE = (
    "The generalisable finding is narrower than it looks and more useful. The durable anchor for "
    "audit integrity had been in the database since migration 0002, signed and constraint-guarded, "
    "with a generated query already reading it. Four gates and eighty digests of ceremony were "
    "built around the integrity claim, and the one property that claim rests on - that a truncated "
    "archive is refused - was not enforced, because the enforcement mechanism already existed and "
    "was simply not called. Ceremony is not coverage, and a check that verifies a property nobody "
    "wired up is a check of the check. The second generalisable point is about the gates: a gate "
    "that treats any failure as success is worse than no gate, because it is trusted. Both are the "
    "same lesson EV-067 recorded, now learned a second time on gates added after it."
)

CAVEATS = (
    "Five limitations, and the first is the important one. human_reviewer is still null. This "
    "review was performed by agents, and the fixes were implemented by agents, so the claim that "
    "these eleven findings are closed is a claim by the same kind of thing that raised them. The "
    "concrete evidence - enumerated startup reads, a virgin-database table count, a regenerated "
    "and twice-confirmed-stable query layer, five proof scripts, a call-count assertion - is real "
    "and reproducible, but a human who did not write any of it has still not looked. Second, two "
    "work streams had to be redone: one worker returned an empty result twice with no changes "
    "made, and finding 10 was implemented directly instead, which is why that fix has a different "
    "author and a different verification route from the other eight. Third, the re-review of "
    "whether the nine fixes actually close the nine findings has not happened; the tests and gates "
    "verify the fixes, not the review's completeness. Fourth, the workflow has still never "
    "executed on a GitHub runner, so runner-specific behaviour is unproven though all 40 run "
    "blocks are syntax-checked. Fifth, unchanged and still owned elsewhere: cross-store atomicity "
    "remains WI-120 and WI-121's, WI-117's unqualified audit and authz tables and RISK-14 remain "
    "other owners', the schema-version forward problem is untouched, the write path is still not "
    "exposed over HTTP, and a reader that cannot supply an anchor still rehydrates on contiguity "
    "and hash checks alone - now documented rather than hidden."
)

EXCEPTION = ""

ARTIFACTS = [
    ".kilo/ecc/project-brain/evidence.jsonl",
    "evidence/gates/G5-gate-report.json",
    "evidence/gates/G5-gate-report.md",
    "services/control-plane/audit/restore.go",
    "services/control-plane/audit/reader.go",
    "services/control-plane/audit/chain.go",
    "services/control-plane/audit/anchor_test.go",
    "services/control-plane/model/restore.go",
    "services/control-plane/model/identity_restore.go",
    "services/control-plane/model/store_read.go",
    "services/control-plane/model/store_read_bulk_test.go",
    "services/control-plane/migrate/store_sql.go",
    "services/control-plane/migrate/lock_test.go",
    "services/control-plane/migrate/plan_target_test.go",
    "services/control-plane/migrate/live_test.go",
    "services/control-plane/cmd/migrate/main.go",
    "services/control-plane/cmd/migrate/main_test.go",
    "services/control-plane/integration/harness_test.go",
    "services/control-plane/integration/destructive_guard_test.go",
    "services/control-plane/db/queries/model_registry.sql",
    "scripts/mutation_check_drain.py",
    "scripts/check_workflow_bash.py",
    "scripts/prove_mutation_gate_rejects_build_failure.py",
    "tests/ci/test_ci_workflow.py",
    "scripts/record_ev070.py",
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
