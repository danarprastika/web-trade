"""Prove each G4 criterion can fail. A gate that cannot fail is not evidence.

Every criterion in scripts/verify_gate_g4.py passes on the real tree. That is the expected state and
it is also the state a broken gate produces, so each criterion is here shown failing against a
deliberately broken input - the same discipline scripts/prove_bash_gate_detects.py and
scripts/prove_secret_scan_gate.py apply to their gates.

The determinism proof mutates a COPY of the gate in a temporary directory and never writes to the
committed script. Mutating the real file and restoring it would risk leaving it damaged, and a proof
that can damage the thing it proves is not worth running.

Run:  python scripts/prove_gate_g4_detects.py
Exit: 0 when every criterion is shown failing when it should.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
GATE = ROOT / "scripts" / "verify_gate_g4.py"


def _load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def prove_versioning_detects_a_constant_fingerprint() -> bool:
    """Break content addressing by making every dataset fingerprint the same value."""
    gate = _load(GATE, "_g4_v1")
    original = gate.Dataset.__dict__["compute_fingerprint"]

    # compute_fingerprint is a @staticmethod taking (name, schema_version, bars), so the replacement
    # has to be installed as a staticmethod too. A plain function here is called with the three
    # arguments directly and the patch silently does not take effect - which would make this proof
    # report a FAIL that the criterion never produced.
    def constant(*args, **kwargs):  # noqa: ANN002, ANN003, ARG001
        return "sha256:" + "0" * 64

    gate.Dataset.compute_fingerprint = staticmethod(constant)
    try:
        criterion = gate.criterion_datasets_versioned()
    finally:
        gate.Dataset.compute_fingerprint = original
    ok = criterion.status == "FAIL"
    print(f"  [{'ok' if ok else 'FAIL'}] a constant fingerprint is refused: {criterion.evidence[:110]}")
    return ok


def prove_determinism_detects_a_nondeterministic_strategy() -> bool:
    """Make the strategy's output vary between processes, then confirm the digests disagree.

    The mutation lands in a temporary copy of the gate, because the criterion compares two
    *separate* interpreter runs and cannot be steered by patching the parent process.
    """
    source = GATE.read_text(encoding="utf-8")
    # The copy must still resolve ROOT to this repository, or it cannot import the workers it is
    # meant to be testing. Deriving ROOT from the copy's own path would make the child fail on an
    # ImportError and prove nothing about determinism.
    rooted = source.replace(
        "ROOT = Path(__file__).resolve().parents[1]",
        f"ROOT = Path({str(ROOT)!r})",
        1,
    )
    if rooted == source:
        print("  [FAIL] the ROOT substitution did not apply; the proof would prove nothing")
        return False
    broken = rooted.replace(
        'return Decision(as_of=view.as_of, side="buy", quantity="1", reason="buy and hold")',
        "import os as _os\n"
        '        return Decision(as_of=view.as_of, side=("buy" if _os.environ.get("G4_SIDE", "buy") '
        '== "buy" else "sell"), quantity="1", reason="mutated")',
    )
    if broken == rooted:
        print("  [FAIL] the determinism mutation did not apply; the proof would prove nothing")
        return False

    with tempfile.TemporaryDirectory(prefix="g4-proof-") as tmp:
        copy_path = pathlib.Path(tmp) / "verify_gate_g4_mutated.py"
        copy_path.write_text(broken, encoding="utf-8", newline="\n")

        digests = []
        for side in ("buy", "sell"):
            env = {**dict(__import__("os").environ), "G4_SIDE": side}
            proc = subprocess.run(
                [sys.executable, "-I", str(copy_path), "--child"],
                capture_output=True,
                text=True,
                env=env,
                timeout=300,
            )
            if proc.returncode != 0:
                print(f"  [FAIL] the mutated child failed: {proc.stderr.strip()[:200]}")
                return False
            digests.append(tuple(json.loads(proc.stdout.strip())))

    ok = digests[0] != digests[1]
    print(
        f"  [{'ok' if ok else 'FAIL'}] a strategy that varies between processes yields different "
        f"digests: {digests[0][0][:12]} vs {digests[1][0][:12]}"
    )
    return ok


def prove_reproducibility_detects_a_constant_artifact_digest() -> bool:
    """Break the artifact digest so every build claims the same identity."""
    gate = _load(GATE, "_g4_v2")
    original = gate.build_artifact

    class _Frozen:
        def __init__(self, wrapped):  # noqa: ANN001
            self._wrapped = wrapped

        def __call__(self, **kwargs):  # noqa: ANN003
            built = original(**kwargs)
            return type(
                "A",
                (),
                {
                    "digest": "sha256:" + "1" * 64,
                    "evaluation_report": built.evaluation_report,
                },
            )()

    gate.build_artifact = _Frozen(original)
    try:
        criterion = gate.criterion_artifacts_reproducible()
    finally:
        gate.build_artifact = original
    ok = criterion.status == "FAIL"
    print(f"  [{'ok' if ok else 'FAIL'}] a constant artifact digest is refused: {criterion.evidence[:110]}")
    return ok


def prove_authority_criterion_runs_the_real_suite() -> bool:
    """The authority criterion must delegate to a suite that exists, and must fail if it does not.

    Asserting that a subprocess command fails is done by pointing it at a path that is not there, so
    the check is shown to propagate a real failure rather than to report PASS unconditionally.
    """
    gate = _load(GATE, "_g4_v3")
    criterion = gate.criterion_no_financial_authority()
    if criterion.status != "PASS":
        print(f"  [FAIL] the authority suite does not pass on the real tree: {criterion.evidence[:140]}")
        return False

    # The suite path is a literal inside the function; point the check at a file that cannot exist by
    # running it from a copy whose argument has been replaced.
    source = GATE.read_text(encoding="utf-8")
    rooted = source.replace(
        "ROOT = Path(__file__).resolve().parents[1]",
        f"ROOT = Path({str(ROOT)!r})",
        1,
    )
    broken = rooted.replace(
        '"workers/research/tests/test_authority_boundary.py",',
        '"workers/research/tests/no_such_boundary_test.py",',
    )
    if broken == rooted:
        print("  [FAIL] the authority mutation did not apply; the proof would prove nothing")
        return False

    with tempfile.TemporaryDirectory(prefix="g4-proof-") as tmp:
        copy_path = pathlib.Path(tmp) / "verify_gate_g4_mutated.py"
        copy_path.write_text(broken, encoding="utf-8", newline="\n")
        mutated = _load(copy_path, "_g4_v3_mutated")
        criterion = mutated.criterion_no_financial_authority()

    ok = criterion.status == "FAIL"
    print(f"  [{'ok' if ok else 'FAIL'}] a missing authority suite is refused: {criterion.evidence[:110]}")
    return ok


def main() -> int:
    print("G4 gate discrimination proof")
    checks = [
        ("versioning rejects a constant fingerprint", prove_versioning_detects_a_constant_fingerprint),
        ("determinism rejects a varying strategy", prove_determinism_detects_a_nondeterministic_strategy),
        ("reproducibility rejects a constant digest", prove_reproducibility_detects_a_constant_artifact_digest),
        ("authority propagates a real suite failure", prove_authority_criterion_runs_the_real_suite),
    ]
    results = [(name, fn()) for name, fn in checks]
    failed = [name for name, ok in results if not ok]
    print()
    if failed:
        print(f"G4 gate proof: FAIL ({len(failed)} of {len(results)} criteria could not be shown failing)")
        for name in failed:
            print(f"  - {name}")
        return 1
    print(f"G4 gate proof: PASS ({len(results)} criteria each shown failing when they should)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())