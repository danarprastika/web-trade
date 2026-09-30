"""Tests for the G0 specification integrity gate.

An integrity gate that cannot be shown to fail is decoration. These tests build synthetic
specification packages in tmp_path, mutate exactly one thing per case, and assert the
gate's verdict. The mutation is always the *real* attack: a document that still exists and
still reads correctly, but whose bytes no longer match the manifest.

Run:
    python -m pytest tests/ci -q
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_gate():
    spec = importlib.util.spec_from_file_location(
        "verify_spec_gate", REPO_ROOT / "scripts" / "verify_spec_gate.py"
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        pytest.skip("verify_spec_gate.py could not be located")
    module = importlib.util.module_from_spec(spec)
    sys.modules["verify_spec_gate"] = module
    spec.loader.exec_module(module)
    return module


gate = _load_gate()

DECISION_REGISTER = """\
# Decision Register

| ID | Decision | Status |
|---|---|---|
| ADR-001 | Go is the authoritative backend | Accepted |
| ADR-002 | TypeScript is the operator frontend | Accepted |

No architectural decision remains open in this final blueprint.

## Additional binding decisions

| ADR | Decision | Rationale / boundary |
|---|---|---|
| ADR-016 | Indonesia is the initial review target | Location never proves residence or eligibility. |
| ADR-017 | Keycloak is the reference identity broker | SAML is accepted only at the federation boundary. |
"""

# Two documents with distinct content, so the duplicate-detection check is not trivially
# triggered by two identical fixtures.
DOC_A = "# Alpha\n\nAuthoritative content for the alpha document.\n"
DOC_B = "# Beta\n\nAuthoritative content for the beta document, distinct from alpha.\n"


def build_package(root: Path, *, decisions: str = DECISION_REGISTER) -> Path:
    """Create a valid two-document specification package under root/docs."""
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)

    entries = []
    for name, body in (("00_ALPHA.md", DOC_A), ("12_DECISION_REGISTER.md", decisions)):
        raw = body.encode("utf-8")
        (docs / name).write_bytes(raw)
        entries.append(
            {
                "path": name,
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )

    manifest = {
        "package": "TEST_PACKAGE",
        "status": "FINAL",
        "document_count": len(entries),
        "documents": entries,
    }
    (docs / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return docs


def run(docs: Path) -> int:
    return gate.main(["--docs-root", str(docs), "--json-only"])


def criteria_by_id(docs: Path) -> dict[str, gate.Criterion]:
    """Run every check and index the results, for asserting on a single criterion."""
    pkg = gate.DocsPackage(docs, repo_root=docs.parent)
    manifest = pkg.load_manifest()
    results = [
        gate.check_documents_exist(pkg, manifest),
        *gate.check_digests(pkg, manifest),
        gate.check_no_unlisted(pkg, manifest),
        gate.check_legacy(pkg, manifest),
        gate.check_duplicate_bytes(pkg, manifest),
        gate.check_decisions(pkg),
    ]
    return {c.criterion_id: c for c in results}


# --- Happy path -------------------------------------------------------------


def test_valid_package_passes_mechanical_checks(tmp_path: Path) -> None:
    docs = build_package(tmp_path)
    results = criteria_by_id(docs)
    for cid, criterion in results.items():
        assert criterion.result == "PASS", f"{cid} unexpectedly failed: {criterion.detail}"


def test_valid_package_is_not_reported_as_passed(tmp_path: Path) -> None:
    """All mechanical checks green must still NOT yield PASS, because docs/11 requires
    a human reviewer and this script cannot supply one."""
    docs = build_package(tmp_path)
    assert run(docs) == 1  # non-zero: human attestation outstanding


def test_verdict_is_pending_human_attestation_not_pass(tmp_path: Path) -> None:
    docs = build_package(tmp_path)
    report = gate.GateReport(gate="G0")
    pkg = gate.DocsPackage(docs, repo_root=docs.parent)
    manifest = pkg.load_manifest()
    for criterion in [
        gate.check_documents_exist(pkg, manifest),
        *gate.check_digests(pkg, manifest),
        gate.check_no_unlisted(pkg, manifest),
        gate.check_legacy(pkg, manifest),
        gate.check_duplicate_bytes(pkg, manifest),
        gate.check_decisions(pkg),
        gate.check_human_attestation(),
    ]:
        report.add(criterion)
    assert report.verdict == "PENDING_HUMAN_ATTESTATION"
    assert not report.failures
    assert len(report.pending_human) == 1


# --- Tamper detection -------------------------------------------------------


def test_single_byte_tamper_is_caught(tmp_path: Path) -> None:
    """The core case: the file still exists and still reads as a valid document, but its
    bytes no longer match the manifest."""
    docs = build_package(tmp_path)
    target = docs / "00_ALPHA.md"
    target.write_text(DOC_A.replace("alpha", "gamma"), encoding="utf-8")
    results = criteria_by_id(docs)
    assert results["G0.3"].result == "FAIL"


def test_equivalent_rewrite_is_caught(tmp_path: Path) -> None:
    """A rewrite that preserves meaning and length but not bytes must still fail.

    This is the case a reviewer would wave through by reading the document, which is
    precisely why the gate hashes rather than reviews.
    """
    docs = build_package(tmp_path)
    target = docs / "00_ALPHA.md"
    raw = DOC_A.encode("utf-8")
    # Same byte length, different bytes: swap two characters in the body.
    altered = raw.replace(b"alpha document", b"gamma document", 1)
    assert len(altered) == len(raw)
    target.write_bytes(altered)
    results = criteria_by_id(docs)
    assert results["G0.2"].result == "PASS", "byte length is unchanged, as intended"
    assert results["G0.3"].result == "FAIL", "digest must still catch the change"


def test_appended_document_is_caught(tmp_path: Path) -> None:
    docs = build_package(tmp_path)
    (docs / "99_EXTRA.md").write_text("# Extra\n", encoding="utf-8")
    assert criteria_by_id(docs)["G0.4"].result == "FAIL"


def test_deleted_document_is_caught(tmp_path: Path) -> None:
    docs = build_package(tmp_path)
    (docs / "00_ALPHA.md").unlink()
    results = criteria_by_id(docs)
    assert results["G0.1"].result == "FAIL"
    assert results["G0.3"].result == "FAIL"


def test_manifest_count_mismatch_is_caught(tmp_path: Path) -> None:
    docs = build_package(tmp_path)
    manifest = json.loads((docs / "MANIFEST.json").read_text(encoding="utf-8"))
    manifest["document_count"] = 99
    (docs / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    assert criteria_by_id(docs)["G0.1"].result == "FAIL"


# --- Legacy and duplicate detection -----------------------------------------


@pytest.mark.parametrize(
    "filename",
    [
        "00_DRAFT.md",
        "00_SUPERSEDED.md",
        "00_ARCHIVE.md",
        "00_OLD.md",
        "00_README.md.orig",
        "00_README.md~",
        "00_COPY.md",
    ],
)
def test_legacy_filename_markers_are_caught(tmp_path: Path, filename: str) -> None:
    docs = build_package(tmp_path)
    (docs / filename).write_text("stale\n", encoding="utf-8")
    # The file is unlisted *and* legacy-named; assert the legacy criterion specifically
    # fires, since that is the control being exercised.
    assert criteria_by_id(docs)["G0.5"].result == "FAIL"


def test_versioned_directory_is_caught(tmp_path: Path) -> None:
    docs = build_package(tmp_path)
    (docs / "v1").mkdir()
    (docs / "v1" / "00_ALPHA.md").write_text(DOC_A, encoding="utf-8")
    assert criteria_by_id(docs)["G0.5"].result == "FAIL"


def test_duplicate_document_bytes_are_caught(tmp_path: Path) -> None:
    """Two listed documents with identical content would be a duplicate authority."""
    docs = build_package(tmp_path)
    # Add a third listed document whose content duplicates the first.
    raw = DOC_A.encode("utf-8")
    (docs / "13_DUPLICATE.md").write_bytes(raw)
    manifest = json.loads((docs / "MANIFEST.json").read_text(encoding="utf-8"))
    manifest["documents"].append(
        {"path": "13_DUPLICATE.md", "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    )
    manifest["document_count"] = len(manifest["documents"])
    (docs / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    assert criteria_by_id(docs)["G0.6"].result == "FAIL"


# --- Decision register parsing ---------------------------------------------


def test_open_decision_is_caught(tmp_path: Path) -> None:
    open_register = DECISION_REGISTER.replace(
        "| ADR-002 | TypeScript is the operator frontend | Accepted |",
        "| ADR-002 | TypeScript is the operator frontend | Open |",
    )
    docs = build_package(tmp_path, decisions=open_register)
    assert criteria_by_id(docs)["G0.7"].result == "FAIL"


def test_proposed_decision_is_caught(tmp_path: Path) -> None:
    open_register = DECISION_REGISTER.replace("| Accepted |", "| Proposed |", 1)
    docs = build_package(tmp_path, decisions=open_register)
    assert criteria_by_id(docs)["G0.7"].result == "FAIL"


def test_rationale_prose_is_not_mistaken_for_an_open_decision(tmp_path: Path) -> None:
    """Regression guard for a real bug.

    The register holds two three-column tables: `| ID | Decision | Status |` and
    `| ADR | Decision | Rationale / boundary |`. A naive row parser reads the second
    table's prose as a status and reports ten fabricated open decisions, which would fail
    a perfectly valid package and train reviewers to ignore the gate.
    """
    docs = build_package(tmp_path)
    criterion = criteria_by_id(docs)["G0.7"]
    assert criterion.result == "PASS", criterion.detail
    assert "2 status-bearing ADRs" in criterion.detail
    assert "2 additional binding ADRs" in criterion.detail


def test_missing_decision_register_is_caught(tmp_path: Path) -> None:
    docs = build_package(tmp_path)
    (docs / "12_DECISION_REGISTER.md").unlink()
    # Also drop it from the manifest so the failure is attributable to G0.7.
    manifest = json.loads((docs / "MANIFEST.json").read_text(encoding="utf-8"))
    manifest["documents"] = [d for d in manifest["documents"] if d["path"] != "12_DECISION_REGISTER.md"]
    manifest["document_count"] = len(manifest["documents"])
    (docs / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    assert criteria_by_id(docs)["G0.7"].result == "FAIL"


# --- Real package -----------------------------------------------------------


def test_real_package_mechanical_checks_pass() -> None:
    """The gate must be green against the repository it actually guards."""
    pkg = gate.DocsPackage(REPO_ROOT / "docs", repo_root=REPO_ROOT)
    manifest = pkg.load_manifest()
    results = {
        c.criterion_id: c
        for c in [
            gate.check_documents_exist(pkg, manifest),
            *gate.check_digests(pkg, manifest),
            gate.check_no_unlisted(pkg, manifest),
            gate.check_legacy(pkg, manifest),
            gate.check_duplicate_bytes(pkg, manifest),
            gate.check_decisions(pkg),
        ]
    }
    failures = {cid: c.detail for cid, c in results.items() if c.result != "PASS"}
    assert not failures, f"real specification package failed: {failures}"
