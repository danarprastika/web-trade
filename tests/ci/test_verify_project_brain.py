"""Tests for the Project Brain integrity gate.

The Project Brain is the record of what this project has actually verified. If its gate can
silently pass, every status claim in the repository becomes unbacked, and the failure is
invisible precisely because the ledger looks healthy. These tests build a synthetic brain in
tmp_path, mutate exactly one thing per case, and assert the gate notices.

The cases below are the ones that matter most, because each represents a way the ledger
could come to overstate itself:

  - a COMPLETED item citing no evidence
  - an IN_PROGRESS item that is quietly blocked and does not say so
  - a COMPLETED item whose dependency is not complete, with no stated reason
  - evidence marked VERIFIED_WITH_EXCEPTION with no explanation of the exception
  - an evidence status outside the defined vocabulary

Run:
    python -m pytest tests/ci -q
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_gate():
    spec = importlib.util.spec_from_file_location(
        "verify_project_brain", REPO_ROOT / "scripts" / "verify_project_brain.py"
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        pytest.skip("verify_project_brain.py could not be located")
    module = importlib.util.module_from_spec(spec)
    sys.modules["verify_project_brain"] = module
    spec.loader.exec_module(module)
    return module


gate = _load_gate()


def write_brain(root: Path, items: list[dict], evidence: list[dict]) -> Path:
    """Create a Project Brain under root and return its path."""
    brain = root / "project-brain"
    brain.mkdir(parents=True, exist_ok=True)
    (brain / "work-items.json").write_text(
        json.dumps({"items": items}, indent=2), encoding="utf-8"
    )
    (brain / "evidence.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in evidence), encoding="utf-8"
    )
    return brain


def item(item_id: str, status: str, **extra) -> dict:
    base = {
        "id": item_id,
        "title": f"Item {item_id}",
        "status": status,
        "acceptance_criteria": ["does the thing"],
        "dependencies": [],
    }
    base.update(extra)
    return base


def evidence(evidence_id: str, status: str = "VERIFIED", **extra) -> dict:
    base = {
        "evidence_id": evidence_id,
        "work_item": "WI-001",
        "claim": "something was checked",
        "status": status,
        "method": "ran it",
        "result": "it worked",
    }
    base.update(extra)
    return base


# --- Happy path --------------------------------------------------------------


def test_minimal_valid_brain_passes(tmp_path: Path) -> None:
    brain = write_brain(
        tmp_path,
        [item("WI-001", "COMPLETED", evidence_ref=["EV-001"])],
        [evidence("EV-001")],
    )
    assert gate.check(brain) == []


def test_pending_items_need_no_evidence_or_explanation(tmp_path: Path) -> None:
    """A PENDING item is unfinished, so requiring evidence or a blocker would be noise."""
    brain = write_brain(tmp_path, [item("WI-001", "PENDING")], [])
    assert gate.check(brain) == []


# --- The overstatement cases ------------------------------------------------


def test_completed_item_without_evidence_is_rejected(tmp_path: Path) -> None:
    """A completion with no recorded evidence is a claim, not a verification."""
    brain = write_brain(tmp_path, [item("WI-001", "COMPLETED")], [evidence("EV-001")])
    problems = gate.check(brain)
    assert any("COMPLETED without evidence_ref" in p for p in problems), problems


def test_completed_item_citing_unknown_evidence_is_rejected(tmp_path: Path) -> None:
    brain = write_brain(
        tmp_path,
        [item("WI-001", "COMPLETED", evidence_ref=["EV-999"])],
        [evidence("EV-001")],
    )
    problems = gate.check(brain)
    assert any("cites unknown evidence EV-999" in p for p in problems), problems


def test_in_progress_item_that_is_blocked_must_say_so(tmp_path: Path) -> None:
    """An IN_PROGRESS item with neither a blocker nor partial results cannot be resumed,
    because nothing records what is actually outstanding."""
    brain = write_brain(
        tmp_path,
        [item("WI-001", "IN_PROGRESS")],
        [evidence("EV-001", status="PARTIALLY_VERIFIED", caveats="the rest is pending")],
    )
    problems = gate.check(brain)
    assert any("neither blocker nor partial_results" in p for p in problems), problems


def test_in_progress_item_with_a_blocker_passes(tmp_path: Path) -> None:
    brain = write_brain(
        tmp_path,
        [item("WI-001", "IN_PROGRESS", blocker="waiting on the Docker daemon")],
        [evidence("EV-001", status="PARTIALLY_VERIFIED", caveats="the rest is pending")],
    )
    assert gate.check(brain) == []


# --- Dependency ordering -----------------------------------------------------


def test_completed_item_with_incomplete_dependency_is_rejected(tmp_path: Path) -> None:
    """Finishing ahead of a dependency is either out-of-order work or a contradicted
    completion, and neither should pass without an explicit stated reason."""
    brain = write_brain(
        tmp_path,
        [
            item("WI-001", "COMPLETED", dependencies=["WI-002"], evidence_ref=["EV-001"]),
            item("WI-002", "IN_PROGRESS", blocker="waiting"),
        ],
        [evidence("EV-001")],
    )
    problems = gate.check(brain)
    assert any("COMPLETED while dependency WI-002" in p for p in problems), problems
    assert any("dependency_exemptions" in p for p in problems), problems


def test_completed_item_with_exemption_passes(tmp_path: Path) -> None:
    """An explicit, reasoned exemption is the legitimate way to finish ahead of a
    dependency, for example when the dependency is gated on a human attestation no
    automated run can satisfy."""
    brain = write_brain(
        tmp_path,
        [
            item(
                "WI-001",
                "COMPLETED",
                dependencies=["WI-002"],
                evidence_ref=["EV-001"],
                dependency_exemptions={
                    "WI-002": "WI-002 needs a human reviewer; it is not a prerequisite "
                    "for this work, and it is not being claimed as passed."
                },
            ),
            item("WI-002", "IN_PROGRESS", blocker="awaiting a named human reviewer"),
        ],
        [evidence("EV-001")],
    )
    assert gate.check(brain) == []


def test_empty_exemption_is_rejected(tmp_path: Path) -> None:
    """An exemption with no reason is the same as no exemption, written in a form the
    check would otherwise accept."""
    brain = write_brain(
        tmp_path,
        [
            item(
                "WI-001",
                "COMPLETED",
                dependencies=["WI-002"],
                evidence_ref=["EV-001"],
                dependency_exemptions={"WI-002": "   "},
            ),
            item("WI-002", "PENDING"),
        ],
        [evidence("EV-001")],
    )
    problems = gate.check(brain)
    assert any("empty dependency_exemptions" in p for p in problems), problems


def test_exemption_does_not_suppress_other_dependency_problems(tmp_path: Path) -> None:
    """An exemption for one dependency must not excuse a second, unrelated one."""
    brain = write_brain(
        tmp_path,
        [
            item(
                "WI-001",
                "COMPLETED",
                dependencies=["WI-002", "WI-003"],
                evidence_ref=["EV-001"],
                dependency_exemptions={"WI-002": "a genuine, stated reason"},
            ),
            item("WI-002", "PENDING"),
            item("WI-003", "PENDING"),
        ],
        [evidence("EV-001")],
    )
    problems = gate.check(brain)
    assert any("dependency WI-003" in p for p in problems), problems
    assert not any("dependency WI-002" in p for p in problems), problems


# --- Evidence vocabulary -----------------------------------------------------


@pytest.mark.parametrize(
    "status",
    ["VERIFIED_WITH_EXCEPTION", "PARTIALLY_VERIFIED", "UNRESOLVED_EXCEPTION"],
)
def test_partial_evidence_without_explanation_is_rejected(
    tmp_path: Path, status: str
) -> None:
    """These statuses all mean "verified except for something". If the something is not
    written down, they read as plain VERIFIED to anyone scanning the ledger."""
    brain = write_brain(
        tmp_path,
        [item("WI-001", "COMPLETED", evidence_ref=["EV-001"])],
        [evidence("EV-001", status=status)],
    )
    problems = gate.check(brain)
    assert any("no `caveats` or `exception`" in p for p in problems), problems


def test_partial_evidence_with_caveats_passes(tmp_path: Path) -> None:
    brain = write_brain(
        tmp_path,
        [item("WI-001", "COMPLETED", evidence_ref=["EV-001"])],
        [
            evidence(
                "EV-001",
                status="VERIFIED_WITH_EXCEPTION",
                caveats="the go.sum conjunct is unmet because there are no dependencies",
            )
        ],
    )
    assert gate.check(brain) == []


def test_resolved_evidence_without_defect_description_is_rejected(tmp_path: Path) -> None:
    """RESOLVED claims a defect was found and fixed. Without the defect it is
    indistinguishable from a plain VERIFIED record."""
    brain = write_brain(
        tmp_path,
        [item("WI-001", "COMPLETED", evidence_ref=["EV-001"])],
        [evidence("EV-001", status="RESOLVED")],
    )
    problems = gate.check(brain)
    assert any("defect_found_and_fixed" in p for p in problems), problems


def test_unknown_evidence_status_is_rejected(tmp_path: Path) -> None:
    brain = write_brain(
        tmp_path,
        [item("WI-001", "COMPLETED", evidence_ref=["EV-001"])],
        [evidence("EV-001", status="PROBABLY_FINE")],
    )
    problems = gate.check(brain)
    assert any("unknown status 'PROBABLY_FINE'" in p for p in problems), problems


def test_unknown_work_item_status_is_rejected(tmp_path: Path) -> None:
    brain = write_brain(
        tmp_path, [item("WI-001", "MOSTLY_DONE")], [evidence("EV-001")]
    )
    problems = gate.check(brain)
    assert any("unknown status 'MOSTLY_DONE'" in p for p in problems), problems


# --- Structural --------------------------------------------------------------


def test_missing_dependency_is_rejected(tmp_path: Path) -> None:
    brain = write_brain(
        tmp_path,
        [item("WI-001", "PENDING", dependencies=["WI-404"])],
        [evidence("EV-001")],
    )
    problems = gate.check(brain)
    assert any("depends on unknown item WI-404" in p for p in problems), problems


def test_duplicate_item_ids_are_rejected(tmp_path: Path) -> None:
    brain = write_brain(
        tmp_path,
        [item("WI-001", "PENDING"), item("WI-001", "PENDING")],
        [evidence("EV-001")],
    )
    problems = gate.check(brain)
    assert any("duplicate work-item ids" in p for p in problems), problems


def test_absent_brain_is_reported_not_silently_passed(tmp_path: Path) -> None:
    """A missing ledger must not read as an empty, valid one."""
    missing = tmp_path / "nowhere"
    problems = gate.check(missing)
    assert problems, "an absent project brain must be reported"


# --- The repository's own brain ---------------------------------------------


def test_repository_brain_passes() -> None:
    """The real Project Brain must satisfy every check the gate enforces."""
    assert gate.check(gate.BRAIN) == []
