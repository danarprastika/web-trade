"""Probe: does a PostgreSQL driver exist that satisfies the toolchain gate unweakened?

EV-059 recorded that no Go driver can be added, because pgx pulls a dependency whose only
versions are pseudo-versions and verify_toolchain.py refuses those. That is true of pgx
specifically. It does not establish the absence of every driver.

This calls the gate's own verify_go_pins against candidate go.mod files, rather than
reimplementing its rule, so the answer is the gate's and not this script's.

Read-only with respect to the repository: it inspects files under _driver_probe/ and never
touches services/control-plane.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import verify_toolchain as vt  # noqa: E402


def judge(path: Path) -> tuple[bool, str]:
    report = vt.Report()
    vt.verify_go_pins(path, path.as_posix(), report)
    if report.passed:
        return True, f"PASS ({report.checks_run} checks)"
    return False, "; ".join(report.failures)


def main() -> None:
    probe = ROOT / "_driver_probe"
    if not probe.is_dir():
        raise SystemExit("no _driver_probe directory; run the probe setup first")

    candidates = sorted(probe.glob("*/go.mod"))
    if not candidates:
        raise SystemExit("no candidate go.mod files found under _driver_probe/")

    width = max(len(p.parent.name) for p in candidates)
    failed = False
    for gomod in candidates:
        ok, detail = judge(gomod)
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {gomod.parent.name:<{width}}  {detail}")
        if not ok:
            failed = True

    print()
    if failed:
        print("  at least one candidate would fail the gate unweakened")
    else:
        print("  every candidate satisfies verify_go_pins with no change to the gate")


if __name__ == "__main__":
    main()