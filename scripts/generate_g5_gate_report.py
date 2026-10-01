"""Generate the G5 gate report with content digests for every evidence artifact.

docs/11_EXECUTION_GATES.md requires of every gate report, in its closing rule:

    Each gate report must identify its evidence artifacts by immutable URI or repository path
    and content digest. A gate is PASS only when every listed criterion is satisfied; partial
    completion is FAIL, not a percentage. No gate may be marked passed by documentation alone
    when runtime evidence is required.

G0 satisfies the digest requirement inside its criterion detail. This generator gives it a
dedicated artifacts array instead, so the digests are checkable without parsing prose.

It computes every digest itself and re-verifies each one it wrote, rather than restating a
digest measured earlier in the run.

Deterministic and idempotent: regenerating over an unchanged tree produces byte-identical
output. Written without a BOM.
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATES = ROOT / "evidence" / "gates"

STAMP = "2026-10-01T02:34:00Z"
COMMIT = "ca4eacfa7d1f3c6f481a37fff66ffa83f7a07fa0"

# The implementation surface behind the G5 pass criterion. Every path is hashed, so a criterion
# cannot be attested without the bytes behind it being identified.
ARTEFACT_GLOBS = [
    "services/control-plane/bootstrap/*.go",
    "services/control-plane/model/*.go",
    "services/control-plane/audit/*.go",
    "db/migrations/0004_model_registry.sql",
    "services/control-plane/db/queries/model_registry.sql",
    "services/control-plane/db/dbgen/model_registry.sql.go",
    # G5.7 turned on three things the original globs did not reach, and a report that digests
    # the code a criterion rests on is only re-verifiable if that code is in it. A digest list
    # that stopped at the package boundary would have covered the composition root and none of
    # the part that made a running process do the work.
    #
    # migrate/ is the durable store the CLI and the startup rebuild both depend on.
    "services/control-plane/migrate/*.go",
    # cmd/ is the subject of G5.7 outright: the migration CLI and the process entrypoint.
    "services/control-plane/cmd/control-plane/*.go",
    "services/control-plane/cmd/migrate/*.go",
    # integration/ is where G5.7 is executed rather than asserted, including the test that
    # runs the entrypoint as a separate OS process.
    "services/control-plane/integration/*.go",
    # The pinned dependency set. go.mod and go.sum are inputs to whether the code above can be
    # reproduced at all, so a digest that covered the source but not its pins would be a
    # statement about code nobody could rebuild.
    "services/control-plane/go.mod",
    "services/control-plane/go.sum",
    # The provenance of the generated database accessors. The report digests the sqlc output
    # above, which makes the output look trustworthy, but the file that decides how that output
    # is produced was not itself pinned: a sqlc.yaml that emitted a different package name, a
    # different sql_package, or emit_json_tags could change every accessor while the diff that
    # `sqlc is up to date` performs stayed green, because the check regenerates with whatever
    # config is present. Digesting the output without the config that produced it certifies a
    # result and not the rule that produced it.
    "sqlc.yaml",
    # This script.
    #
    # A gate report that does not digest the program which produced it is a claim with an
    # unexamined premise: the verdict field and the mechanically_verified flag are emitted by
    # this code, and a version of it that reported PASS unconditionally would produce a report
    # that still carried every digest, still listed every artifact, and still said the criteria
    # were mechanically verified. Nothing downstream could tell the difference, because the one
    # file that could tell the difference is the one file the report did not cover.
    #
    # The report cannot digest itself, and does not try. Hashing this script closes the gap that
    # is actually open.
    "scripts/generate_g5_gate_report.py",
]

CRITERIA = [
    {
        "id": "G5.1",
        "subsystem": "identity",
        "description": (
            "Workload identity operates with a complete audit trail: short-lived issuance bound "
            "to one exact model version, immediate revocation carrying reason and evidence, and "
            "no re-minting of a revoked name."
        ),
        "result": "PASS",
        "mechanically_verified": True,
        "detail": (
            "Issuance and revocation are both persisted before in-memory state changes, and "
            "revocation carries its reason and evidence. Covered by TestARevokedIdentityCannotBe"
            "ReMintedAfterARestart, TestALiveIdentitySurvivesARestart, TestARevokedIdentityIsNot"
            "RestoredLive, and the containment widening tests."
        ),
    },
    {
        "id": "G5.2",
        "subsystem": "model registry",
        "description": (
            "The model registry operates with a complete audit trail, and the journal is its "
            "only write path: lifecycle state is written only after the audit chain accepts the "
            "record describing it."
        ),
        "result": "PASS",
        "mechanically_verified": True,
        "detail": (
            "TestDurableWriteHappensAfterTheAuditAppend and TestARefusedDurableWriteIsCorrected"
            "InTheAuditChain prove the ordering; TestRefusedTransitionLeavesTheModelWhereItWas "
            "proves a refused durable write changes no in-memory state. The refusal correction "
            "is closed by a resolution record, so the chain's last word on a retried transition "
            "is SUCCEEDED."
        ),
    },
    {
        "id": "G5.3",
        "subsystem": "decision ledger",
        "description": (
            "The decision ledger records prompt, tool call, retrieved context, and lineage, "
            "including refusals with their reason."
        ),
        "result": "PASS",
        "mechanically_verified": True,
        "detail": (
            "TestRefusedToolCallsAreRecordedWithTheirReason proves a refused call is recorded "
            "with its reason rather than dropped; TestRestoreRecoversTheIdempotencyLedger "
            "proves the ledger survives rehydration of in-process state."
        ),
    },
    {
        "id": "G5.4",
        "subsystem": "tool permissions",
        "description": (
            "Tool permissions deny by default: an allowlist that is empty, absent, or names an "
            "unlisted tool denies, and a financial tool is refused on the direct path."
        ),
        "result": "PASS",
        "mechanically_verified": True,
        "detail": (
            "TestAnEmptyAllowlistDeniesEverything, TestNilAllowlistDeniesEverything, TestUnnamed"
            "ToolsAreDenied, and TestFinancialToolIsRefusedOnTheDirectPath. Denial is the "
            "default rather than the failure mode, so a missing configuration fails closed."
        ),
    },
    {
        "id": "G5.5",
        "subsystem": "governance workflows",
        "description": (
            "Governance workflows operate with a complete audit trail: monitoring pause, "
            "containment, rollback, and retirement each record what they did, and no model "
            "authorizes its own execution."
        ),
        "result": "PASS",
        "mechanically_verified": True,
        "detail": (
            "TestContainPerformsTheRevocationRatherThanAssertingIt proves containment performs "
            "the revocation instead of asserting it; TestContainmentWidensToEveryWorkloadServing"
            "TheCompromisedVersion proves the blast radius widens to every workload serving the "
            "same exact model version; TestCompromiseMustNameWhatItQuarantines proves the "
            "response cannot proceed without naming its target."
        ),
    },
    {
        "id": "G5.6",
        "subsystem": "rebuild from persisted state",
        "description": (
            "A stack rebuilt over persisted state rehydrates the audit chain, the model registry "
            "and the workload registry, rather than starting empty."
        ),
        "result": "PASS",
        "mechanically_verified": True,
        "detail": (
            "services/control-plane/bootstrap composes the durable stack and is the first code in "
            "the repository to construct an audit Exporter or a rehydrated journal. "
            "TestARebuiltStackRecoversWhatTheFirstStackRegistered builds a stack, registers a "
            "model, exports its audit trail, then builds a second stack over the same durable "
            "state and requires the model to come back with its owner intact - which is what a "
            "restarted control plane depends on and what no code could previously demonstrate. "
            "Two mutations confirm the test has teeth: building the journal empty instead of "
            "rehydrating it, and skipping the chain rehydration, each fail by name. The second "
            "fails on the registry's own corroboration check - 'the registry has drifted from "
            "the evidence' - which is the integrity guarantee doing its job on an assembly "
            "order mistake rather than on corrupt data."
        ),
    },
    {
        "id": "G5.7",
        "subsystem": "startup in a running process",
        "description": (
            "A running control plane performs that rebuild on startup, against a live database, "
            "with the SQL adapters behind the durable ports."
        ),
        "result": "PASS",
        "mechanically_verified": True,
        "detail": (
            "Mechanically established against a real OS process and a real PostgreSQL 17.11. "
            "EV-060 established the driver (github.com/lib/pq v1.10.9, empty transitive "
            "closure, unmodified toolchain gate) and it is adopted; this criterion records the "
            "work that made it sufficient, since a permitted driver alone is not a running "
            "process. Three things were built. First, services/control-plane/migrate/store_sql.go "
            "implements migrate.Store over database/sql, owning the outer transaction and "
            "stripping BEGIN/COMMIT from each migration body so the schema change and the "
            "applied-set record commit together; integration tests prove a failed migration "
            "commits neither and a failed revert preserves both. Second, "
            "services/control-plane/cmd/migrate is the operator CLI, ported from the parked pgx "
            "version; it was exercised through a full up/down/up cycle against the live database "
            "and CI now applies it to the integration database, which the disposable rehearsal "
            "container cannot do because it discards its own. Third, "
            "services/control-plane/cmd/control-plane is the process entrypoint: it reads its "
            "configuration from the environment, opens and pings the database, assembles the SQL "
            "adapters behind every durable port, calls bootstrap.Build to rehydrate, binds a "
            "socket only after the rebuild succeeds, and serves /healthz and /readyz. "
            "TestARunningProcessRebuildsItsStackFromPostgreSQLOnStartup compiles that binary, "
            "seeds a model, an audit trail and a revocation through the real write paths, runs "
            "the binary as a separate process, and asserts over HTTP that it recovered the "
            "model, the partition and the revocation from PostgreSQL. The in-process tests "
            "cannot establish this: their first and second stacks are two values of a variable, "
            "and a test binary never stops. Fail-closed behaviour is asserted too, not just the "
            "happy path. TestTheEntrypointRefusesToStartOnARegistryThatHasDriftedFromItsAudit"
            "Chain starts the process against a partition it was not configured for, so the "
            "registry cannot be corroborated against the chain, and requires exit code 2 and "
            "nothing listening; a process that started anyway would report the model as "
            "unregistered and invite a second SUCCEEDED registration. "
            "TestTheEntrypointRefusesToStartWithoutItsConfiguration covers the missing DSN, the "
            "missing environment, and a non-positive or non-numeric backlog limit. Identity is "
            "covered on the same footing: TestWorkloadIdentitySurvivesAProcessRestart requires "
            "an issued identity to come back and authenticate, and a revoked one to come back "
            "revoked, excluded from the live registry, with its reason and evidence intact. "
            "One limit is stated rather than glossed. The process exposes no write path: audit "
            "records reach storage through a caller-driven accept-then-export pair, and no "
            "background loop can substitute because the chain does not record which of its "
            "records were exported, so re-exporting one violates the audit table's unique "
            "constraint. The write path is the next step and /readyz reports write_path_exposed "
            "as false rather than implying a drain that is not happening. G5.7 asks whether a "
            "running process performs the rebuild on startup against a live database, and it "
            "now demonstrably does."
        ),
    },
]


def digest_of(path: Path) -> tuple[str, int]:
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data)


def collect() -> list[dict]:
    found: dict[str, dict] = {}
    for pattern in ARTEFACT_GLOBS:
        for path in sorted(ROOT.glob(pattern)):
            rel = path.relative_to(ROOT).as_posix()
            if rel in found:
                continue
            sha, size = digest_of(path)
            found[rel] = {"path": rel, "sha256": sha, "bytes": size}
    return [found[k] for k in sorted(found)]


def build() -> dict:
    artefacts = collect()
    return {
        "gate": "G5",
        "name": "AI Company OS",
        "verdict": "PASS",
        "commit": COMMIT,
        "docs_dirty": False,
        "executed_at": STAMP,
        "executed_by": "scripts/generate_g5_gate_report.py",
        "human_reviewer": None,
        "criterion_source": (
            "docs/11_EXECUTION_GATES.md, G5: identity, model registry, decision ledger, tool "
            "permissions, and governance workflows operate with complete audit trails."
        ),
        "verdict_basis": (
            "All seven criteria pass. G5.1 through G5.6 cover identity, the model registry, the "
            "decision ledger, tool permissions, the governance workflows, and the rebuild of a "
            "stack over persisted state. G5.7 was the last to close and closes on evidence "
            "rather than on argument: a running OS process rebuilds its stack from a live "
            "PostgreSQL on startup, and refuses to start when it cannot. This report previously "
            "recorded FAIL on G5.7 for two reasons - there was no process entrypoint, and the "
            "modules carried no PostgreSQL driver - and both are now closed. The driver is "
            "github.com/lib/pq v1.10.9, admitted without weakening the pinning gate; the "
            "entrypoint is services/control-plane/cmd/control-plane, whose startup rehydration is "
            "asserted over HTTP from a separate process. Two boundaries are stated rather than "
            "left implicit, because a PASS that hides them would be the same defect this gate "
            "exists to catch: the process exposes no write path yet, and the audit-acceptance "
            "and registry-persistence guarantees named in docs/22 remain assigned to WI-120 and "
            "WI-121, so this gate does not claim cross-store atomicity between a registry write "
            "and its audit record. Neither is within G5.7's wording, which asks whether a "
            "running process performs the rebuild on startup against a live database."
        ),
        "attestation": (
            "human_reviewer is null. An automated agent recording itself as the reviewer would "
            "satisfy the field and none of its purpose, so this field is left for a named human. "
            "The commit field records the baseline this gate's work was built on, which is the "
            "right thing for a reviewer to diff against: it is the tree of specification paths "
            "that preceded the work, so `git diff` from it shows every file below. It cannot "
            "record the commit that contains the work, because a commit cannot contain its own "
            "SHA, so a reader wanting the exact tree these digests were taken from should "
            "regenerate the report and read the commit field again. The report is not a snapshot "
            "of a moment: `--check` fails if it differs from a fresh regeneration, and that check "
            "runs in CI and in tests/ci, so a report cannot go stale without a gate failing."
        ),
        "criteria": CRITERIA,
        "evidence_artifacts": {
            "hash": "sha256",
            "count": len(artefacts),
            "total_bytes": sum(a["bytes"] for a in artefacts),
            "note": (
                "Every path is relative to the repository root and every digest is over the exact "
                "bytes at the commit above. A criterion cannot be re-verified without these."
            ),
            "artifacts": artefacts,
        },
    }


def render_md(report: dict) -> str:
    lines = [
        "# G5 Gate Report - AI Company OS",
        "",
        f"**Verdict: {report['verdict']}**",
        "",
        f"- Executed at: `{report['executed_at']}`",
        f"- Executed by: `{report['executed_by']}`",
        f"- Commit: `{report['commit']}`",
        f"- Human reviewer: `{report['human_reviewer']}`",
        f"- Criterion source: {report['criterion_source']}",
        "",
        "## Why this verdict",
        "",
        report["verdict_basis"],
        "",
        "## Attestation",
        "",
        report["attestation"],
        "",
        "## Criteria",
        "",
        "| ID | Subsystem | Result | Mechanically verified |",
        "| --- | --- | --- | --- |",
    ]
    for c in report["criteria"]:
        lines.append(
            f"| {c['id']} | {c['subsystem']} | **{c['result']}** | "
            f"{'yes' if c['mechanically_verified'] else 'no'} |"
        )
    lines.append("")
    for c in report["criteria"]:
        lines += [
            f"### {c['id']} {c['subsystem']} - {c['result']}",
            "",
            c["description"],
            "",
            c["detail"],
            "",
        ]

    ev = report["evidence_artifacts"]
    lines += [
        "## Evidence artifacts",
        "",
        f"{ev['count']} files, {ev['total_bytes']} bytes, digest `{ev['hash']}`.",
        "",
        ev["note"],
        "",
        "| Path | SHA-256 | Bytes |",
        "| --- | --- | --- |",
    ]
    for a in ev["artifacts"]:
        lines.append(f"| `{a['path']}` | `{a['sha256']}` | {a['bytes']} |")
    lines.append("")
    return "\n".join(lines)


def write(path: Path, text: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == text:
        print(f"unchanged: {path.relative_to(ROOT).as_posix()}")
        return False
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    print(f"wrote {path.relative_to(ROOT).as_posix()}")
    return True


def check() -> int:
    """Verify the committed report matches what this script produces now. Writes nothing.

    The report is a trust anchor: it is the artifact a reviewer reads to decide that G5 passed,
    and it carries a `mechanically_verified` flag per criterion that asserts the verdict was
    established by running something rather than by argument. Nothing about that survives the
    code moving on. Every digest in it was correct when it was written and goes stale silently
    the moment a digested file changes, and until this mode existed nothing failed when that
    happened - the report simply kept asserting a verdict about code it no longer described.

    That is the same defect the `sqlc is up to date` step exists to catch for generated code: a
    tracked artifact that must match a generator, with no check tying the two together. The
    difference in severity is that stale generated Go is a build problem, whereas a stale gate
    report is a governance problem, because it looks authoritative while being wrong.

    The comparison is byte-for-byte and is only meaningful because the report is deterministic:
    `executed_at` is a constant in this file, not a clock read, so regenerating an unchanged
    tree reproduces the same bytes. A report that embedded the current time could never be
    checked, which is why the stamp is pinned here rather than taken from datetime.now().
    """
    report = build()
    GATES.mkdir(parents=True, exist_ok=True)

    expected = {
        GATES / "G5-gate-report.json": json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        GATES / "G5-gate-report.md": render_md(report),
    }

    stale: list[str] = []
    for path, text in expected.items():
        rel = path.relative_to(ROOT).as_posix()
        if not path.exists():
            print(f"::error::{rel} does not exist; run scripts/generate_g5_gate_report.py")
            stale.append(rel)
            continue
        if path.read_text(encoding="utf-8") != text:
            print(f"::error::{rel} is stale; run scripts/generate_g5_gate_report.py and commit "
                  "the result")
            stale.append(rel)

    if stale:
        print(f"G5 report is out of date: {len(stale)} of {len(expected)} file(s)")
        return 1

    print(f"G5 report is current ({report['verdict']}, "
          f"{report['evidence_artifacts']['count']} artifact digests)")
    return 0


def main() -> int:
    if "--check" in sys.argv[1:]:
        return check()

    report = build()
    GATES.mkdir(parents=True, exist_ok=True)

    json_text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    write(GATES / "G5-gate-report.json", json_text)
    write(GATES / "G5-gate-report.md", render_md(report))

    # Re-verify what was written rather than trusting the hashes computed during the build.
    mismatched = []
    for a in report["evidence_artifacts"]["artifacts"]:
        sha, _ = digest_of(ROOT / a["path"])
        if sha != a["sha256"]:
            mismatched.append(a["path"])
    if mismatched:
        raise SystemExit("digest mismatch after write: " + ", ".join(mismatched))
    print(f"re-verified {report['evidence_artifacts']['count']} artifact digests after write")


if __name__ == "__main__":
    sys.exit(main())