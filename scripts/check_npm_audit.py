"""Fail closed on high and critical npm advisories, with one enumerated exception.

`npm audit --audit-level=high` blocks on high and critical findings, which is the docs/06 target. On
this tree it blocks, and it cannot be satisfied: the sole advisory is GHSA-vfj7-8cjw-p6xm against
`braces`, `braces@3.0.3` is the newest release that exists, there is no beta or next tag to move to,
and `fast-glob@3.3.3` - newer than the 3.3.1 installed here - still depends on `micromatch ^4.0.8`,
which still depends on `braces`. So the only fix npm can offer is `npm audit fix --force`, which it
describes accurately: it downgrades `eslint-config-next` from 16.3.6 to 14.2.35. Taking it would
trade a build-time advisory in a linter for a two-major-version regression in the framework's own
lint configuration, which is a worse outcome than the thing being avoided.

That leaves three honest options and one dishonest one. Silencing the job, or marking it
continue-on-error, is the dishonest one and is what this gate exists to prevent. Upgrading is
impossible, as measured above. Replacing `eslint-config-next` with a hand-written config would clear
the chain but discard the Next-specific rules that config exists to supply, which is a coverage loss
bought with a security label on it. So the advisory is accepted, enumerated, and bounded instead.

Four properties keep that from being a suppression in disguise.

It is keyed on the advisory, not on the package or the severity count. npm reports five high entries
for one advisory, because it lists the four carrier packages alongside the one that carries it. An
exception written as "braces is fine" or "5 highs are fine" would keep passing after a second,
different advisory arrived in the same package, or after the count changed for an unrelated reason.
Keying on the GHSA identifier means a new advisory in the same package is a new, unmatched finding.

It is exact in both directions. An unlisted advisory fails. So does an exception that matched nothing,
because an exception nobody has looked at for two releases is a permission that outlived its
justification, and the honest moment to notice is while it is still visible in a diff.

Its justification is measured rather than asserted. The reason this advisory is acceptable is that it
is reachable only from the lint toolchain - production dependencies are clean. So the gate runs
`npm audit --omit=dev` and requires zero blocking advisories there. The exception holds only while
the thing that justifies it is true; if `braces` ever moves into the production tree, the premise
fails and the gate fails with it, instead of the justification remaining true forever in a comment.

The chain is recorded so the next reader does not have to rediscover it. It is
eslint-config-next -> @next/eslint-plugin-next -> fast-glob -> micromatch -> braces, and every link
is verified by npm's own `via` and `effects` rather than by inspection.

Revisit when any of these becomes false: `braces` publishes a release covering `GHSA-vfj7-8cjw-p6xm`;
`micromatch` or `fast-glob` drops its `braces` dependency; Next ships an `eslint-config-next` without
the plugin's `fast-glob` chain; or the `--omit=dev` scan stops being clean, which fails the gate
rather than requiring a human to notice.

Idempotent and read-only: it scans, it never installs, upgrades, or edits.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"

# docs/06: critical and high block. Moderate, low and informational are reported by the monthly
# security review and must not fail this gate, or the severity ladder stops meaning anything.
BLOCKING_SEVERITIES = frozenset({"high", "critical"})

# An advisory, identified by its GHSA identifier rather than by package name or by how many packages
# npm happens to list for it. One advisory produces five entries in `vulnerabilities` and one line
# here, which is the correct ratio: five lines would excuse whatever else those packages carry.
EXCEPTIONS: tuple[dict[str, str], ...] = (
    {
        "package": "braces",
        "advisory": "GHSA-vfj7-8cjw-p6xm",
        "severity": "high",
        "chain": (
            "eslint-config-next -> @next/eslint-plugin-next -> fast-glob -> micromatch -> braces"
        ),
        "reach": (
            "development only. Reached from @webtrade/web devDependencies through eslint-config-next, "
            "so it is present when the linter runs and absent from anything the application serves. "
            "`npm audit --omit=dev` reports 0 vulnerabilities on this tree, and this gate requires "
            "that to stay true rather than taking it on trust."
        ),
        "impact": (
            "CWE-674, stack exhaustion through deeply nested glob patterns. The patterns come from "
            "the linter expanding glob arguments over this repository's own files, which are trusted "
            "input at build time. There is no untrusted path to them at runtime, because there is no "
            "runtime path to this package at all."
        ),
        "no_fix_available": (
            "braces@3.0.3 is the latest published version and there is no beta or next tag, so the "
            "advisory's range (<=3.0.3) covers every version that exists. Verified rather than "
            "assumed: `npm view braces dist-tags` returns latest 3.0.3 only; `npm view "
            "fast-glob@latest dependencies` shows 3.3.3 still depending on micromatch ^4.0.8. The "
            "only remediation npm can compute is a --force downgrade of eslint-config-next to "
            "14.2.35, which is why this is an exception rather than an upgrade."
        ),
    },
)


def run_audit(extra: list[str]) -> dict:
    """One `npm audit --json`, as a dict.

    `--audit-level` is deliberately not passed: it changes the exit code, not the JSON, and this
    gate decides for itself what blocks. npm exits non-zero whenever it finds anything, so the exit
    code is not an error signal here and is ignored - reading it as one would make a clean tree look
    like a failed command.
    """
    # Resolved rather than run as a bare "npm". On Windows the executable on PATH is npm.cmd, and
    # CreateProcess only appends .exe, so a bare name raises FileNotFoundError on a machine where npm
    # is installed and working. shutil.which consults PATHEXT, so this finds it on both platforms -
    # the same reason check_workflow_bash.py resolves bash rather than assuming it.
    npm = shutil.which("npm")
    if npm is None:
        raise SystemExit(
            "npm is not on PATH, so no audit could be run. Refusing to pass: a gate that cannot "
            "look must not report that there is nothing to find."
        )
    result = subprocess.run(
        [npm, "audit", "--json", *extra],
        cwd=WEB,
        capture_output=True,
        text=True,
        timeout=600,
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as err:
        raise SystemExit(
            f"npm audit did not produce JSON ({err}). Its output was:\n{result.stdout[:2000]}"
        ) from err


def advisories(report: dict) -> dict[tuple[str, str], dict]:
    """Every blocking advisory in a report, keyed by (advisory id, package).

    Keyed on the advisory rather than on the package because npm lists the carriers too: the five
    entries on this tree are one advisory plus four packages that depend on it. A `via` that is a
    string names another vulnerable package rather than an advisory, so those are skipped here and
    resolved into the chain below.

    Falls back to the report's own severity counts when `vulnerabilities` is absent, so a change in
    npm's report shape produces a loud failure naming a shape this gate does not understand, rather
    than a silent pass over an empty set.
    """
    found: dict[tuple[str, str], dict] = {}
    for package, entry in (report.get("vulnerabilities") or {}).items():
        for via in entry.get("via") or []:
            if not isinstance(via, dict):
                continue
            if str(via.get("severity", "")).lower() not in BLOCKING_SEVERITIES:
                continue
            identifier = str(via.get("url", "")).rsplit("/", 1)[-1]
            if not identifier:
                continue
            found[(identifier, str(via.get("name") or package))] = via
    if not found and report.get("vulnerabilities") is None:
        counts = (report.get("metadata") or {}).get("vulnerabilities") or {}
        blocking = {name: int(counts.get(name, 0)) for name in BLOCKING_SEVERITIES}
        raise SystemExit(
            "npm audit reported no `vulnerabilities` key, so this gate cannot tell an empty "
            f"finding set from a report shape it does not understand. Severity counts: {blocking}. "
            "Refusing to pass on a report this gate could not read."
        )
    return found


def carrier_chain(report: dict, package: str) -> list[str]:
    """Packages that pull `package` in, nearest first, read from npm's own links.

    `via` strings and `effects` are npm's statement of the dependency edges, so the chain printed on
    a failure is the one npm computed rather than one re-derived by inspection.
    """
    chain = [package]
    seen = {package}
    while True:
        parents = sorted(
            name
            for name, entry in (report.get("vulnerabilities") or {}).items()
            if name not in seen and _depends_on(entry, package)
        )
        if not parents:
            return chain
        package = parents[0]
        seen.add(package)
        chain.append(package)


def _depends_on(entry: dict, package: str) -> bool:
    """Whether npm says this entry pulls `package` in.

    Two shapes carry that statement and they are alternatives, not alternatives to each other's
    absence: `via` holds a bare string when the finding is inherited from another vulnerable package
    rather than raised against this one, and `effects` names the packages a finding here propagates
    to. Either can be the only one present, so both are consulted.
    """
    via_strings = [via for via in (entry.get("via") or []) if isinstance(via, str)]
    return package in via_strings or package in (entry.get("effects") or [])


def check(report: dict, production: dict, exceptions: tuple[dict[str, str], ...]) -> list[str]:
    """Every reason this audit should not pass. Empty means it passes."""
    problems: list[str] = []

    allowed = {(item["advisory"], item["package"]) for item in exceptions}
    found = advisories(report)
    present = set(found)

    for key in sorted(present - allowed):
        advisory = found[key]
        chain = " -> ".join(carrier_chain(report, key[1]))
        problems.append(
            f"{key[0]} affects {key[1]} (severity {advisory.get('severity')}), reached through "
            f"{chain}. No exception covers it, and docs/06 makes high and critical findings "
            f"blocking. Advisory: {advisory.get('url')}"
        )

    for key in sorted(allowed - present):
        problems.append(
            f"the exception for {key[0]} / {key[1]} matched nothing in this audit. Either the "
            "advisory has been fixed upstream, the dependency moved, or the exception has rotted. "
            "Remove it in the same commit that removes its cause, so it cannot outlive its "
            "justification."
        )

    # The premise every dev-only exception rests on. Checked rather than believed: a finding moving
    # from the dev tree into the production tree must invalidate the exception automatically, at the
    # moment it happens, rather than waiting for a reviewer to re-read a comment.
    production_found = advisories(production)
    for key in sorted(production_found):
        advisory = production_found[key]
        problems.append(
            f"{key[0]} affects {key[1]} in the PRODUCTION dependency tree (severity "
            f"{advisory.get('severity')}). Every dev-only exception in this file is void from this "
            "point: the justification was that nothing shipped reaches the vulnerable code, and that "
            f"is no longer true. Advisory: {advisory.get('url')}"
        )

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--audit-json",
        type=Path,
        help="read the full-tree audit report from this file instead of running npm. The seam the "
        "tests drive, so a control can state a condition without a network or a registry.",
    )
    parser.add_argument(
        "--production-json",
        type=Path,
        help="read the --omit=dev audit report from this file instead of running npm.",
    )
    args = parser.parse_args()

    report = (
        json.loads(args.audit_json.read_text(encoding="utf-8-sig"))
        if args.audit_json
        else run_audit([])
    )
    production = (
        json.loads(args.production_json.read_text(encoding="utf-8-sig"))
        if args.production_json
        else run_audit(["--omit=dev"])
    )

    problems = check(report, production, EXCEPTIONS)
    found = advisories(report)
    allowed = {(item["advisory"], item["package"]) for item in EXCEPTIONS}

    for item in EXCEPTIONS:
        key = (item["advisory"], item["package"])
        if key not in found:
            continue
        print(f"  [excepted] {item['advisory']} / {item['package']} ({item['severity']})")
        print(f"             chain: {item['chain']}")
        print(f"             reach: {item['reach']}")
        print(f"             impact: {item['impact']}")
        print(f"             no fix available: {item['no_fix_available']}")

    prod = advisories(production)
    print()
    print(
        f"npm audit gate: {len(found)} blocking advisory/advisories in the full tree, "
        f"{len(allowed)} excepted, {len(prod)} in the production tree"
    )
    if prod:
        print(f"  [ok]   production tree carries {len(prod)} of them; the dev-only exceptions are void")

    if problems:
        print()
        for problem in problems:
            print(f"  [FAIL] {problem}")
        print(f"::error::npm audit gate failed with {len(problems)} problem(s)")
        return 1

    print("  [ok]   production tree is clean, so every dev-only exception still holds")
    print("  [ok]   every blocking advisory in the full tree is enumerated and justified above")
    return 0


if __name__ == "__main__":
    sys.exit(main())