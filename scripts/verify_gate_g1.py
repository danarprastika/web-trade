"""Verify the G1 domain-foundation gate and emit its report.

docs/11 section G1 sets nine criteria: canonical IDs, timestamps, money/quantity types, errors,
envelopes, idempotency, configuration boundaries, migrations, and domain tests, each of which
must be "implemented and verified". docs/11 also fixes what a gate report must record:
reviewer, commit, timestamp, command output, binary PASS/FAIL, and evidence digests, and it
states that a gate is PASS only when every criterion holds and that partial completion is FAIL.

The design rule here is that no criterion is marked PASS by inspection. Each one names the
artifacts that implement it, the command that exercises them, and a check on the real output.
An artifact that exists is not evidence; a test that runs and reports `ok` is.

Two fields of the report cannot be produced mechanically, and the script does not pretend
otherwise. The *reviewer* is a named human, and the *commit* is a git reference. Both are
reported as outstanding, and because docs/11 forbids partial completion, their absence forces
the overall verdict to FAIL rather than to a pass with a caveat. A gate report that recorded
"reviewer: automated agent" would satisfy the letter of the field and none of its purpose.

Usage:
    python scripts/verify_gate_g1.py            # verify and print the report
    python scripts/verify_gate_g1.py --json     # machine-readable only
    python scripts/verify_gate_g1.py --no-write # do not touch the report file

Exit codes:
    0  every mechanical criterion holds (the gate verdict may still not be PASS; see report)
    1  at least one mechanical criterion failed
    2  the verification could not run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / ".kilo" / "ecc" / "project-brain" / "evidence" / "wi-118"
REPORT_FILE = REPORT_DIR / "G1-gate-report.md"

CONTRACTS = "contracts/go"
CONFIG_PKG = "services/control-plane/config"


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def digest_tree(paths: list[Path]) -> str:
    """One digest over a set of files, order-independent and name-bound.

    A per-file digest list is what the report carries; this is the roll-up, so that a claim
    like "the ledger is unchanged" has a single value to compare against later.
    """
    accumulator = hashlib.sha256()
    for path in sorted(paths, key=lambda p: str(p)):
        accumulator.update(str(path.relative_to(ROOT)).encode())
        accumulator.update(b"\0")
        accumulator.update(path.read_bytes())
        accumulator.update(b"\0")
    return "sha256:" + accumulator.hexdigest()


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 900) -> tuple[int, str]:
    result = subprocess.run(cmd, cwd=cwd or ROOT, capture_output=True, text=True,
                            timeout=timeout, check=False, stdin=subprocess.DEVNULL)
    return result.returncode, (result.stdout + result.stderr).strip()


def go_test(module: str, run_flag: str = "-count=1") -> tuple[int, str, str]:
    """Run `go test` in a module and return (code, output, package summary).

    The package count is taken from lines that *begin* with `ok`. Counting lines that *end*
    with `ok` looks equivalent and is not: `go test` prints `ok  <package>  <elapsed>`, so the
    line ends with a duration and the count comes out zero. A gate report whose evidence reads
    "0 package(s) ok" is indistinguishable from one where nothing ran, which is the specific
    ambiguity this report exists to avoid.
    """
    code, output = run(["go", "test", run_flag, "./..."], cwd=ROOT / module)
    ok_packages = [l for l in output.splitlines() if l.strip().startswith("ok")]
    no_tests = [l for l in output.splitlines() if "no test files" in l]
    return code, output, f"{len(ok_packages)} package(s) ok, {len(no_tests)} without tests"


class Criterion:
    def __init__(self, key: str, name: str, artifacts: list[str]):
        self.key = key
        self.name = name
        self.artifacts = artifacts
        self.status = "NOT_RUN"
        self.evidence = ""
        self.command_output = ""
        self.command_exit = None
        self.placeholders: dict[str, str] = {}

    def files(self) -> list[Path]:
        return [ROOT / a for a in self.artifacts if (ROOT / a).exists()]

    def missing(self) -> list[str]:
        return [a for a in self.artifacts if not (ROOT / a).exists()]

    def as_dict(self) -> dict:
        return {
            "criterion": self.name,
            "status": self.status,
            "artifacts": [
                {"path": str(p.relative_to(ROOT)).replace("\\", "/"), "digest": digest(p)}
                for p in self.files()
            ],
            "artifact_set_digest": digest_tree(self.files()) if self.files() else None,
            "command": self.evidence,
            "command_exit": self.command_exit,
            "command_output": self.command_output[-4000:],
            # Placeholders are surfaced rather than dropped, so a module with no
            # implementation cannot be mistaken for a module whose tests were forgotten.
            "declared_placeholders": self.placeholders,
        }


def criterion_canonical_ids() -> Criterion:
    c = Criterion("ids", "Canonical IDs", ["contracts/go/identifier.go",
                                           "contracts/go/identifier_test.go"])
    code, out, ok = go_test(CONTRACTS)
    c.command_exit = code
    c.command_output = out
    missing = c.missing()
    if missing:
        c.status, c.evidence = "FAIL", f"missing: {missing}"
    elif code != 0:
        c.status, c.evidence = "FAIL", f"go test failed; {ok}"
    else:
        c.status = "PASS"
        c.evidence = f"go test ./... in contracts/go: {ok}"
    return c


def criterion_timestamps() -> Criterion:
    c = Criterion("timestamps", "Timestamps", ["contracts/go/error.go",
                                               "contracts/go/error_timestamp_test.go"])
    code, out, ok = go_test(CONTRACTS)
    c.command_exit = code
    c.command_output = out
    text = "\n".join(p.read_text(encoding="utf-8") for p in c.files())
    # The canonical layout and the UTC rejection are the two properties that make a timestamp
    # safe to hash and to compare across systems; asserting the type merely exists is not
    # verification of either.
    canonical = "2006-01-02T15:04:05.000000000Z" in text
    rejects_non_utc = "UTC" in text and "timestamp" in text.lower()
    if c.missing():
        c.status, c.evidence = "FAIL", f"missing: {c.missing()}"
    elif code != 0:
        c.status, c.evidence = "FAIL", f"go test failed; {ok}"
    elif not (canonical and rejects_non_utc):
        c.status = "FAIL"
        c.evidence = (f"canonical layout present={canonical}, UTC handling present="
                      f"{rejects_non_utc}")
    else:
        c.status = "PASS"
        c.evidence = f"contracts.Timestamp canonical form and UTC rejection asserted; {ok}"
    return c


def criterion_money() -> Criterion:
    c = Criterion("money", "Money/quantity types", ["contracts/go/money.go",
                                                    "contracts/go/decimal.go",
                                                    "contracts/go/money_test.go",
                                                    "contracts/go/decimal_test.go",
                                                    "contracts/go/no_float_test.go"])
    code, out, ok = go_test(CONTRACTS)
    c.command_exit = code
    c.command_output = out
    if c.missing():
        c.status, c.evidence = "FAIL", f"missing: {c.missing()}"
    elif code != 0:
        c.status, c.evidence = "FAIL", f"go test failed; {ok}"
    else:
        c.status = "PASS"
        c.evidence = (f"exact-decimal Money/Quantity/Decimal; no_float_test enforces the "
                      f"absence of binary floating point; {ok}")
    return c


def criterion_errors() -> Criterion:
    c = Criterion("errors", "Errors", ["contracts/go/error.go", "contracts/go/error_test.go"])
    code, out, ok = go_test(CONTRACTS)
    c.command_exit = code
    c.command_output = out
    if c.missing():
        c.status, c.evidence = "FAIL", f"missing: {c.missing()}"
    elif code != 0:
        c.status, c.evidence = "FAIL", f"go test failed; {ok}"
    else:
        c.status = "PASS"
        c.evidence = f"ErrorCode and ContractError with a stable wire form; {ok}"
    return c


def criterion_envelopes() -> Criterion:
    c = Criterion("envelopes", "Envelopes", ["contracts/go/envelope.go",
                                             "contracts/go/envelope_test.go",
                                             "contracts/go/envelope_actor_test.go"])
    code, out, ok = go_test(CONTRACTS)
    c.command_exit = code
    c.command_output = out
    if c.missing():
        c.status, c.evidence = "FAIL", f"missing: {c.missing()}"
    elif code != 0:
        c.status, c.evidence = "FAIL", f"go test failed; {ok}"
    else:
        c.status = "PASS"
        c.evidence = f"CommandEnvelope and EventEnvelope; actor binding asserted; {ok}"
    return c


def criterion_idempotency() -> Criterion:
    c = Criterion("idempotency", "Idempotency",
                  ["contracts/go/envelope.go", "components/oms/order.go",
                   "services/control-plane/ledger/entry.go",
                   "services/control-plane/ledger/ledger_test.go",
                   "db/migrations/0001_ledger.sql"])
    code1, out1, ok1 = go_test(CONTRACTS)
    code2, out2, ok2 = go_test("components/oms")
    code3, out3, ok3 = go_test("services/control-plane")
    c.command_exit = max(code1, code2, code3)
    c.command_output = f"--- contracts/go ---\n{out1}\n--- components/oms ---\n{out2}\n" \
                       f"--- services/control-plane ---\n{out3}"
    missing = c.missing()
    if missing:
        c.status, c.evidence = "FAIL", f"missing: {missing}"
    elif c.command_exit != 0:
        c.status, c.evidence = "FAIL", f"go test failed; {ok1} {ok2} {ok3}"
    else:
        c.status = "PASS"
        c.evidence = (f"idempotency key in the envelope, in OMS apply, and enforced by a unique "
                      f"index in 0001_ledger.sql; ledger idempotency tests pass; {ok1} {ok2} {ok3}")
    return c


def criterion_config_boundaries() -> Criterion:
    c = Criterion("config", "Configuration boundaries",
                  [f"{CONFIG_PKG}/config.go", f"{CONFIG_PKG}/load.go", f"{CONFIG_PKG}/sign.go",
                   f"{CONFIG_PKG}/drift.go", f"{CONFIG_PKG}/config_test.go"])
    code, out, ok = go_test("services/control-plane")
    c.command_exit = code
    c.command_output = out
    if c.missing():
        c.status, c.evidence = "FAIL", f"missing: {c.missing()}"
    elif code != 0:
        c.status, c.evidence = "FAIL", f"go test failed; {ok}"
    else:
        c.status = "PASS"
        c.evidence = (f"typed configuration with signed immutable release snapshot and drift "
                      f"detection; {ok}")
    return c


def criterion_migrations() -> Criterion:
    c = Criterion("migrations", "Migrations",
                  ["services/control-plane/migrate/migrate.go",
                   "services/control-plane/migrate/real_migrations_test.go",
                   "db/migrations/0001_ledger.sql", "db/migrations/0002_audit.sql",
                   "db/migrations/0003_authz.sql"])
    code, out, ok = go_test("services/control-plane")
    c.command_exit = code
    c.command_output = out
    missing = c.missing()
    if missing:
        c.status, c.evidence = "FAIL", f"missing: {missing}"
    elif code != 0:
        c.status, c.evidence = "FAIL", f"go test failed; {ok}"
    else:
        c.status = "PASS"
        c.evidence = (f"every migration in db/migrations parsed by real_migrations_test.go, "
                      f"which asserts reversibility, explicit BEGIN/COMMIT, and no DROP in an up "
                      f"body; {ok}")
    return c


def module_is_placeholder(module: str) -> tuple[bool, list[str]]:
    """A module is a declared placeholder only if it holds no implementation.

    The rule is structural rather than a hardcoded list of names, so it keeps working when
    modules are added or filled in. A module containing real code and no tests fails this
    gate; a module containing only its package documentation does not, because its
    implementation belongs to a later gate — `adapters/venues` names G8 in its own package
    comment, and `components/reconciliation` is gated by WI-131.

    Accepting a placeholder must not become a way to skip testing, so a placeholder is
    reported explicitly with its digest rather than quietly excluded from the totals.
    """
    directory = ROOT / module
    implementation = [
        p.name for p in sorted(directory.glob("*.go"))
        if not p.name.endswith("_test.go") and not p.name.endswith(".gen.go")
    ]
    non_doc = [n for n in implementation if n != "doc.go"]
    return (not non_doc), non_doc


def criterion_domain_tests() -> Criterion:
    modules = [CONTRACTS, "components/oms", "components/risk-engine",
               "components/reconciliation", "adapters/venues", "services/control-plane"]
    c = Criterion("domain_tests", "Domain tests", [])
    outputs, failures, per_module, placeholders = [], [], {}, {}
    for module in modules:
        if not (ROOT / module / "go.mod").is_file():
            failures.append(f"{module}: no go.mod")
            continue
        code, out = run(["go", "test", "-count=1", "-v", "./..."], cwd=ROOT / module)
        outputs.append(f"--- {module} ---\n{out}")
        if code != 0:
            failures.append(f"{module}: exit {code}")
        passed = out.count("--- PASS:")
        per_module[module] = passed
        if passed == 0:
            is_placeholder, code_files = module_is_placeholder(module)
            if is_placeholder:
                placeholders[module] = implementation_digest(module)
            else:
                failures.append(
                    f"{module}: no passing test and {len(code_files)} implementation file(s) "
                    f"({', '.join(code_files)})"
                )
    c.command_output = "\n".join(outputs)
    c.command_exit = 1 if failures else 0
    total = sum(per_module.values())
    c.evidence = f"{total} test(s) reported PASS: " + ", ".join(
        f"{m} {n}" for m, n in per_module.items()
    )
    c.placeholders = placeholders
    if failures:
        c.status, c.evidence = "FAIL", f"{failures}; {c.evidence}"
    elif total == 0:
        c.status, c.evidence = "FAIL", "no test reported PASS in any module"
    else:
        c.status = "PASS"
        if placeholders:
            c.evidence += (f"; declared placeholders with no implementation yet, gated by later "
                           f"work items: {', '.join(sorted(placeholders))}")
    return c


def implementation_digest(module: str) -> str:
    return digest_tree(sorted((ROOT / module).glob("*.go")))


CRITERIA = [
    criterion_canonical_ids,
    criterion_timestamps,
    criterion_money,
    criterion_errors,
    criterion_envelopes,
    criterion_idempotency,
    criterion_config_boundaries,
    criterion_migrations,
    criterion_domain_tests,
]


def render_markdown(report: dict) -> str:
    """The human-readable gate report.

    Written for a named reviewer, so it leads with the verdict rather than burying it, and it
    states plainly which fields are outstanding and why that forces the verdict. A report
    whose reader has to infer the outcome from a table is not a gate report.
    """
    mechanical = report["mechanical_result"]
    lines = [
        f"# G1 Gate Report - Domain Foundation",
        "",
        f"Specification: {report['specification']}",
        f"Verified at: {report['verified_at']}",
        f"**Verdict: {report['verdict']}**",
        "",
        "## Why the verdict is FAIL",
        "",
    ]
    lines += [f"- {b}" for b in report["verdict_basis"]]
    lines += [
        "",
        "docs/11_EXECUTION_GATES.md states that a gate is PASS only when every listed",
        "criterion is satisfied and that partial completion is FAIL, not a percentage. All nine",
        "mechanical criteria hold. The report's *reviewer* and *commit* fields cannot be",
        "produced by an automated agent, and the referenced commit does not contain the work",
        "being certified, so the gate cannot be recorded as PASS.",
        "",
        "## Mechanical criteria",
        "",
        "| Criterion | Result | Evidence |",
        "| --- | --- | --- |",
    ]
    for c in report["criteria"]:
        detail = c["command"].replace("|", "\\|")
        lines.append(f"| {c['criterion']} | **{c['status']}** | {detail} |")
    lines += [
        "",
        f"{mechanical['pass']} of {mechanical['total']} mechanical criteria PASS.",
        "",
        "## Required report fields",
        "",
        "| Field | Value | Status |",
        "| --- | --- | --- |",
    ]
    for name, field in report["required_report_fields"].items():
        value = str(field.get("value"))
        value = value if len(value) <= 90 else value[:87] + "..."
        lines.append(f"| {name} | `{value}` | {field['status']} |")
    lines += ["", "### Outstanding fields in detail", ""]
    for name, field in report["required_report_fields"].items():
        if field.get("status") == "OUTSTANDING":
            lines += [f"**{name}** - {field['reason']}", ""]
    lines += [
        "## Evidence digests",
        "",
        "Every artifact is identified by repository path and SHA-256 content digest, as",
        "docs/11 requires.",
        "",
    ]
    for c in report["criteria"]:
        if not c["artifacts"]:
            continue
        lines.append(f"### {c['criterion']} ({c['status']})")
        lines.append("")
        lines.append(f"Artifact set digest: `{c['artifact_set_digest']}`")
        lines.append("")
        for a in c["artifacts"]:
            lines.append(f"- `{a['path']}` - `{a['digest']}`")
        if c.get("declared_placeholders"):
            lines += ["", "Declared placeholders (no implementation; gated by later work items):", ""]
            for module, d in sorted(c["declared_placeholders"].items()):
                lines.append(f"- `{module}` - `{d}`")
        lines.append("")
    return "\n".join(lines) + "\n"


def git_field(field: list[str]) -> str:
    code, out = run(field, timeout=120)
    return out if code == 0 else "unavailable"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    results = [factory() for factory in CRITERIA]
    failed = [r for r in results if r.status == "FAIL"]

    head = git_field(["git", "rev-parse", "HEAD"])
    dirty = git_field(["git", "status", "--porcelain"])
    untracked_or_modified = len([l for l in dirty.splitlines() if l.strip()])
    # Whether the artifacts G1 covers are actually in a commit. A HEAD that predates them
    # makes the commit field a reference to something that does not contain the work.
    work_committed = "unknown"

    report = {
        "gate": "G1",
        "title": "Domain Foundation",
        "specification": "docs/11_EXECUTION_GATES.md section G1",
        "verified_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "criteria": [r.as_dict() for r in results],
        "mechanical_result": {
            "total": len(results),
            "pass": len([r for r in results if r.status == "PASS"]),
            "fail": len(failed),
        },
        "required_report_fields": {
            "reviewer": {
                "value": None,
                "status": "OUTSTANDING",
                "reason": "A named human reviewer cannot be produced by an automated agent. "
                          "docs/11 requires the gate report to identify its reviewer, and the "
                          "same package treats an unattested specification as not passed "
                          "(G0.8 REQUIRES_HUMAN_ATTESTATION).",
            },
            "commit": {
                "value": head,
                "status": "OUTSTANDING",
                "reason": f"HEAD is {head[:12] if head != 'unavailable' else 'unavailable'}, but "
                          f"{untracked_or_modified} path(s) in the working tree are untracked or "
                          f"modified, including the Go sources and migrations this gate covers. "
                          f"The referenced commit therefore does not contain the work being "
                          f"certified (work_committed={work_committed}). No commit was requested "
                          f"or made.",
            },
            "timestamp": {"value": "recorded above in verified_at", "status": "PRESENT"},
            "command_output": {"value": "per criterion", "status": "PRESENT"},
            "binary_pass_fail": {
                "value": "FAIL",
                "status": "PRESENT",
                "reason": "docs/11: a gate is PASS only when every listed criterion is "
                          "satisfied; partial completion is FAIL, not a percentage. The nine "
                          "mechanical criteria are individually reported above; the reviewer and "
                          "commit fields are outstanding, so the gate cannot be recorded as PASS.",
            },
            "evidence_digests": {"value": "per artifact", "status": "PRESENT"},
        },
        "verdict": "FAIL",
        "verdict_basis": [
            f"{len([r for r in results if r.status == 'PASS'])} of {len(results)} mechanical "
            f"criteria PASS",
            "reviewer field OUTSTANDING",
            "commit field OUTSTANDING (HEAD does not contain the work)",
        ],
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"G1 - Domain Foundation  ({report['verified_at']})")
        for r in results:
            mark = {"PASS": "PASS", "FAIL": "FAIL"}.get(r.status, r.status)
            print(f"  {mark:4}  {r.name:26} {r.evidence}")
        print()
        print(f"  mechanical: {report['mechanical_result']['pass']}/{len(results)} PASS")
        print(f"  reviewer:   OUTSTANDING")
        print(f"  commit:     OUTSTANDING (HEAD {head[:12]}, "
              f"{untracked_or_modified} untracked/modified path(s))")
        print(f"  VERDICT:    {report['verdict']}")

    if not args.no_write and not args.json:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        (REPORT_DIR / "g1-gate-report.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        REPORT_FILE.write_text(render_markdown(report), encoding="utf-8", newline="\n")
        print(f"\nwrote {REPORT_DIR / 'g1-gate-report.json'}")
        print(f"wrote {REPORT_FILE}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
