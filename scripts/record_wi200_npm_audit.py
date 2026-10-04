"""Record WI-200 and EV-101: the accepted npm advisory, as ledger entries rather than a comment.

The justification for accepting GHSA-vfj7-8cjw-p6xm lives in scripts/check_npm_audit.py, where the gate
reads it. That is the right place for the gate to read it from and the wrong place for it to live
only: a reviewer reading the project brain - which is where the risk register is - would find no
record that this repository ships a knowingly unfixed high-severity advisory, and that omission is
the kind this repository keeps recording.

So the risk is recorded as EV-101 against WI-200, in the form a reader of the ledger can act on: what
is accepted, what it would take to stop accepting it, and what is measured on every run to keep the
acceptance honest. The exit conditions are enumerated in the work item's acceptance criteria, because
an accepted risk with no stated exit condition is a permanent one wearing a temporary label.

`evidence_ref` is a list of evidence identifiers, and the brain gate enforces that: it reads each
entry as an id and reports an unknown one. A sentence written there is not a soft warning, it is 84
separate failures - which is the gate working, and worth having met.

Idempotent.
"""

import json
import pathlib

BRAIN = pathlib.Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
STORE = BRAIN / "work-items.json"
EVIDENCE = BRAIN / "evidence.jsonl"

EVIDENCE_RECORD = {
    "schema": "ecc.project-brain/evidence/v7",
    "evidence_id": "EV-101",
    "recorded_at": "2026-10-04T15:40:00Z",
    "recorded_by": "team-lead",
    "work_item": "WI-200",
    "claim": (
        "The one high-severity npm advisory on this tree has no available fix, and it is accepted "
        "under an exception that is keyed to the advisory, expires when the advisory does, and is "
        "void the moment the finding could reach production"
    ),
    "status": "VERIFIED",
    "method": (
        "Read from GitHub Actions rather than from the local suite: the dependency + license scan "
        "job's `npm audit` step was failing while every local gate was green, which is only visible "
        "by asking the runner. Reproduced with `npm audit --json` in apps/web, and the report's own "
        "`via` and `effects` fields used to derive the dependency chain rather than reading it off "
        "the tree. The absence of a fix was measured, not assumed: `npm view braces dist-tags` "
        "returns latest 3.0.3 with no beta or next tag, and `npm view fast-glob@latest dependencies` "
        "shows 3.3.3, which is newer than the installed 3.3.1, still depending on micromatch ^4.0.8. "
        "Exposure was measured rather than assumed too: `npm audit --omit=dev --audit-level=high` "
        "reports `found 0 vulnerabilities` and exits 0. Nine controls then drive the gate's "
        "`--audit-json` seam against synthetic reports, and one runs the script as the workflow "
        "invokes it, so a gate that is wired but unrunnable cannot pass."
    ),
    "result": (
        "The audit reports 5 high entries and they are 1 advisory plus 4 carriers: "
        "GHSA-vfj7-8cjw-p6xm against braces, reached as eslint-config-next -> "
        "@next/eslint-plugin-next -> fast-glob -> micromatch -> braces. `python scripts/"
        "check_npm_audit.py` reports `1 blocking advisory/advisories in the full tree, 1 excepted, "
        "0 in the production tree` and exits 0, printing the exception's reach, impact and "
        "no-fix-available justification on every run. A second advisory planted in the same braces "
        "entry is reported as unmatched. Removing the advisory so the exception matches nothing is "
        "reported as a stale acceptance. A finding placed in the --omit=dev report is reported as "
        "voiding every dev-only exception. A report with no `vulnerabilities` key exits non-zero "
        "rather than passing as an empty finding set. 10 controls pass."
    ),
    "defect_found_and_fixed": (
        "1. `npm audit --audit-level=high` blocked the dependency-scan job on every run and could "
        "not be satisfied, because no version of braces outside the advisory's range exists and npm's "
        "only computable remediation is a --force downgrade of eslint-config-next from 16.3.6 to "
        "14.2.35. Replaced by a gate that enumerates the acceptance instead of silencing the step.\n"
        "2. The obvious exception - by package name, or by the count of 5 - would have kept passing "
        "after a second and different advisory arrived in braces, and would have needed a second "
        "line to balance the arithmetic. Keyed on the GHSA identifier, so one advisory is one "
        "finding and one line.\n"
        "3. An exception that matched nothing would have sat there unnoticed once upstream fixed the "
        "advisory. An unmatched exception is now itself a failure.\n"
        "4. The justification 'this never ships' would have remained true in a comment after the "
        "package moved into the production tree. The --omit=dev scan is now re-measured every run "
        "and its failure voids the exception.\n"
        "5. `subprocess.run(['npm', ...])` raises FileNotFoundError on Windows, where the "
        "executable on PATH is npm.cmd and CreateProcess only appends .exe. Resolved through "
        "shutil.which, which consults PATHEXT."
    ),
    "significance": (
        "The shape is the repository's recurring one, at its ninth instance, and this time it was "
        "reached from a security angle rather than a CI one: a check that cannot be satisfied, where "
        "the three available responses are to weaken the check, to regress the dependency, or to "
        "bound the finding. Only the third keeps the gate able to fail tomorrow - because an "
        "exception keyed to a GHSA id rejects the next advisory in the same package, and because the "
        "condition the acceptance rests on is re-measured rather than remembered. The alternative "
        "that was available and would have looked responsible is `continue-on-error` on the step, "
        "which converts an unfixable finding into an unowned one."
    ),
    "caveats": (
        "The advisory is live and the acceptance is not a fix. braces 3.0.3 remains installed in the "
        "development tree and remains flagged by npm; nothing here changes that, and the gate passes "
        "while the finding stands.\n\n"
        "The production-tree cleanliness that justifies it was measured once, on this tree, with the "
        "lockfile as committed. The gate re-measures it on every run in CI, so a future change that "
        "moves the package into production fails the build rather than the comment.\n\n"
        "The severity of the acceptance depends on the input being trusted. The vulnerable code path "
        "is a linter expanding glob patterns over this repository's own files at build time. If a "
        "build ever processed untrusted glob input, that reasoning would no longer hold and this "
        "exception would need to be re-argued rather than re-run.\n\n"
        "Not verified: whether GitHub Actions reports this gate green. The local run is observed; the "
        "runner is observed only through run and job conclusions, because job logs require a token "
        "this host does not have."
    ),
    "exception": (
        "One, and it is the subject of this record: GHSA-vfj7-8cjw-p6xm against braces in the "
        "development dependency tree. Nothing is skipped or weakened beyond it. Any other high or "
        "critical advisory blocks, including one in the same package; an exception that no longer "
        "matches blocks; and a finding in the production tree blocks regardless of any exception."
    ),
    "artifacts": [
        "scripts/check_npm_audit.py",
        "tests/ci/test_npm_audit_gate.py",
        "scripts/record_wi200_npm_audit.py",
        ".github/workflows/ci.yml",
        ".kilo/ecc/project-brain/evidence.jsonl",
        ".kilo/ecc/project-brain/work-items.json",
    ],
    "supersedes": [],
}

