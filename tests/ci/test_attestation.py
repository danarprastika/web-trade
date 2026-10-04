"""Controls for scripts/attestation.py.

The property that matters is not that a name can be recorded. It is that an attestation stops being
honoured the moment it stops being true: when the report it covers changes, or when HEAD moves. A
mechanism that accepts a signature and keeps honouring it forever is worse than no mechanism, because
it looks like accountability while providing none.

These drive the real module against synthetic reports and commits, so each control states a condition
that must hold rather than a string that must appear.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

STATEMENT = (
    "I read the mechanical criteria output and the evidence digests for this gate, and I confirm "
    "the report describes the repository state it names."
)
REVIEWER = "Ada Lovelace"


def _module():
    path = REPO_ROOT / "scripts" / "attestation.py"
    if not path.is_file():
        pytest.skip("attestation.py not present")
    spec = importlib.util.spec_from_file_location("_attestation", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def att(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The real module, redirected at a temporary attestation directory and a synthetic HEAD."""
    module = _module()
    monkeypatch.setattr(module, "ATTESTATIONS", tmp_path / "attestations")
    monkeypatch.setattr(module, "head", lambda: "a" * 40)
    monkeypatch.setattr(
        module,
        "_gate_report",
        lambda gate: {"gate": gate, "criteria": [{"id": "G1.1", "status": "PASS"}]},
    )
    return module


def _record(att, gate: str = "G1", **overrides):
    record = {
        "schema": att.SCHEMA,
        "gate": gate,
        "reviewer": REVIEWER,
        "reviewer_role": "reviewer",
        "attested_at": "2026-10-04T12:00:00Z",
        "commit_reviewed": "a" * 40,
        "statement": STATEMENT,
        "attested_digest": None,
    }
    record.update(overrides)
    return record


REPORT = {"gate": "G1", "criteria": [{"id": "G1.1", "status": "PASS"}]}


def test_no_attestation_is_outstanding_rather_than_a_pass(att) -> None:
    """Absent is not the same as approved. This is the state every gate starts in."""
    status, _record_out, problems = att.evaluate("G1", REPORT)
    assert status == att.OUTSTANDING
    assert problems and "no attestation" in problems[0]


def test_a_valid_attestation_resolves(att) -> None:
    att._write("G1", _record(att, attested_digest=att.report_digest(REPORT)))
    status, record, problems = att.evaluate("G1", REPORT)
    assert status == att.RESOLVED, problems
    assert record["reviewer"] == REVIEWER


def test_an_attestation_goes_stale_when_the_report_changes(att) -> None:
    """The property the whole mechanism exists for.

    The reviewer signed a digest. If the report is then regenerated over a changed tree, the digest
    moves and the signature no longer covers it. Passing anyway would mean the review silently
    extended itself over work nobody read.
    """
    att._write("G1", _record(att, attested_digest=att.report_digest(REPORT)))
    changed = json.loads(json.dumps(REPORT))
    changed["criteria"][0]["status"] = "FAIL"
    status, _record_out, problems = att.evaluate("G1", changed)
    assert status == att.STALE, problems
    assert "Re-attest, do not re-use" in " ".join(problems)


def test_an_attestation_goes_stale_when_head_moves(att) -> None:
    """A review is a judgement about one state of the repository."""
    att._write("G1", _record(att, attested_digest=att.report_digest(REPORT)))
    att.head = lambda: "b" * 40
    status, _record_out, problems = att.evaluate("G1", REPORT)
    assert status == att.STALE, problems
    assert any("HEAD" in problem for problem in problems)


def test_recording_an_attestation_does_not_change_the_digest_it_is_checked_against(att) -> None:
    """Otherwise the first write invalidates itself and no gate could ever resolve.

    The report the gate writes carries the reviewer field it just filled in. Hashing the report as
    written would make the digest depend on the signature, so the mechanism could only ever report
    STALE.
    """
    signed = dict(REPORT)
    signed["required_report_fields"] = {"reviewer": {"value": None, "status": "OUTSTANDING"}}
    before = att.report_digest(signed)
    signed["required_report_fields"] = {
        "reviewer": {"value": REVIEWER, "status": "PRESENT"},
        "commit": {"value": "a" * 40, "status": "PRESENT"},
    }
    assert att.report_digest(signed) == before


@pytest.mark.parametrize(
    "reviewer",
    ["automated agent", "Automated Agent", "kilo", "an AI assistant", "TBD", "unknown"],
)
def test_a_reviewer_that_reads_as_an_agent_is_refused(att, reviewer: str) -> None:
    """docs/11 requires a named human. This is the exact value it forbids, in several spellings."""
    problems = att._problems(_record(att, reviewer=reviewer), "G1")
    assert problems, f"{reviewer!r} was accepted as a named human reviewer"
    assert any("agent" in problem or "human reviewer" in problem for problem in problems)


def test_a_statement_that_says_nothing_is_refused(att) -> None:
    problems = att._problems(_record(att, statement="looks good"), "G1")
    assert any("statement" in problem for problem in problems)


def test_an_attestation_for_another_gate_is_refused(att) -> None:
    problems = att._problems(_record(att, gate="G4"), "G1")
    assert any("not G1" in problem for problem in problems)


def test_every_required_field_is_required(att) -> None:
    for field in att.REQUIRED:
        problems = att._problems(_record(att, **{field: ""}), "G1")
        assert any(field in problem for problem in problems), f"{field} was accepted when empty"


def test_malformed_json_is_malformed_and_not_outstanding(att) -> None:
    """A corrupt file must not read as 'nobody has signed yet' - those are different failures."""
    path = att.path_for("G1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    status, _record_out, problems = att.evaluate("G1", REPORT)
    assert status == att.MALFORMED, problems
    assert any("not valid JSON" in problem for problem in problems)
