"""Run every release gate and report one line per gate with its own evidence.

Written because the previous way of doing this was a shell function that silently failed to
invoke anything and printed eleven FAILs for eleven gates that had not run. A gate sweep that
reports failures it did not measure is worse than no sweep, because it looks like a result.

Each gate runs as its own subprocess with a timeout. A gate that hangs is reported as a
failure with the word TIMEOUT rather than being allowed to stall the whole sweep, and a gate
that fails is reported with the last line of its real output so the reason is visible without
re-running it.

Usage:
    python scripts/run_gates.py
    python scripts/run_gates.py --only db rehearsal
    python scripts/run_gates.py --list
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Gates are grouped the way a reviewer thinks about them: the checks that decide whether the
# repository is coherent, then the ones that decide whether the database is real, then the
# code gates. The order is the order of trust, cheapest and most disqualifying first.
@dataclass
class Gate:
    name: str
    command: list[str]
    expect: str = ""
    timeout: int = 1800
    group: str = "code"
    env: dict = field(default_factory=dict)


GATES: list[Gate] = [
    Gate("toolchain", [sys.executable, "scripts/verify_toolchain.py"],
         expect="PASS", group="repository"),
    Gate("project-brain", [sys.executable, "scripts/verify_project_brain.py"],
         expect="PASS", group="repository"),
    Gate("pytest-ci", [sys.executable, "-m", "pytest", "tests/ci", "-q"],
         group="repository"),
    Gate("pytest-research", [sys.executable, "-m", "pytest", "workers/research/tests", "-q"],
         group="repository"),
    Gate("pytest-backtest", [sys.executable, "-m", "pytest", "workers/backtest/tests", "-q"],
         group="repository"),

    Gate("db-0001-ledger",
         [sys.executable, "scripts/verify_ledger_db.py",
          "--migration", "db/migrations/0001_ledger.sql",
          "--verify", "db/tests/0001_ledger_verify.sql"],
         expect="ALL 18 DATABASE ASSERTIONS PASSED", group="database"),
    Gate("db-0002-audit",
         [sys.executable, "scripts/verify_ledger_db.py",
          "--migration", "db/migrations/0002_audit.sql",
          "--verify", "db/tests/0002_audit_verify.sql"],
         expect="ALL 20 DATABASE ASSERTIONS PASSED", group="database"),
    Gate("db-0003-authz",
         [sys.executable, "scripts/verify_ledger_db.py",
          "--migration", "db/migrations/0003_authz.sql",
          "--verify", "db/tests/0003_authz_verify.sql"],
         expect="ALL 54 DATABASE ASSERTIONS PASSED", group="database"),
    Gate("db-0004-model-registry",
         [sys.executable, "scripts/verify_ledger_db.py",
          "--migration", "db/migrations/0004_model_registry.sql",
          "--verify", "db/tests/0004_model_registry_verify.sql"],
         expect="ALL 45 DATABASE ASSERTIONS PASSED", group="database"),
    Gate("migration-rehearsal", [sys.executable, "scripts/rehearse_migrations.py"],
         expect="MIGRATION REHEARSAL PASSED", group="database"),

    Gate("go-test-control-plane",
         ["go", "-C", "services/control-plane", "test", "-count=1", "./..."],
         group="code"),
    Gate("sqlc-generate", ["sqlc", "generate"], group="code"),
    Gate("sqlc-vet", ["sqlc", "vet"], group="code"),
]


def run_gate(gate: Gate) -> tuple[bool, str]:
    env = dict(os.environ)
    # sqlc lives in the Go bin directory rather than on PATH by default, and a gate that
    # fails because a binary is not on PATH is a gate reporting the wrong thing.
    gopath_bin = subprocess.run(["go", "env", "GOPATH"], capture_output=True,
                                text=True, timeout=60).stdout.strip()
    if gopath_bin:
        env["PATH"] = os.path.join(gopath_bin, "bin") + os.pathsep + env.get("PATH", "")
    env.update(gate.env)

    try:
        proc = subprocess.run(gate.command, cwd=ROOT, capture_output=True, text=True,
                              timeout=gate.timeout, env=env, check=False)
    except FileNotFoundError as exc:
        return False, f"command not found: {exc}"
    except subprocess.TimeoutExpired:
        return False, f"TIMEOUT after {gate.timeout}s"

    combined = (proc.stdout + "\n" + proc.stderr).strip()
    last = combined.splitlines()[-1] if combined else "(no output)"

    if proc.returncode != 0:
        return False, last
    if gate.expect and gate.expect not in combined:
        # A zero exit code is not proof when the gate is supposed to report a specific
        # result. A rehearsal that printed nothing and exited 0 must not be recorded as a
        # pass, which is the failure mode this check exists for.
        return False, f"exit 0 but {gate.expect!r} not in output: {last}"
    return True, last


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="*", help="run only gates whose name contains one of these")
    parser.add_argument("--list", action="store_true", help="list the gates and exit")
    args = parser.parse_args()

    if args.list:
        for g in GATES:
            print(f"{g.group:12} {g.name}")
        return 0

    selected = GATES
    if args.only:
        selected = [g for g in GATES if any(k in g.name for k in args.only)]
        if not selected:
            print(f"no gate matches {args.only}", file=sys.stderr)
            return 2

    failures = 0
    current_group = None
    for gate in selected:
        if gate.group != current_group:
            current_group = gate.group
            print(f"\n[{gate.group}]")
        ok, detail = run_gate(gate)
        if not ok:
            failures += 1
        print(f"  {'PASS' if ok else 'FAIL'}  {gate.name:26} {detail}")

    print()
    if failures:
        print(f"{failures} of {len(selected)} gate(s) FAILED")
        return 1
    print(f"all {len(selected)} gate(s) passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
