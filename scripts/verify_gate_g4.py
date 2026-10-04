#!/usr/bin/env python3
"""G4 - Research. Mechanical criteria only; the reviewer field comes from scripts/attestation.py.

docs/11_EXECUTION_GATES.md G4: "datasets are versioned, backtests are deterministic, artifacts are
reproducible, and no research worker has financial authority."

Those are four claims, and three of them are the kind that are usually satisfied by a README. So each
criterion here is a computation whose result could have been different, not a check that the code
contains a feature:

  versioned      The registry keys a dataset by a content fingerprint. Equal content must yield the
                 same fingerprint on two independent constructions, and different content a
                 different one - otherwise "versioned" is a name for a counter.
  deterministic  The same dataset, strategy and seed must produce a byte-identical result across two
                 runs *in separate processes*, because the ways a backtest becomes irreproducible -
                 dict ordering, hash randomisation, a clock, an unseeded RNG - are all invisible to
                 two calls in one interpreter.
  reproducible   Two independently built artifacts must carry the same content digest.
  no authority   The workers' own authority-boundary suite, which asserts the absence of network,
                 database, process and credential capability rather than the presence of a control.

G4 previously had no gate script at all: WI-140 was blocked on a human reviewer for a report that
nothing could produce. That is the same defect as WI-196 and WI-197 - a documented requirement with
no enforcement - and it is why the reviewer field, not the criteria, was the last thing standing.

Run:  python scripts/verify_gate_g4.py [--json]
Exit: 0 all criteria PASS, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / ".kilo" / "ecc" / "project-brain" / "evidence" / "wi-140"

# Both workers are imported from source rather than assumed installed. A gate that silently used a
# stale site-packages copy would report on a different tree than the one it claims to certify.
for _src in ("workers/research/src", "workers/backtest/src"):
    sys.path.insert(0, str(ROOT / _src))

from webtrade_backtest.artifacts import build_artifact  # noqa: E402
from webtrade_backtest.harness import (  # noqa: E402
    BacktestParams,
    Decision,
    run_backtest,
)
from webtrade_research.content_address import canonical_digest  # noqa: E402
from webtrade_research.dataset import Bar, Dataset, DatasetRegistry  # noqa: E402

BASE = datetime(2026, 1, 5, 9, 0, 0, tzinfo=UTC)


def _at(minutes: int) -> datetime:
    return BASE + timedelta(minutes=minutes)


def _bar(sequence: int, minute: int, close: str, instrument: str = "BTC-USD") -> Bar:
    return Bar(
        instrument=instrument,
        event_time=_at(minute),
        available_at=_at(minute),
        open=close,
        high=close,
        low=close,
        close=close,
        volume="1",
        sequence=sequence,
    )


def _dataset(name: str = "g4-fixture") -> Dataset:
    """Seven bars across two instruments, which is enough for the fingerprint to depend on more
    than the instrument list."""
    return Dataset.create(
        name=name,
        schema_version="bars/1",
        bars=[
            _bar(0, 0, "100"),
            _bar(1, 1, "101"),
            _bar(2, 2, "102", "ETH-USD"),
            _bar(3, 3, "103"),
            _bar(4, 4, "104", "ETH-USD"),
            _bar(5, 5, "105"),
            _bar(6, 6, "106", "ETH-USD"),
        ],
    )


class _BuyAndHold:
    """A strategy with no hidden state and no clock, so any nondeterminism observed belongs to the
    harness or the dataset rather than to the strategy."""

    def decide(self, view) -> Decision:  # noqa: ANN001 - the protocol is structural
        if view.as_of == view.as_of and not view.bars:
            return Decision(as_of=view.as_of, side="hold", quantity="0")
        return Decision(as_of=view.as_of, side="buy", quantity="1", reason="buy and hold")


@dataclass
class Criterion:
    criterion_id: str
    name: str
    status: str
    evidence: str

    def as_dict(self) -> dict:
        return {
            "id": self.criterion_id,
            "name": self.name,
            "status": self.status,
            "evidence": self.evidence,
            "mechanically_verified": True,
        }


def _params(seed: int = 4242) -> BacktestParams:
    return BacktestParams(seed=seed, start=_at(0), end=_at(60), initial_cash="100000")


def _run_once() -> tuple[str, str]:
    """One backtest, returning (result canonical digest, artifact digest)."""
    dataset = _dataset()
    result = run_backtest(dataset, _BuyAndHold(), _params(), strategy_name="buy-and-hold")
    artifact = build_artifact(
        result=result,
        dataset=dataset,
        code_revision="g4-gate-fixture",
        feature_specification_version="g4/1",
        evaluation_report="G4 gate determinism fixture; not a performance claim.",
    )
    return canonical_digest(result.to_canonical()), artifact.digest


def criterion_determinism_in_separate_processes() -> Criterion:
    """Two runs in two fresh interpreters must agree exactly.

    Separate processes, not two calls. Everything that makes a backtest irreproducible in practice -
    PYTHONHASHSEED randomising dict iteration, a module-level cache surviving between calls, a clock
    read at import - is invisible to a second call in the same interpreter and fully visible to a
    second process. A same-process check would have passed against all of them.
    """
    runs: list[tuple[str, str]] = []
    for _ in range(2):
        proc = subprocess.run(
            [sys.executable, "-I", str(Path(__file__).resolve()), "--child"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if proc.returncode != 0:
            return Criterion(
                "G4.2",
                "Backtests are deterministic",
                "FAIL",
                f"the child run failed ({proc.returncode}): {proc.stderr.strip()[:400]}",
            )
        try:
            runs.append(tuple(json.loads(proc.stdout.strip())))  # type: ignore[arg-type]
        except json.JSONDecodeError as exc:
            return Criterion(
                "G4.2", "Backtests are deterministic", "FAIL", f"unreadable child output: {exc}"
            )

    first, second = runs
    if first != second:
        return Criterion(
            "G4.2",
            "Backtests are deterministic",
            "FAIL",
            f"two processes disagree. result/artifact first={first[0][:16]}/{first[1][:16]} "
            f"second={second[0][:16]}/{second[1][:16]}",
        )
    if not first[0] or not first[1]:
        return Criterion(
            "G4.2",
            "Backtests are deterministic",
            "FAIL",
            "the child reported an empty digest, so agreement was agreement about nothing",
        )
    return Criterion(
        "G4.2",
        "Backtests are deterministic",
        "PASS",
        f"two isolated interpreters produced identical results ({first[0][:16]}) and identical "
        f"artifact digests ({first[1][:16]}) for the same dataset, strategy and seed",
    )


def criterion_artifacts_reproducible() -> Criterion:
    """Two independently constructed artifacts must carry the same content digest, and the digest
    must depend on the content: a changed evaluation report has to change it, or the digest is
    measuring nothing."""
    dataset = _dataset()

    def build(report: str, revision: str = "g4-gate-fixture") -> str:
        result = run_backtest(dataset, _BuyAndHold(), _params(), strategy_name="buy-and-hold")
        return build_artifact(
            result=result,
            dataset=dataset,
            code_revision=revision,
            feature_specification_version="g4/1",
            evaluation_report=report,
        ).digest

    a = build("report one")
    b = build("report one")
    if a != b:
        return Criterion(
            "G4.3",
            "Artifacts are reproducible",
            "FAIL",
            f"two builds of the same inputs disagree: {a[:16]} vs {b[:16]}",
        )
    c = build("report two, different text")
    if c == a:
        return Criterion(
            "G4.3",
            "Artifacts are reproducible",
            "FAIL",
            "changing the evaluation report did not change the digest, so the digest does not "
            "cover the content it claims to address",
        )
    return Criterion(
        "G4.3",
        "Artifacts are reproducible",
        "PASS",
        f"identical inputs yield digest {a[:16]} across two builds, and altering the evaluation "
        f"report changes it to {c[:16]}, so the digest tracks content rather than being constant",
    )


def criterion_datasets_versioned() -> Criterion:
    """Content addressing, checked in the direction that matters.

    That equal content yields equal fingerprints is the easy half. The half that catches a registry
    keyed by a counter or a name is that *different* content must yield a different fingerprint, and
    that the registry must hand back the dataset registered under that fingerprint.
    """
    registry = DatasetRegistry()
    first = _dataset()
    second = _dataset()  # independently constructed, identical content
    different = Dataset.create(
        name="g4-fixture",
        schema_version="bars/1",
        bars=[_bar(0, 0, "999")] + [_bar(i, i, str(100 + i)) for i in range(1, 7)],
    )

    # The registry raises rather than returning a verdict when it is handed a fingerprint collision.
    # Left uncaught that turns a broken fingerprint into a traceback, which is the worst possible
    # report: a crash says nothing about whether datasets are versioned. Caught, it is a FAIL that
    # names the reason, which is what a gate owes its reader.
    try:
        fp_first = registry.register(first)
        fp_second = registry.register(second)
        fp_different = registry.register(different)
    except Exception as exc:  # noqa: BLE001 - any registry refusal is a FAIL, not a crash
        return Criterion(
            "G4.1",
            "Datasets are versioned",
            "FAIL",
            f"the registry refused a legitimate registration: {type(exc).__name__}: {exc}",
        )
    if fp_first != fp_second:
        return Criterion(
            "G4.1",
            "Datasets are versioned",
            "FAIL",
            f"two independently built identical datasets fingerprinted differently: "
            f"{fp_first[:16]} vs {fp_second[:16]}; the fingerprint is not a function of content",
        )
    if fp_first == fp_different:
        return Criterion(
            "G4.1",
            "Datasets are versioned",
            "FAIL",
            "a dataset with different content received the same fingerprint, so the version does "
            "not distinguish versions",
        )
    if registry.get(fp_first) is not first:
        return Criterion(
            "G4.1",
            "Datasets are versioned",
            "FAIL",
            "the registry did not return the dataset registered under its own fingerprint",
        )
    if set(registry.fingerprints()) != {fp_first, fp_different}:
        return Criterion(
            "G4.1", "Datasets are versioned", "FAIL", "the registry's fingerprint set is not its contents"
        )
    return Criterion(
        "G4.1",
        "Datasets are versioned",
        "PASS",
        f"content addressing holds in both directions: identical content fingerprints to "
        f"{fp_first[:16]} across two constructions, altered content to {fp_different[:16]}, and "
        f"the registry returns each dataset under its own fingerprint ({len(registry)} registered)",
    )


def criterion_no_financial_authority() -> Criterion:
    """The workers' own authority-boundary suite, run as-is.

    Delegated rather than reimplemented: that suite already parses the ASTs, checks declared
    dependencies, pins requirements exactly and hunts credential literals. A second copy here would
    be a weaker version of a check that already exists, and would drift from it.
    """
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "workers/research/tests/test_authority_boundary.py",
            "-q",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=600,
    )
    tail = (proc.stdout or "").strip().splitlines()
    summary = tail[-1] if tail else "no output"
    if proc.returncode != 0:
        return Criterion(
            "G4.4",
            "No research worker has financial authority",
            "FAIL",
            f"the authority-boundary suite failed: {summary}",
        )
    return Criterion(
        "G4.4",
        "No research worker has financial authority",
        "PASS",
        f"workers/research/tests/test_authority_boundary.py: {summary} - no network, database, "
        f"process or credential capability in either worker, dependencies pinned exactly",
    )


def git_field(field: list[str]) -> str:
    proc = subprocess.run(["git", *field], cwd=ROOT, capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else "unavailable"


def _attestation():
    path = ROOT / "scripts" / "attestation.py"
    if not path.is_file():
        raise SystemExit(f"cannot load {path}; the attestation rule is required by G4")
    import importlib.util

    spec = importlib.util.spec_from_file_location("_attestation", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="emit the report as JSON and write nothing")
    parser.add_argument(
        "--child",
        action="store_true",
        help="internal: run one backtest and print its two digests, for the determinism criterion",
    )
    args = parser.parse_args(argv)

    if args.child:
        result_digest, artifact_digest = _run_once()
        print(json.dumps([result_digest, artifact_digest]))
        return 0

    results = [
        criterion_datasets_versioned(),
        criterion_determinism_in_separate_processes(),
        criterion_artifacts_reproducible(),
        criterion_no_financial_authority(),
    ]
    failed = [r for r in results if r.status == "FAIL"]

    head = git_field(["rev-parse", "HEAD"])
    dirty_lines = [
        line for line in git_field(["status", "--porcelain"]).splitlines() if line.strip()
    ]

    attested_payload = {
        "gate": "G4",
        "specification": "docs/11_EXECUTION_GATES.md section G4",
        "criteria": [r.as_dict() for r in results],
    }
    att_status, att_record, _problems = _attestation().evaluate("G4", attested_payload)

    if att_status == "RESOLVED" and att_record is not None:
        reviewer_field = {
            "value": att_record["reviewer"],
            "status": "PRESENT",
            "role": att_record["reviewer_role"],
            "attested_at": att_record["attested_at"],
            "statement": att_record["statement"],
            "attested_digest": att_record["attested_digest"],
        }
    else:
        reviewer_field = {
            "value": None,
            "status": "OUTSTANDING",
            "reason": f"No named human reviewer has attested this report (status {att_status}). "
                      f"docs/11 requires every gate report to name its reviewer, and forbids "
                      f"partial completion.",
        }

    tree_clean = not dirty_lines
    commit_field = {
        "value": head,
        "status": "PRESENT" if tree_clean else "OUTSTANDING",
        "reason": (
            f"HEAD is {head[:12]} and the working tree is clean, so the referenced commit contains "
            f"the work being certified."
            if tree_clean
            else f"HEAD is {head[:12]} but {len(dirty_lines)} path(s) are untracked or modified."
        ),
    }

    binary_pass = not failed and reviewer_field["status"] == "PRESENT" and tree_clean
    binary_reason = (
        "All four mechanical criteria PASS, the reviewer field names an attested human whose "
        "attestation matches this report's digest and names HEAD, and the working tree is clean."
        if binary_pass
        else f"{len(results) - len(failed)} of {len(results)} mechanical criteria PASS; reviewer "
             f"field {reviewer_field['status']}, commit field {commit_field['status']}. docs/11: a "
             f"gate is PASS only when every listed criterion is satisfied."
    )

    report = {
        "gate": "G4",
        "title": "Research",
        "specification": "docs/11_EXECUTION_GATES.md section G4",
        "verified_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "criteria": [r.as_dict() for r in results],
        "mechanical_result": {
            "total": len(results),
            "pass": len(results) - len(failed),
            "fail": len(failed),
        },
        "required_report_fields": {
            "reviewer": reviewer_field,
            "commit": commit_field,
            "timestamp": {"value": "recorded above in verified_at", "status": "PRESENT"},
            "command_output": {"value": "per criterion", "status": "PRESENT"},
            "binary_pass_fail": {
                "value": "PASS" if binary_pass else "FAIL",
                "status": "PRESENT",
                "reason": binary_reason,
            },
            "evidence_digests": {"value": "per criterion", "status": "PRESENT"},
        },
        "attested_payload": attested_payload,
        "verdict": "PASS" if binary_pass else "FAIL",
        "verdict_basis": [
            f"{len(results) - len(failed)} of {len(results)} mechanical criteria PASS",
            f"reviewer field {reviewer_field['status']}",
            f"commit field {commit_field['status']} (HEAD {head[:12]}, {len(dirty_lines)} untracked/modified)",
        ],
    }

    if args.json:
        print(json.dumps(report, indent=2))
        return 0 if not failed else 1

    print(f"G4 - Research  ({report['verified_at']})")
    for r in results:
        print(f"  {r.status:4}  {r.criterion_id}  {r.name}")
        print(f"        {r.evidence}")
    print()
    print(f"  mechanical: {report['mechanical_result']['pass']}/{len(results)} PASS")
    print(f"  reviewer:   {reviewer_field['status']}")
    print(f"  commit:     {commit_field['status']}")
    print(f"  VERDICT:    {report['verdict']}")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "G4-gate-report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    lines = [
        f"# G4 gate report — Research",
        "",
        "Authority: `docs/11_EXECUTION_GATES.md` section G4. Generated by `scripts/verify_gate_g4.py`.",
        "Re-running the script overwrites this file; it is a derived artifact, not an input.",
        "",
        f"**Verdict: {report['verdict']}**",
        "",
        f"- Commit: `{head}`",
        f"- Executed at (UTC): {report['verified_at']}",
        f"- Mechanical criteria: {report['mechanical_result']['pass']}/{len(results)} PASS",
        f"- Reviewer field: {reviewer_field['status']}",
        f"- Commit field: {commit_field['status']}",
        "",
        "## Criteria",
        "",
        "| ID | Criterion | Result |",
        "|---|---|---|",
    ]
    for r in results:
        lines.append(f"| {r.criterion_id} | {r.name} | **{r.status}** |")
    lines += ["", "## Evidence", ""]
    for r in results:
        lines += [f"### {r.criterion_id} — {r.name}", "", f"- **{r.status}**: {r.evidence}", ""]
    lines += [
        "## Outstanding fields in detail",
        "",
    ]
    for name, field in report["required_report_fields"].items():
        if isinstance(field, dict) and field.get("status") == "OUTSTANDING":
            lines += [f"- **{name}**: {field.get('reason')}", ""]
    (REPORT_DIR / "G4-gate-report.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"\nwrote {REPORT_DIR / 'G4-gate-report.json'}")
    print(f"wrote {REPORT_DIR / 'G4-gate-report.md'}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())