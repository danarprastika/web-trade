#!/usr/bin/env python3
"""Human attestations for gate reports, and the rule that stops them going stale.

docs/11_EXECUTION_GATES.md requires every gate report to name its reviewer, and docs/11 also says a
gate is PASS only when every listed criterion is satisfied. Three gates - G0, G1 and G4 - are held
open solely because the reviewer field cannot be produced by an automated agent, and recording the
agent as the reviewer would satisfy the field and none of its purpose.

So the reviewer is a human, and this is where that human's judgement is recorded. It is deliberately
not a name typed into a gate script: a name written into source is a claim with no evidence behind it,
which is the same defect this repository has now recorded eight times in other guises.

Two properties make an attestation worth more than the string it contains.

  It binds to a digest of the report. `report_digest` hashes the report with the attestation-derived
  fields removed, so the digest covers exactly what the reviewer read and nothing the gate computed
  afterwards. An attestation for an older report cannot be reused: the moment the tree moves, the
  digest changes and the attestation reports STALE and the gate refuses again. Without this, an
  attestation would be a permanent licence that survives any amount of later change - which is
  strictly worse than no mechanism at all, because it looks like accountability.

  It names a commit, checked against HEAD. Same reasoning: an attestation is a judgement about a
  specific state of the repository.

Reviewer names are rejected if they look like an agent. That is a blunt instrument and it is here
because the failure it prevents is worse than the false positive it risks: `reviewer: automated
agent` is exactly the value docs/11 forbids, and the cheapest way for it to get in is for a well
meaning tool to accept whatever string it is handed.

Run:  python scripts/attestation.py --gate G1 --reviewer "Ada Lovelace" --statement "..."
       python scripts/attestation.py --check G1
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
ATTESTATIONS = ROOT / ".kilo" / "ecc" / "attestations"

SCHEMA = "ecc.project-brain/attestation/v1"

# Fields the attestation fills in. They are removed before hashing so that recording an attestation
# does not change the digest it is checked against - otherwise the first write would invalidate itself.
ATTESTED_PATHS = ("required_report_fields.reviewer", "required_report_fields.commit")

REQUIRED = ("gate", "reviewer", "reviewer_role", "attested_at", "commit_reviewed", "statement")

# Substrings that mark a reviewer as an agent rather than a person. Checked case-insensitively against
# the whole name.
NOT_A_HUMAN = (
    "agent",
    "automated",
    "assistant",
    "bot",
    "chatgpt",
    "claude",
    "copilot",
    "cursor",
    "gpt",
    "kilo",
    "llm",
    "none",
    "tbd",
    "unknown",
)

MIN_STATEMENT_CHARS = 40

RESOLVED = "RESOLVED"
OUTSTANDING = "OUTSTANDING"
STALE = "STALE"
MALFORMED = "MALFORMED"


def _git(*args: str) -> str:
    try:
        out = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unavailable"
    return out.strip()


def head() -> str:
    return _git("rev-parse", "HEAD")


def path_for(gate: str) -> pathlib.Path:
    return ATTESTATIONS / f"{gate.upper()}.json"


def _prune(value):
    """Remove the attestation-derived fields, so hashing is stable across recording."""
    if isinstance(value, dict):
        return {
            k: _prune(v)
            for k, v in value.items()
            if k not in {"reviewer", "commit", "attestation"}
        }
    if isinstance(value, list):
        return [_prune(v) for v in value]
    return value


def report_digest(report: dict) -> str:
    """SHA-256 over what the reviewer attests to.

    If the gate publishes an `attested_payload`, that is the surface: the exact set of criteria and
    provenance the reviewer read. It deliberately excludes any criterion that depends on the
    attestation itself, so recording a signature cannot change the digest it is checked against - which
    would make the mechanism permanently STALE and therefore permanently useless.

    Otherwise the whole report is hashed, pruned of attestation-derived fields.

    Canonical JSON, sorted keys, no whitespace variance: two runs of the same gate over an unchanged
    tree must produce the same digest, or an attestation would go stale for no reason.
    """
    payload = report.get("attested_payload")
    if not isinstance(payload, dict):
        payload = _prune(report)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _problems(record: object, gate: str) -> list[str]:
    if not isinstance(record, dict):
        return ["attestation is not a JSON object"]
    problems: list[str] = []
    for field in REQUIRED:
        value = record.get(field)
        if not isinstance(value, str) or not value.strip():
            problems.append(f"{field} is missing or empty")
    if record.get("schema") not in (None, SCHEMA):
        problems.append(f"unknown attestation schema {record.get('schema')!r}")
    if isinstance(record.get("gate"), str) and record["gate"].upper() != gate.upper():
        problems.append(f"attestation is for gate {record['gate']}, not {gate.upper()}")
    reviewer = record.get("reviewer")
    if isinstance(reviewer, str) and reviewer.strip():
        lowered = reviewer.lower()
        hit = [token for token in NOT_A_HUMAN if token in lowered]
        if hit:
            problems.append(
                f"reviewer {reviewer!r} reads as an agent rather than a person "
                f"(matched {', '.join(hit)}); docs/11 requires a named human reviewer"
            )
    statement = record.get("statement")
    if isinstance(statement, str) and len(statement.strip()) < MIN_STATEMENT_CHARS:
        problems.append(
            f"statement is {len(statement.strip())} characters; a reviewer attestation that says "
            f"nothing is not an attestation"
        )
    return problems


def evaluate(gate: str, report: dict | None = None) -> tuple[str, dict | None, list[str]]:
    """Resolve an attestation against the report it claims to cover.

    Returns (status, record, problems). `report` is the gate's report dict; when omitted the digest
    check is skipped, which is only appropriate for asking whether a record exists at all.
    """
    path = path_for(gate)
    if not path.is_file():
        return OUTSTANDING, None, [f"no attestation recorded at {path}"]
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return MALFORMED, None, [f"attestation is not valid JSON: {exc}"]

    problems = _problems(record, gate)
    if problems:
        return MALFORMED, record, problems

    if report is not None:
        expected = report_digest(report)
        claimed = record.get("attested_digest")
        if claimed != expected:
            return (
                STALE,
                record,
                [
                    f"attestation covers a different report: it attests digest "
                    f"{str(claimed)[:12]}, this report digests {expected[:12]}. The tree has moved "
                    f"since the reviewer signed, so the review no longer covers what the gate is "
                    f"about to report. Re-attest, do not re-use."
                ],
            )

    reviewed = record.get("commit_reviewed")
    current = head()
    if reviewed and current != "unavailable" and reviewed != current:
        return (
            STALE,
            record,
            [
                f"attestation names commit {reviewed[:12]} but HEAD is {current[:12]}; a review is a "
                f"judgement about one state of the repository"
            ],
        )

    return RESOLVED, record, []


def _write(gate: str, record: dict) -> pathlib.Path:
    ATTESTATIONS.mkdir(parents=True, exist_ok=True)
    path = path_for(gate)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gate", help="gate identifier, e.g. G1")
    parser.add_argument("--reviewer", help="the named human reviewer")
    parser.add_argument("--role", default="reviewer", help="the reviewer's role or capacity")
    parser.add_argument("--statement", help="what the reviewer examined and concluded")
    parser.add_argument("--commit", help="commit reviewed; defaults to HEAD")
    parser.add_argument(
        "--check", help="report the status of an existing attestation without writing one"
    )
    args = parser.parse_args(argv)

    if args.check:
        gate = args.check
        status, record, problems = evaluate(gate)
        print(f"attestation {gate.upper()}: {status}")
        if record:
            print(f"  reviewer: {record.get('reviewer')} ({record.get('reviewer_role')})")
            print(f"  attested_at: {record.get('attested_at')}")
            print(f"  commit_reviewed: {record.get('commit_reviewed')}")
        for problem in problems:
            print(f"  - {problem}")
        return 0 if status == RESOLVED else 1

    if not (args.gate and args.reviewer and args.statement):
        parser.error("--gate, --reviewer and --statement are required to record an attestation")

    gate = args.gate.upper()
    record = {
        "schema": SCHEMA,
        "gate": gate,
        "reviewer": args.reviewer.strip(),
        "reviewer_role": args.role.strip(),
        "attested_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit_reviewed": args.commit or head(),
        "statement": args.statement.strip(),
        "attested_digest": None,
    }
    status, _record, problems = evaluate(gate, None)
    problems = _problems(record, gate)
    if problems:
        print("attestation REFUSED; it would not be accepted by a gate:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    del status

    report = _gate_report(gate)
    if report is not None:
        record["attested_digest"] = report_digest(report)
    else:
        record["attested_digest"] = "no-report-yet"
        print(
            f"note: {gate} has no generated report on this tree, so the attestation is recorded "
            f"with attested_digest='no-report-yet'. It will read STALE until the report is "
            f"generated and the reviewer re-attests against it."
        )

    path = _write(gate, record)
    print(f"recorded {gate} attestation for {record['reviewer']} at {path}")
    print(f"  commit_reviewed: {record['commit_reviewed']}")
    print(f"  attested_digest: {record['attested_digest']}")
    return 0


def _gate_report(gate: str) -> dict | None:
    """The gate's generated report, if it exists. Used to bind the attestation to what was read.

    Searched for by filename under both report locations rather than by a hardcoded work-item
    directory, because G1's report is written under its work item's evidence directory and G0's under
    evidence/gates. Hardcoding either would mean the digest silently covered nothing for the other.
    """
    name = f"{gate.upper()}-gate-report.json"
    roots = (
        ROOT / "evidence" / "gates",
        ROOT / ".kilo" / "ecc" / "project-brain" / "evidence",
    )
    for root in roots:
        if not root.is_dir():
            continue
        for candidate in sorted(root.rglob(name)):
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return None
    return None


if __name__ == "__main__":
    raise SystemExit(main())