ITEM = {
    "id": "WI-200",
    "phase": 3,
    "title": (
        "The dependency scan blocked on a high npm advisory with no available fix, and the only "
        "remediation npm could compute was a two-major-version downgrade of the lint configuration"
    ),
    "status": "COMPLETED",
    "priority": "high",
    "acceptance_criteria": [
        "The accepted finding is keyed to its GHSA identifier, so a second and different advisory in "
        "the same package is an unmatched finding and still blocks",
        "An exception that matches no advisory is itself a failure, so an acceptance cannot outlive "
        "the advisory it was granted for",
        "`npm audit --omit=dev` reports zero blocking advisories, and the gate re-measures it on "
        "every run rather than asserting it, so an acceptance justified by 'this never ships' "
        "stops holding on the run where it would ship",
        "A report shape the gate cannot read fails rather than passing as an empty finding set",
        "Every one of those properties has a control that fails against the implementation without "
        "it, and the workflow runs the gate rather than the bare npm command",
        "The exit conditions are recorded: braces publishing a release covering the advisory, "
        "micromatch or fast-glob dropping their braces dependency, Next shipping an "
        "eslint-config-next without the plugin's fast-glob chain, or the --omit=dev scan ceasing to "
        "be clean"
    ],
    "source": (
        "Reading GitHub Actions directly rather than trusting the local suite, which is what "
        "revealed the dependency + license scan job failing at its npm audit step while every "
        "local gate was green. CI has not had a green run since 299f2e8 on 2026-07-27."
    ),
    "reproduction": (
        "cd apps/web && npm audit --audit-level=high. Reports 5 high findings and exits 1. The five "
        "entries are one advisory plus its four carrier packages: GHSA-vfj7-8cjw-p6xm against "
        "braces, reached as eslint-config-next -> @next/eslint-plugin-next -> fast-glob -> "
        "micromatch -> braces. `npm audit --omit=dev --audit-level=high` reports found 0 "
        "vulnerabilities and exits 0, so the exposure is the lint toolchain only."
    ),
    "evidence_ref": ["EV-101"],
    "notes": (
        "Accepted deliberately, because there is no alternative that is not worse. braces@3.0.3 is "
        "the newest published version and `npm view braces dist-tags` shows no beta or next tag, so "
        "the advisory's range (<=3.0.3) covers every version that exists. fast-glob has a newer "
        "release than the installed one - 3.3.3 against 3.3.1 - and still depends on micromatch "
        "^4.0.8, so moving up the chain does not clear it. npm's only computable remediation is a "
        "--force downgrade of eslint-config-next from 16.3.6 to 14.2.35, which would trade a "
        "build-time advisory in a linter for a two-major-version regression in the framework's own "
        "lint configuration. Replacing eslint-config-next with a hand-written config would clear "
        "the chain and discard the Next-specific rules the config exists to supply. Silencing the "
        "job or marking it continue-on-error is the outcome every one of these exists to prevent. "
        "Impact if realised is CWE-674 stack exhaustion through deeply nested glob patterns, where "
        "the patterns come from the linter expanding globs over this repository's own files - "
        "trusted input at build time, with no runtime path to the package at all. This item stays "
        "COMPLETED because the gate that bounds the acceptance is built and controlled; the risk it "
        "records is live and will stay live until one of the exit conditions is met, which is "
        "monitored by the --omit=dev check rather than by a human remembering."
    ),
    # Deliberately empty. WI-200 was found while working on WI-107, and the two share a subject, but
    # nothing about WI-200 waits for WI-107: the gate is built, controlled and passing on this tree,
    # and the only thing still outstanding is whether the runner agrees. Declaring the dependency
    # would have been the tidier-looking answer and would have been false - the brain gate caught it,
    # which is the gate working, and the alternative it offered was a dependency_exemptions entry
    # justifying a dependency that does not exist.
    "dependencies": [],
}


