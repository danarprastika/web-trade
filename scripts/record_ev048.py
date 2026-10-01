"""One-off: append EV-048 recording the audit read side and a latent defect in durable evidence.

Two things are recorded. The reader that EV-047 identified as the missing half is implemented.
And in the act of implementing it, a defect was found in code that had been shipping since
EV-045: SQLSink writes audit records whose hashes cannot be reproduced from the stored row, so
every real record would be rejected as tampering by any verifier that recomputes the hash.

EV-047 also reported a mutation harness that found 6 of 8 and whose false positive went
unnoticed. This record corrects that count and explains how it happened.

Idempotent, append-only, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-048"
STAMP = "2026-09-30T13:50:00Z"

WORK_ITEM = "WI-141"

CLAIM = (
    "The audit read side exists, so the rehydration blocker from EV-041 through EV-047 is "
    "closed on the Go side. Building it exposed a latent defect in durable evidence that has "
    "been shipping since EV-045: audit records were being written whose hash cannot be "
    "reproduced from the stored row, because the hashed payload carries nanosecond timestamps "
    "and the columns are timestamptz, which holds microseconds. Every record carrying "
    "sub-microsecond precision - which is every record whose timestamp came from time.Now() - "
    "would be rejected as tampering by any independent verifier that recomputes the hash, and "
    "docs/22 section 3 requires exactly that. The defect is fixed by canonicalising the audit "
    "instant to the resolution the store can hold. Separately, EV-047's mutation result of 6 of "
    "8 is corrected: one of the two detections it reported was a false positive, and the "
    "harness that should have caught it was comparing against a file it had already corrupted."
)

METHOD = (
    "Started from the SQL layer rather than from Go, because EV-047's useful finding was that "
    "the queries already existed: ListAuditRecordsInPartitionRange returns a partition's records "
    "ordered by sequence, and GetLatestAuditCheckpoint gives the signed closure. That made the "
    "remaining work a port and a mapping rather than infrastructure, and it also set the "
    "question that mattered. Restore recomputes the hash of every record it loads, so before "
    "writing the reader I checked what the hashed payload actually contains - canonicalFields in "
    "record.go covers 23 fields including both timestamps at nine fractional digits - against "
    "the column types in 0002_audit.sql, which declare both timestamps timestamptz. Wrote "
    "ChainReader, SQLChainReader and Rehydrate, with recordFrom as the exact inverse of "
    "paramsFor. Wrote the round-trip test before the fix, deliberately, so that the defect would "
    "be demonstrated rather than asserted - and it failed, with Restore refusing as tampered a "
    "record the sink had just written. Then applied a mutation harness to the new code, which is "
    "where the EV-047 correction came from."
)

RESULT = (
    "The defect is confirmed empirically and then fixed. A record built with a nanosecond-bearing "
    "timestamp, written through the sink's own mapping and stored through PostgreSQL's own "
    "timestamptz resolution, comes back with a different value: the canonical rendering differs in "
    "the last three digits, the recomputed hash differs, and Restore refuses it as tampering with "
    "the message that the stored content has been altered since it was written. The fix "
    "canonicalises the instant to one microsecond inside NewRecord, which is the single point "
    "every construction path passes through, and truncates rather than refuses because the "
    "discarded precision cannot survive the write either way. The fix is in NewRecord rather than "
    "in TimestampFrom because a Record can be assembled from a contracts.Timestamp directly - the "
    "package's own fixtures do it - so a fix in the converter would leave that path unnormalised "
    "while the round-trip test still passed, since that fixture goes through the converter. The "
    "defect was pre-existing and would have shipped: the database trigger in 0002_audit.sql checks "
    "chain linkage by comparing stored record_hash values to each other, so it never recomputes a "
    "hash from content and could never have noticed. Only a recompute-from-content check finds it, "
    "and Restore is the first thing in the repository that performs one. The reader itself is "
    "verified: 22 new tests covering field-by-field round-trip, both mapping directions, hash "
    "length refusal, driver-slice copying, schema-version refusal, error propagation, paging that "
    "terminates, and multi-partition rehydration. A mutation harness reports 9 of 9 detected "
    "against a verified-pristine baseline, with both sources restored byte-for-byte. All 13 "
    "project gates pass, the audit and model suites pass under -race, go vet and gofmt are clean."
)

DEFECT_FOUND_AND_FIXED = (
    "Four defects, and the third is the one that matters most. First, the timestamp defect "
    "described above, in code that had been shipping since EV-045. Second, and in my own new "
    "code: Rehydrate originally called Restore once per partition, which cannot work, because "
    "Restore refuses a chain that already holds records - so the second partition would always "
    "fail. Caught by reading the two functions against each other rather than by a test, and "
    "fixed by restoring the whole archive once, which is correct because Restore stages per "
    "partition independently. Third, the mutation harness. Its first run crashed part-way through "
    "and left a mutation on disk. The next run took its baseline hash from that already-corrupted "
    "file, so every subsequent 'restored byte-for-byte' was a comparison against the corruption "
    "it existed to detect, and the corrupted file survived into the source tree until a build "
    "error exposed it. Worse, that leftover made one mutation of mine report as DETECTED when it "
    "had changed nothing: its replacement still performed the same array copy, so the only reason "
    "the suite failed was the pollution. The harness now refuses to run unless the tree builds "
    "cleanly first, and M12 was rewritten to actually remove the byte transfer. The general form "
    "is that a hash comparison proves 'unchanged since this run started' and never 'correct when "
    "this run started', which is precisely the gap a restoration check appears to close. Fourth, "
    "a test of mine was self-defeating: TestNewRecordCanonicalisesInstantPrecision built its "
    "nanosecond fixture by calling audit.TimestampFrom, which by then truncated, so the guard "
    "asserting the two forms hashed differently was comparing a value against itself. The fixture "
    "now uses contracts.ParseTimestamp, which is also the path the fix actually exists to cover."
)

SIGNIFICANCE = (
    "The substantive finding is that a tamper-evident store can be tamper-evident only in the "
    "direction it checks. The evidence chain was internally consistent and correctly linked, and "
    "the database enforced the linkage, and every layer agreed - and none of them recomputed a "
    "hash from content, so none of them could detect that a verifier working purely from the "
    "migration would compute different hashes and conclude the whole archive was forged. A "
    "control that verifies its own outputs against each other rather than against the rule is "
    "self-consistent under tampering that preserves consistency. This is the reason Restore was "
    "worth building even though the rehydration capability was its ostensible purpose: adding the "
    "check found a defect in the write path, and the write path was not under suspicion when the "
    "work started. The second point is about verification infrastructure being part of the "
    "system under test. Two of the four defects here were in the harness, and both produced "
    "confident wrong answers - a false detection and a silent corruption - rather than obvious "
    "failures. A verification tool that cannot fail visibly is more dangerous than none, because "
    "it is trusted."
)

CAVEATS = (
    "Five limitations. First, and unchanged from EV-046: no Go process has connected to a "
    "PostgreSQL instance and called the reader, the sink, or the stores. The round-trip is proved "
    "by modelling the driver's row type and PostgreSQL's timestamp resolution, not against a live "
    "database; the 20 database assertions in db-0002-audit cover the statements and the schema but "
    "not the Go mapping. The model is written out in the test rather than hidden so a reader can "
    "see exactly what is being assumed. Second, the truncation is a deliberate loss of precision. "
    "Nanoseconds in an audit instant are not preserved, because timestamptz cannot hold them; a "
    "reviewer who believes otherwise should know it is the store's limit being adopted rather "
    "than a choice made here. Third, the fix changes the hash basis for audit records, so it "
    "invalidates the record hashes recorded in EV-045's mutation evidence. That is acceptable only "
    "because nothing has ever been written - and it would not be acceptable after a first write, "
    "which makes this the last cheap moment to make the change. Fourth, the forward-compatibility "
    "limit identified while checking the schema is NOT fixed: canonicalFields hashes the package "
    "constant rather than a per-record value, and the column is CHECK (schema_version = 1), so a "
    "future schema bump makes every existing record un-re-derivable by design rather than by "
    "accident. Given seven-year retention that is a real forward problem, and it is recorded "
    "rather than fixed because the fix changes a security-relevant invariant and belongs to a "
    "human decision. Fifth, scope: the model journal's rehydration, the identity store's missing "
    "read side and the non-atomic audit/registry commit were not touched, and no composition root "
    "constructs a Chain, Guard, Exporter, reader or journal, so nothing yet calls Rehydrate in "
    "production. Also unchanged: the mutation harness was run as a verification activity and its "
    "script and backups were deleted - the repository's own spec gate correctly refuses stray "
    "files in the project-brain directory, which is how the leftover backups were caught; no "
    "specification file was modified, docs/ remains clean, nothing was staged, and nothing was "
    "committed."
)

EXCEPTION = ""

ARTIFACTS = [
    "services/control-plane/audit/reader.go",
    "services/control-plane/audit/reader_test.go",
    "services/control-plane/audit/reader_path_test.go",
    "services/control-plane/audit/record.go",
    "services/control-plane/audit/restore.go",
    "db/migrations/0002_audit.sql",
    "services/control-plane/db/queries/audit.sql",
    "docs/22_AUDIT_INTEGRITY_AND_EVIDENCE.md",
    "scripts/record_ev048.py",
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
