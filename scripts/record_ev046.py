"""One-off: append EV-046 recording the driver-pinning investigation and its negative result.

The blocker has been asserted as unsolvable in EV-042, EV-043 and EV-045 without anyone
reading the gate's actual rule or testing a workaround. This record verifies the claim
empirically, confirms it, and - the useful part - records the one workaround that appears to
work and why it does not, so the next person does not spend an afternoon on it.

Idempotent, append-only, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-046"
STAMP = "2026-09-30T12:40:00Z"

WORK_ITEM = "WI-141"

CLAIM = (
    "The Go database driver blocker is real, and it is now demonstrated rather than "
    "asserted - but it is narrower than three prior evidence records stated it, and the one "
    "workaround that appears to satisfy the gate does not survive `go mod tidy`. No pgx v5 "
    "release can be added to the control plane without the toolchain gate failing, and the "
    "workaround that makes the gate pass is a latent CI failure rather than a fix."
)

METHOD = (
    "Stopped propagating the claim and read verify_toolchain.py's actual rule rather than its "
    "summary: it reads go.mod as text, never resolves the module graph, and exempts "
    "filesystem replace directives. Probed the module proxy for the real version landscape: "
    "pgx/v5 tops out at v5.11.0, matching what the prior records said, and pgservicefile "
    "returns an empty version list with @latest resolving to a v0.0.0-2024 pseudo-version, "
    "confirming it has no tagged release at all. Built a throwaway module inside the "
    "repository, imported pgx's stdlib driver, and let `go mod tidy` produce the go.mod "
    "unmodified, which showed pgservicefile entering the require block as an indirect "
    "pseudo-version. Ran the repository's own verify_go_pins function against three candidate "
    "go.mod forms rather than reasoning about what it would do. Deleted the scratch module; "
    "the repository's own go.mod was never touched."
)

RESULT = (
    "The blocker is confirmed and its exact mechanism is now known. `go get pgx/v5@v5.11.0` "
    "adds `github.com/jackc/pgservicefile v0.0.0-20240606120523-5a60cdf6a761` to the require "
    "block, and verify_toolchain.py rejects any require beginning `v0.0.0-`. Running the "
    "gate's own function against that go.mod returns FAIL with the expected message. The "
    "narrower part of the correction: the prior records said no driver could satisfy the gate, "
    "which is true of every release as published, but the gate's rule is about the text of "
    "go.mod and it explicitly exempts filesystem replaces. A go.mod carrying "
    "`require github.com/jackc/pgservicefile v0.0.0` alongside "
    "`replace github.com/jackc/pgservicefile => ./third_party/pgservicefile` PASSES the gate, "
    "verified by running the gate against it, and `v0.0.0` is not rejected because it is not "
    "a pseudo-version and matches the tagged-release pattern. So the claim 'no form satisfies "
    "the gate' is false. The claim that survives is narrower and is the one that matters: that "
    "form does not survive `go mod tidy`. Given a real pgx import and the local replace in "
    "place, tidy rewrote the require straight back to the pseudo-version, because the recorded "
    "version comes from the build list pgx demands rather than from what go.mod says. The "
    "build succeeded either way, so a committed go.mod in that form would pass the gate today "
    "and fail the next time anyone ran tidy - which is the worst property a supply-chain gate "
    "fix can have, because it looks solved and reopens itself."
)

DEFECTS = (
    "Two defects, both in my own prior records. First, the claim was propagated three times "
    "without being tested or without anyone reading the rule it depends on. EV-042, EV-043 and "
    "EV-045 each restate that no driver satisfies the pinning gate, and each cites the pgx "
    "v5.0.0-to-v5.11.0 range as though that had been established rather than assumed. The "
    "version range is correct - the proxy confirms it - but the conclusion drawn from it was "
    "never checked against verify_toolchain.py, which had meanwhile grown a filesystem-replace "
    "exemption that makes a passing form exist. The general form is that a blocker restated "
    "three times starts to read as a law of nature rather than a finding, and the second and "
    "third restatements cite the first as authority instead of as a claim. Second, and found "
    "while writing this record: I read Report.checks_run as a count of checks performed and "
    "concluded that a candidate go.mod passing with '0 pins checked' had simply been skipped by "
    "the parser. It had not. checks_run is incremented only by report.check, and report.check "
    "is only called on failure, so the field counts failures - '0' means every pin was valid. I "
    "had the polarity of the gate's own instrumentation backwards, which is a small thing in "
    "isolation and a good illustration of why a verification tool's output needs reading as "
    "carefully as the code it verifies."
)

SIGNIFICANCE = (
    "Two general forms. The first is about negative results. A workaround that passes the gate "
    "on the day it is written and fails after the next ordinary maintenance command is worse "
    "than an acknowledged blocker, because it converts a known, visible, honestly recorded gap "
    "into an intermittent one that will be discovered by someone who has no idea it was ever "
    "addressed. Recording that the workaround exists, that it passes, and that tidy reverts it "
    "is worth more than the workaround, because the next person can skip the experiment and "
    "still knows the shape of the ground. The second form is about a class of defect that is "
    "invisible to the thing that would catch it: a build broken by an environment the "
    "reproducing environment does not share. A CI failure that appears only where a test can "
    "reach a network is a test that has quietly stopped being a test, and the fix is not to "
    "make the test more forgiving but to make its reachability a property the suite asserts."
)

CAVEATS = (
    "Four limitations on this record. First, the investigation was conducted in a throwaway "
    "module inside the repository and then deleted; the control plane's own go.mod was never "
    "modified, so nothing here has been proven to build inside the real module, only inside an "
    "equivalent one. Second, and the reason this could not simply be fixed: the three ways out "
    "are all decisions reserved for a human. Amending verify_toolchain.py to permit a "
    "pseudo-version for a specific audited commit weakens a supply-chain control, and doing "
    "that to unblock one's own work is precisely the move a gate exists to prevent. Switching "
    "to github.com/lib/pq, which is tagged, contradicts the stack table at "
    "docs/00_README.md line 24, and docs/ is immutable. Accepting the gap is the third. Third, "
    "the consequence of the gap is unchanged and is recorded against WI-141, WI-117 and the "
    "model store: no Go process has ever connected to a database and called SQLStore, "
    "SQLIdentityStore or SQLSink, so their transaction, commit, isolation-level and "
    "mid-commit driver-error paths remain unproven. What is proven is that the statements are "
    "accepted by real PostgreSQL - 137 database assertions across the four migrations - that "
    "the generated accessors compile and match the schema under sqlc vet, and that the "
    "ordering and refusal behaviour of the Go side holds against stores that can fail. Fourth, "
    "the untagged dependency is an upstream packaging gap rather than a choice made here: "
    "pgservicefile has no tagged release at all, so there is no tagged version to move to, and "
    "a future pgx release that tags or drops it would resolve this with no action here. Also "
    "unchanged: the mutation harness remains a verification activity rather than a release "
    "gate; no specification file was modified, docs/ remains clean, the scratch module was "
    "removed, nothing was staged, and nothing was committed."
)

ARTIFACTS = [
    "scripts/verify_toolchain.py",
    "scripts/record_ev046.py",
    "docs/00_README.md",
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
    "event_id": "EVT-WI-141-DRIVER-PINNING-INVESTIGATED",
    "recorded_at": STAMP,
    "recorded_by": "team-lead",
    "work_item": WORK_ITEM,
    "event": "investigation_recorded",
    "status": "RECORDED",
    "evidence_ref": EVIDENCE_ID,
    "summary": (
        "The Go database driver blocker is now demonstrated rather than asserted, and it is "
        "narrower than EV-042, EV-043 and EV-045 stated. Mechanism confirmed: `go get "
        "pgx/v5@v5.11.0` adds `pgservicefile v0.0.0-20240606120523-5a60cdf6a761` to the "
        "require block, and verify_toolchain.py rejects any require starting `v0.0.0-` - "
        "verified by running the gate's own function against a real tidied go.mod, which "
        "returns FAIL. pgservicefile has no tagged release at all: the proxy returns an empty "
        "version list and @latest is that pseudo-version, so there is no tagged version to "
        "move to. The correction: the gate reads go.mod as text, never resolves the module "
        "graph, and explicitly exempts filesystem replaces, so `require "
        "pgservicefile v0.0.0` plus a local directory replace PASSES the gate - verified, not "
        "assumed. So 'no form satisfies the gate' is false. What survives is narrower and is "
        "what matters: that form does not survive `go mod tidy`, which rewrites the require "
        "straight back to the pseudo-version because the recorded version comes from the "
        "build list pgx demands. The build succeeds either way, so committing that form would "
        "pass the gate today and fail after the next tidy - a latent CI failure that looks "
        "solved and reopens itself, which is worse than the acknowledged gap. Not fixed, and "
        "all three ways out are human decisions: amending the gate to permit a pinned "
        "pseudo-version weakens a supply-chain control and doing that to unblock my own work "
        "is what a gate exists to prevent; github.com/lib/pq is tagged but contradicts the "
        "stack table at docs/00_README.md line 24, and docs/ is immutable; or the gap is "
        "accepted. Consequence unchanged: no Go process has ever connected to a database, so "
        "SQLStore, SQLIdentityStore and SQLSink keep unproven transaction, commit, isolation "
        "and mid-commit-error paths, while the statements themselves are proven by 137 "
        "database assertions and the accessors by sqlc vet. Two defects recorded, both mine: "
        "the claim was propagated three times without being tested, the second and third "
        "restatements citing the first as authority rather than as a claim, and the gate had "
        "meanwhile grown a filesystem-replace exemption that makes a passing form exist; and "
        "I misread Report.checks_run as a count of checks performed, concluding a candidate "
        "go.mod had been skipped by the parser, when it counts failures and '0' means every "
        "pin was valid. The scratch module was deleted and the repository's go.mod was never "
        "touched. WI-141 stays IN_PROGRESS."
    ),
}


def append_jsonl(path: Path, record: dict) -> None:
    with io.open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=True) + "\n")


PARTIAL_RESULTS = (
    "AC1 registry/audit/idempotency verified: journal.go is the registry's only write path and "
    "writes the lifecycle state only after the audit chain accepts the record describing it. "
    "AC2 no model authorizes its own execution verified. AC3 tool permission-denial, model "
    "rollback, and lineage verified. AC4 all four compromise actions verified, with "
    "containment widening from the detected workload to every workload serving the same exact "
    "model version and a blast radius derived from recorded revocations rather than the live "
    "set. Identity: short-lived workload identity bound to one exact model version, with "
    "immediate idempotent revocation carrying reason and evidence, no re-minting of a revoked "
    "name, and both issuance and revocation persisted durably before the in-memory state "
    "changes. Persistence: 0004_model_registry.sql provides a durable registry, identity, "
    "revocation and idempotency store proven against real PostgreSQL 17 with 45 assertions; "
    "19 sqlc queries preserve audit-causation and blast-radius-from-recorded-revocations in "
    "SQL; the journal's writes go through a two-method Store port and WorkloadRegistry's "
    "through a two-method IdentityStore with no read and no delete, so audit-before-state "
    "ordering, transition atomicity, a refused write leaving in-memory state untouched, and a "
    "refused issuance or revocation changing nothing are each proven against stores that can "
    "fail. 149 model tests race-clean, 83 audit tests, 41 of 41 model mutations and 10 of 10 "
    "audit mutations applied and detected with byte-for-byte restore, all 13 gates PASS. "
    "Defects found and fixed, this work item's own: 4 of 41 model mutations were build "
    "failures the harness was counting as detections, so EV-042 and EV-043 overstated their "
    "coverage; the one claim among them, that a refusal is not a state change, was enforced "
    "by no test until one was added; that mutation was itself a no-op because it drew its "
    "partition from the zero Record on the branch it injected into; an audit mutation tested a "
    "property that could not fail because the language already provides the copy it claimed "
    "the code was making; and the driver-pinning blocker was propagated across three evidence "
    "records without being tested, which EV-046 corrects. REMAINING, in severity order: the "
    "pinned-driver gap, now understood precisely by EV-046 - no Go process has ever connected "
    "to a database, so SQLStore, SQLIdentityStore and SQLSink keep unproven transaction, "
    "commit, isolation-level and mid-commit-error paths, and all three ways out are reserved "
    "for a human; the store and identity store are write-only, so a restarted WorkloadRegistry "
    "authenticates against an empty live set and refuses identities the database holds as "
    "validly issued - safe, because it fails closed, but it means EV-040's containment "
    "widening is lost with the process that observed the compromise, and rehydration is "
    "blocked rather than deferred because the audit chain is in-memory; there is no "
    "cross-store transaction on either the model or the identity path, so a refused durable "
    "write leaves a SUCCEEDED audit record describing a change that did not take effect; Mint "
    "and Revoke still default to context.Background() for the existing callers; "
    "Authenticate performs no cryptographic verification; Contain does not itself perform the "
    "model's lifecycle quarantine; containment quarantines only the artifacts named in the "
    "declaration; and workload_revocations.evidence_ref is free text rather than a foreign "
    "key to a forensic store. Gate verdict FAIL; work item remains IN_PROGRESS."
)


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
        if item["id"] != WORK_ITEM:
            continue
        refs = item.get("evidence_ref", [])
        if EVIDENCE_ID not in refs:
            item["evidence_ref"] = [*refs, EVIDENCE_ID]
            changed = True
        item["partial_results"] = PARTIAL_RESULTS
        changed = True
    if changed:
        io.open(work_path, "w", encoding="utf-8", newline="\n").write(
            json.dumps(doc, indent=2, ensure_ascii=True) + "\n"
        )
        print(f"{WORK_ITEM} evidence and partial_results updated")
    else:
        print("work item already up to date")

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