def main() -> bool:
    changed = False

    raw = EVIDENCE.read_text(encoding="utf-8")
    lines = [line for line in raw.splitlines() if line.strip()]
    # Appended as one line rather than by re-serialising the file. The existing records are written in
    # insertion order, not sorted, so rewriting them through json.dumps would reorder every key in
    # all 100 records and turn a one-line addition into a whole-file diff that hides the addition.
    if not any(json.loads(line).get("evidence_id") == "EV-101" for line in lines):
        payload = json.dumps(EVIDENCE_RECORD, ensure_ascii=False) + "\n"
        EVIDENCE.write_text(
            raw if raw.endswith("\n") else raw + "\n", encoding="utf-8", newline="\n"
        )
        with EVIDENCE.open("a", encoding="utf-8", newline="") as handle:
            handle.write(payload)
        print("recorded EV-101")
        changed = True

    doc = json.loads(STORE.read_text(encoding="utf-8"))
    items = doc["items"]
    index = next((i for i, item in enumerate(items) if item["id"] == "WI-200"), None)
    if index is None:
        items.append(ITEM)
        changed = True
        print("recorded WI-200")
    elif items[index] != ITEM:
        items[index] = ITEM
        changed = True
        print("updated WI-200")

    if changed:
        STORE.write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
    if not changed:
        print("unchanged: EV-101 and WI-200")
    return changed


if __name__ == "__main__":
    main()