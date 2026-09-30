#!/usr/bin/env python3
"""G0 — Specification Integrity gate.

Authority: docs/11_EXECUTION_GATES.md, G0:

    "all documents listed in the manifest exist; every SHA-256 digest matches the exact
    packaged bytes; no unlisted document or legacy version is present; no duplicate
    authority or unresolved architecture choice remains; and the gate report records
    reviewer, commit, timestamp, command output, and pass/fail result. A mismatch is an
    automatic failure."

docs/11 also states that "A gate is PASS only when every listed criterion is satisfied;
partial completion is FAIL, not a percentage", and that "No gate may be marked passed by
documentation alone when runtime evidence is required."

G0 is explicitly package integrity only, so this script touches nothing outside docs/.

Two honesty properties this script is written to preserve:

  * Criteria that genuinely require a human are reported as REQUIRES_HUMAN_ATTESTATION
    rather than being quietly passed. A machine cannot review a document for duplicated
    *authority*; it can only detect duplicated *bytes* and structural legacy markers.
    Those are reported as what they are.

  * A digest mismatch is an automatic failure and is never downgraded to a warning or a
    count. The script exits non-zero on any failure and on any criterion left
    unattested, so a partial run cannot be recorded as a pass.

Usage:
    python scripts/verify_spec_gate.py
    python scripts/verify_spec_gate.py --json-only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS = REPO_ROOT / "docs"
MANIFEST = DOCS / "MANIFEST.json"
DECISION_REGISTER = DOCS / "12_DECISION_REGISTER.md"
OUT_DIR = REPO_ROOT / "evidence" / "gates"

# Structural markers of a superseded or legacy specification package. docs/00 states that
# "Earlier version folders, draft documents, superseded concepts, historical archives, and
# duplicate specifications are intentionally excluded", so any of these appearing is a G0
# failure even if every listed digest still matches.
LEGACY_NAME_PATTERNS = (
    re.compile(r"(^|[._-])draft([._-]|$)", re.IGNORECASE),
    re.compile(r"(^|[._-])superseded([._-]|$)", re.IGNORECASE),
    re.compile(r"(^|[._-])obsolete([._-]|$)", re.IGNORECASE),
    re.compile(r"(^|[._-])deprecated([._-]|$)", re.IGNORECASE),
    re.compile(r"(^|[._-])archive(d)?([._-]|$)", re.IGNORECASE),
    re.compile(r"(^|[._-])backup([._-]|$)", re.IGNORECASE),
    re.compile(r"(^|[._-])old([._-]|$)", re.IGNORECASE),
    re.compile(r"(^|[._-])copy([._-]|$)", re.IGNORECASE),
    re.compile(r"\.(orig|rej|bak)$", re.IGNORECASE),
    re.compile(r"[~$]"),
)

# `v1`, `v2`, ... directory segments inside docs/ indicate a versioned package layout.
LEGACY_DIR_PATTERN = re.compile(r"^v\d+$", re.IGNORECASE)


@dataclass
class Criterion:
    """One G0 pass criterion and its outcome.

    `mechanically_verified` distinguishes a result a machine can stand behind from one
    that only a reviewer can. Reporting a human judgement as machine-verified would be
    the exact failure mode the gate is supposed to prevent.
    """

    criterion_id: str
    description: str
    result: str  # PASS | FAIL | REQUIRES_HUMAN_ATTESTATION
    detail: str
    mechanically_verified: bool

    @property
    def satisfied(self) -> bool:
        return self.result == "PASS"


@dataclass
class GateReport:
    gate: str
    criteria: list[Criterion] = field(default_factory=list)

    def add(self, criterion: Criterion) -> None:
        self.criteria.append(criterion)

    @property
    def failures(self) -> list[Criterion]:
        return [c for c in self.criteria if c.result == "FAIL"]

    @property
    def pending_human(self) -> list[Criterion]:
        return [c for c in self.criteria if c.result == "REQUIRES_HUMAN_ATTESTATION"]

    @property
    def verdict(self) -> str:
        # docs/11: partial completion is FAIL, not a percentage.
        if self.failures:
            return "FAIL"
        if self.pending_human:
            return "PENDING_HUMAN_ATTESTATION"
        return "PASS"


class DocsPackage:
    """A specification package rooted at a docs directory.

    Introduced so the gate can be exercised against synthetic packages in tests. A gate
    that can only ever run against the real docs/ cannot be proven to fail, and an
    integrity gate that cannot fail is decoration.

    `repo_root` is the tree scanned for legacy markers. It defaults to the docs
    directory's parent, because `docs/` sits directly in the repository root. (An
    earlier version walked one level higher and scanned the entire parent of the
    repository, which is both wrong and ruinously slow.)
    """

    def __init__(self, docs: Path, repo_root: Path | None = None) -> None:
        self.docs = docs
        self.repo_root = repo_root or docs.parent
        self.manifest = docs / "MANIFEST.json"
        self.decision_register = docs / "12_DECISION_REGISTER.md"
        self.out_dir = self.repo_root / "evidence" / "gates"

    def load_manifest(self) -> dict:
        return json.loads(self.manifest.read_text(encoding="utf-8"))


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        # Streamed so the check works for a package of any size and never holds a whole
        # document in memory.
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit() -> str:
    """Record the commit the gate ran against.

    Recorded even when the tree is dirty, because the gate is about the working tree's
    docs/. A dirty tree is reported separately rather than silently implying a clean
    revision.
    """
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return f"UNAVAILABLE ({exc})"


def git_dirty() -> bool:
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "--", "docs"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        return bool(out.stdout.strip())
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return False


def check_documents_exist(pkg: "DocsPackage", manifest: dict) -> Criterion:
    missing = [d["path"] for d in manifest["documents"] if not (pkg.docs / d["path"]).is_file()]
    if missing:
        return Criterion(
            "G0.1",
            "All documents listed in the manifest exist",
            "FAIL",
            f"missing: {missing}",
            True,
        )
    count = len(manifest["documents"])
    declared = manifest.get("document_count")
    if declared != count:
        return Criterion(
            "G0.1",
            "All documents listed in the manifest exist",
            "FAIL",
            f"manifest declares document_count={declared} but lists {count} documents",
            True,
        )
    return Criterion(
        "G0.1",
        "All documents listed in the manifest exist",
        "PASS",
        f"all {count} listed documents are present and document_count agrees",
        True,
    )


def check_digests(pkg: "DocsPackage", manifest: dict) -> list[Criterion]:
    """Byte length and SHA-256, reported as two criteria.

    Both are checked because a truncated or mutated document is exactly the failure this
    gate exists to catch, and reporting only one dimension would hide a partial tamper.
    """
    byte_failures: list[str] = []
    digest_failures: list[str] = []
    verified = 0

    for entry in manifest["documents"]:
        path = pkg.docs / entry["path"]
        if not path.is_file():
            byte_failures.append(f"{entry['path']}: missing")
            digest_failures.append(f"{entry['path']}: missing")
            continue

        actual_bytes = path.stat().st_size
        if actual_bytes != entry["bytes"]:
            byte_failures.append(
                f"{entry['path']}: manifest says {entry['bytes']} bytes, file is {actual_bytes}"
            )

        actual_digest = sha256_of(path)
        if actual_digest != entry["sha256"]:
            digest_failures.append(
                f"{entry['path']}: manifest {entry['sha256'][:16]}…, file {actual_digest[:16]}…"
            )
        else:
            verified += 1

    total = len(manifest["documents"])
    return [
        Criterion(
            "G0.2",
            "Every document matches its declared byte length",
            "FAIL" if byte_failures else "PASS",
            "; ".join(byte_failures) if byte_failures else f"{total}/{total} byte lengths match",
            True,
        ),
        Criterion(
            "G0.3",
            "Every SHA-256 digest matches the exact packaged bytes",
            "FAIL" if digest_failures else "PASS",
            "; ".join(digest_failures)
            if digest_failures
            else f"{verified}/{total} digests match",
            True,
        ),
    ]


def check_no_unlisted(pkg: "DocsPackage", manifest: dict) -> Criterion:
    listed = {d["path"] for d in manifest["documents"]}
    listed.add(pkg.manifest.name)
    present = {
        str(p.relative_to(pkg.docs)).replace("\\", "/")
        for p in pkg.docs.rglob("*")
        if p.is_file()
    }
    unlisted = sorted(present - listed)
    if unlisted:
        return Criterion(
            "G0.4",
            "No unlisted document is present in docs/",
            "FAIL",
            f"unlisted: {unlisted}",
            True,
        )
    return Criterion(
        "G0.4",
        "No unlisted document is present in docs/",
        "PASS",
        f"docs/ contains exactly the {len(listed)} manifest-listed files and nothing else",
        True,
    )


def check_legacy(pkg: "DocsPackage", manifest: dict) -> Criterion:
    """Legacy markers anywhere in the repository, not just docs/.

    A superseded copy left in another directory is still a competing authority even
    though docs/ itself is pristine, so the whole tree is scanned for filename markers.
    Directories that would trip this are skipped explicitly.
    """
    findings: list[str] = []
    skip_dirs = {".git", "node_modules", ".next", "__pycache__", ".venv", "vendor"}

    for path in pkg.repo_root.rglob("*"):
        if any(part in skip_dirs for part in path.parts):
            continue
        if path.is_dir():
            if LEGACY_DIR_PATTERN.match(path.name):
                findings.append(f"versioned directory: {path.relative_to(pkg.repo_root)}")
            continue
        name = path.name
        if name == pkg.manifest.name and path.parent == pkg.docs:
            continue
        for pattern in LEGACY_NAME_PATTERNS:
            if pattern.search(name):
                findings.append(f"legacy-named file: {path.relative_to(pkg.repo_root)}")
                break

    if findings:
        return Criterion(
            "G0.5",
            "No unlisted document or legacy version is present",
            "FAIL",
            "; ".join(sorted(set(findings))[:10]),
            True,
        )
    return Criterion(
        "G0.5",
        "No unlisted document or legacy version is present",
        "PASS",
        "no draft/superseded/archived/versioned-path markers found in the repository",
        True,
    )


def check_duplicate_bytes(pkg: "DocsPackage", manifest: dict) -> Criterion:
    """Two listed documents with identical content would be a duplicate authority.

    This is the machine-checkable half of "no duplicate authority". It detects identical
    *bytes*; two documents can also be duplicates in substance while differing in
    wording, which no byte comparison can catch. That residue is the human criterion.
    """
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    for entry in manifest["documents"]:
        path = pkg.docs / entry["path"]
        if not path.is_file():
            continue
        digest = entry["sha256"]
        if digest in seen:
            duplicates.append(f"{seen[digest]} and {entry['path']} share sha256 {digest[:16]}…")
        else:
            seen[digest] = entry["path"]

    if duplicates:
        return Criterion(
            "G0.6",
            "No two documents are byte-identical (mechanical duplicate detection)",
            "FAIL",
            "; ".join(duplicates),
            True,
        )
    return Criterion(
        "G0.6",
        "No two documents are byte-identical (mechanical duplicate detection)",
        "PASS",
        f"all {len(seen)} document digests are distinct",
        True,
    )


def check_decisions(pkg: "DocsPackage") -> Criterion:
    """No architectural decision may remain open.

    docs/12 states "No architectural decision remains open in this final blueprint", so
    this is verifiable by parsing the register rather than by judgement.

    The register holds two tables with the same column count but different meanings, and
    treating them identically is a real trap:

      | ID   | Decision | Status                 |   <- third column is a status
      | ADR  | Decision | Rationale / boundary  |   <- third column is prose

    Both match a naive row regex. Reading the addendum's prose as a status reports ten
    fabricated "open decisions", so the header of each table is consulted to decide what
    its third column means.
    """
    if not pkg.decision_register.is_file():
        return Criterion(
            "G0.7",
            "No unresolved architecture choice remains",
            "FAIL",
            f"{pkg.decision_register.name} is missing, so decision status cannot be established",
            True,
        )

    text = pkg.decision_register.read_text(encoding="utf-8")
    lines = text.splitlines()

    third_column_meaning: str | None = None
    status_checked: list[str] = []
    binding_rows: list[str] = []
    non_accepted: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            # A non-table line ends the current table.
            third_column_meaning = None
            continue

        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) != 3:
            third_column_meaning = None
            continue

        # Header row: the second cell names the table's purpose.
        if re.fullmatch(r"(id|adr)", cells[0], re.IGNORECASE) and not cells[0].lower().startswith("adr-"):
            third_column_meaning = "status" if "status" in cells[2].lower() else "rationale"
            continue

        # Separator row (|---|---|---|).
        if re.fullmatch(r":?-{2,}:?", cells[0]):
            continue

        adr, third = cells[0], cells[2]
        if not re.match(r"^ADR-\d+$", adr, re.IGNORECASE):
            continue

        if third_column_meaning == "status":
            status_checked.append(adr)
            if third.lower() != "accepted":
                non_accepted.append(f"{adr} status={third!r}")
        else:
            # A row in the binding-addendum table. These carry no status column, so their
            # acceptance is implied by inclusion in a document marked FINAL. Recorded for
            # the report so the count is visible rather than silently discarded.
            binding_rows.append(adr)
            if not third:
                non_accepted.append(f"{adr} has an empty rationale/boundary cell")

    if not status_checked:
        return Criterion(
            "G0.7",
            "No unresolved architecture choice remains",
            "FAIL",
            "no ADR status rows could be identified in the decision register",
            True,
        )

    if non_accepted:
        return Criterion(
            "G0.7",
            "No unresolved architecture choice remains",
            "FAIL",
            f"non-accepted decision rows: {non_accepted}",
            True,
        )

    return Criterion(
        "G0.7",
        "No unresolved architecture choice remains",
        "PASS",
        f"all {len(status_checked)} status-bearing ADRs are Accepted; "
        f"{len(binding_rows)} additional binding ADRs ({binding_rows[0]}–{binding_rows[-1]}) "
        f"carry a rationale and are implicit-accepted by inclusion in a FINAL package",
        True,
    )


def check_human_attestation() -> Criterion:
    """The part of G0 a machine cannot decide, stated rather than assumed.

    docs/11 requires the gate report to record a *reviewer*. This script is that
    evidence's producer, not its reviewer. Recording an automated run as a human
    attestation would defeat the control, so the criterion is reported as outstanding
    rather than satisfied.
    """
    return Criterion(
        "G0.8",
        "Named human reviewer attests the specification package",
        "REQUIRES_HUMAN_ATTESTATION",
        "Digest, inventory, legacy-marker and decision-status checks are mechanical and "
        "have run. Semantic duplicate authority and overall reviewer sign-off are human "
        "judgements and are NOT asserted by this script.",
        False,
    )


def render_markdown(report: GateReport, manifest: dict, commit: str, dirty: bool, ran_at: str) -> str:
    lines = [
        f"# Gate report — {report.gate}",
        "",
        "Authority: `docs/11_EXECUTION_GATES.md`. Generated by `scripts/verify_spec_gate.py`.",
        "Re-running the script overwrites this file; it is a derived artifact, not an input.",
        "",
        "## Provenance",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Gate | {report.gate} |",
        f"| Specification package | `{manifest.get('package')}` |",
        f"| Manifest status | {manifest.get('status')} |",
        f"| Commit | `{commit}` |",
        f"| docs/ working tree | {'DIRTY' if dirty else 'clean'} |",
        f"| Executed at (UTC) | {ran_at} |",
        "| Automated executor | `team-lead` via `scripts/verify_spec_gate.py` |",
        "| Human reviewer | **NOT YET ASSIGNED** |",
        "",
        "## Criteria",
        "",
        "| ID | Criterion | Result | Mechanically verified |",
        "|---|---|---|---|",
    ]
    for c in report.criteria:
        lines.append(
            f"| {c.criterion_id} | {c.description} | **{c.result}** | {'yes' if c.mechanically_verified else 'no'} |"
        )

    lines += ["", "## Detail", ""]
    for c in report.criteria:
        lines += [f"### {c.criterion_id} — {c.description}", "", f"- **Result:** {c.result}", f"- {c.detail}", ""]

    lines += [
        "## Verdict",
        "",
        f"**{report.verdict}**",
        "",
    ]
    if report.failures:
        lines += [
            f"{len(report.failures)} criterion/criteria failed. Per docs/11, a mismatch is an",
            "automatic failure and partial completion is FAIL, not a percentage.",
            "",
        ]
        for c in report.failures:
            lines.append(f"- {c.criterion_id}: {c.detail}")
        lines.append("")

    if report.pending_human:
        lines += [
            f"{len(report.pending_human)} criterion/criteria cannot be machine-decided and remain",
            "outstanding. This gate report therefore does **not** claim G0 is passed.",
            "",
        ]
        for c in report.pending_human:
            lines.append(f"- {c.criterion_id}: {c.description}")
        lines.append("")

    lines += [
        "## Command output",
        "",
        "```",
        "$ python scripts/verify_spec_gate.py",
    ]
    for c in report.criteria:
        lines.append(f"[{c.result:28}] {c.criterion_id}  {c.description}")
    lines += [f"[{report.verdict:28}] VERDICT", "```", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json-only", action="store_true", help="suppress the human-readable report")
    parser.add_argument(
        "--docs-root",
        default=str(DOCS),
        help="specification package directory (default: ./docs). Overridden by tests to "
             "exercise the gate against synthetic packages.",
    )
    args = parser.parse_args(argv)

    pkg = DocsPackage(Path(args.docs_root).resolve())
    if not pkg.manifest.is_file():
        print(f"G0 FAILED: manifest not found at {pkg.manifest}", file=sys.stderr)
        return 1

    manifest = pkg.load_manifest()
    report = GateReport(gate="G0")

    report.add(check_documents_exist(pkg, manifest))
    for criterion in check_digests(pkg, manifest):
        report.add(criterion)
    report.add(check_no_unlisted(pkg, manifest))
    report.add(check_legacy(pkg, manifest))
    report.add(check_duplicate_bytes(pkg, manifest))
    report.add(check_decisions(pkg))
    report.add(check_human_attestation())

    commit = git_commit()
    dirty = git_dirty()
    ran_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if not args.json_only:
        for c in report.criteria:
            marker = "PASS" if c.result == "PASS" else c.result
            print(f"[{marker:28}] {c.criterion_id}  {c.description}")
        print(f"[{report.verdict:28}] VERDICT")

    pkg.out_dir.mkdir(parents=True, exist_ok=True)
    (pkg.out_dir / "G0-gate-report.md").write_text(
        render_markdown(report, manifest, commit, dirty, ran_at), encoding="utf-8"
    )
    (pkg.out_dir / "G0-gate-report.json").write_text(
        json.dumps(
            {
                "gate": report.gate,
                "verdict": report.verdict,
                "commit": commit,
                "docs_dirty": dirty,
                "executed_at": ran_at,
                "executed_by": "scripts/verify_spec_gate.py",
                "human_reviewer": None,
                "criteria": [
                    {
                        "id": c.criterion_id,
                        "description": c.description,
                        "result": c.result,
                        "mechanically_verified": c.mechanically_verified,
                        "detail": c.detail,
                    }
                    for c in report.criteria
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    if report.failures:
        print(f"\nG0 {report.verdict}: {len(report.failures)} mechanical failure(s).", file=sys.stderr)
        for c in report.failures:
            print(f"  {c.criterion_id}: {c.detail}", file=sys.stderr)
        return 1
    if report.pending_human:
        print(
            f"\nG0 {report.verdict}: mechanical checks passed, but human attestation is "
            f"outstanding. This gate report does not claim G0 is passed.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
