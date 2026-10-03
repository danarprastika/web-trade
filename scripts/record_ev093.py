"""Record WI-192 and EV-093: the Python workers' typecheck step could never pass.

Found by running the CI battery against this tree rather than by reading the workflow. Both
workers declare the same relative paths for the same purpose - `pythonpath` for pytest and
`mypy_path` for mypy - and the pyproject.toml comment asserted the two therefore resolve the
package from the same place. They do not: pytest resolves `pythonpath` relative to rootdir, mypy
resolves `mypy_path` relative to the current working directory, and the workflow invoked mypy
from the repository root.

This file also corrects the comment in workers/backtest/pyproject.toml, which stated the false
claim in the place a reader would consult it.

No attestation is asserted anywhere in this file. G0.8 remains REQUIRES_HUMAN_ATTESTATION.

Idempotent.
"""

import io
import json
import pathlib

BRAIN = pathlib.Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
ITEMS = BRAIN / "work-items.json"
EVIDENCE = BRAIN / "evidence.jsonl"

STAMP = "2026-10-03T21:35:00Z"

ARTIFACTS = [
    ".github/workflows/ci.yml",
    "workers/backtest/pyproject.toml",
    "tests/ci/test_ci_workflow.py",
    "scripts/record_ev093.py",
    ".kilo/ecc/project-brain/evidence.jsonl",
    ".kilo/ecc/project-brain/work-items.json",
]

WI_192 = {
    "id": "WI-192",
    "phase": 1,
    "title": (
        "The Python workers' typecheck step could never pass: mypy was invoked from a directory "
        "where the mypy_path its own configuration declares does not exist"
    ),
    "status": "COMPLETED",
    "priority": "high",
    "acceptance_criteria": [
        "Every mypy invocation in the workflow runs from a directory in which the mypy_path of the "
        "configuration it will read resolves to a real directory",
        "The lint step executes to completion on this host, with both workers reporting success",
        "The original wiring is observed failing under the same shell, so the change is shown to be "
        "load-bearing rather than cosmetic",
        "The check reads each worker's declared configuration rather than pattern-matching the "
        "command, and accepts a worker that declares no mypy_path",
        "The comment in workers/backtest/pyproject.toml no longer claims the two tools resolve the "
        "package from the same place",
    ],
    "source": (
        "Running the CI battery locally against this tree for the first time, rather than "
        "reasoning about the workflow. The step is 'lint python workers', and nothing else in the "
        "repository executes it."
    ),
    "reproduction": (
        "From the repository root, `python -m mypy workers/backtest/src` exits 1 with four "
        "import-not-found errors in harness.py and artifacts.py, naming "
        "webtrade_research.dataset, webtrade_research.canonical and "
        "webtrade_research.content_address. The same command from workers/backtest exits 0. "
        "workers/backtest/pyproject.toml declares `mypy_path = [\"src\", \"../research/src\"]`, and "
        "from the root those entries name `<root>/src` and `<root>/../research/src`, neither of "
        "which exists. Installing webtrade-research and webtrade-backtest into site-packages does "
        "not change the root-relative result, so the failure is not a missing install."
    ),
    "notes": (
        "The trap is that the two configurations look identical and mean different places. "
        "pytest resolves `pythonpath` relative to rootdir, which is the directory holding the "
        "pyproject.toml, so `python -m pytest workers/backtest/tests -q` from the repository root "
        "has always worked. mypy resolves `mypy_path` relative to the current working directory. "
        "The comment above mypy_path said the entry 'mirrors the pytest pythonpath above so the "
        "two tools resolve the package from the same place', and that sentence was the defect: it "
        "was the justification for a configuration that does not work from where the workflow "
        "called it. It is corrected in place, where a reader would consult it.\n\n"
        "Installing the package was the hypothesis that had to be eliminated rather than assumed. "
        "If site-packages held a typed webtrade_research, mypy would have resolved the import "
        "without help from mypy_path and the step would have passed. It does not: the built wheel "
        "carries no py.typed marker, so there is no typed distribution to fall back on, and the "
        "root-relative invocation still reports the same four errors after installation.\n\n"
        "The new check reads the configuration instead of matching the shape of the command. It "
        "finds every mypy invocation in the workflow, establishes the working directory from either "
        "a `cd` in the same command or the step's `working-directory:`, locates the pyproject.toml "
        "above the target that declares [tool.mypy], and verifies each declared path resolves from "
        "that working directory. A third worker is therefore covered by the rule rather than by a "
        "new assertion, and a worker that declares no mypy_path is correctly accepted - "
        "workers/research declares none, because it imports nothing from the other worker, so a "
        "root-relative invocation is right for it. Demanding a `cd` from every worker would have "
        "rejected that valid configuration.\n\n"
        "One control was written, run, and discarded because its premise was false: "
        "`(cd workers/research && python -m mypy ../backtest/src)` reads like a mistake and is not "
        "one. mypy_path resolves against the working directory, and from workers/research both "
        "entries exist, so the invocation succeeds. Asserting it fails would have encoded a "
        "misunderstanding of the tool in order to make the rule look thorough. The control that "
        "replaced it - descending one level too far, into workers/backtest/src, where `src` then "
        "means `workers/backtest/src/src` - is a real failure a rule that merely checked for the "
        "presence of a `cd` would wave through."
    ),
    "dependencies": ["WI-182"],
    "evidence_ref": ["EV-093"],
}

EV_093 = {
    "evidence_id": "EV-093",
    "work_item": "WI-192",
    "claim": (
        "The Python workers' typecheck step runs, and every mypy invocation in the workflow is "
        "checked against the mypy_path of the configuration it will actually read."
    ),
    "method": (
        "Both invocations were executed from the repository root and from the worker directory, in "
        "the same shell, before anything was changed. The hypothesis that a missing install was the "
        "cause was eliminated by installing both local packages and re-measuring. The corrected "
        "step was then executed verbatim under Git Bash, as a single `set -euo pipefail` block, and "
        "the original block was executed verbatim the same way as the negative control. The new "
        "assertion was checked by mutation against parsed copies of the workflow rather than by "
        "editing ci.yml and restoring it, so no test can leave the real workflow modified."
    ),
    "result": (
        "Before: `python -m mypy workers/backtest/src` from the repository root exits 1 with four "
        "import-not-found errors; after installing webtrade-research and webtrade-backtest into "
        "site-packages it still exits 1 with the same four errors. From workers/backtest the same "
        "command exits 0. The corrected step, run verbatim under Git Bash, exits 0: ruff reports "
        "'All checks passed!', research reports 'Success: no issues found in 5 source files', "
        "backtest reports 'Success: no issues found in 3 source files'. The original block, run "
        "verbatim in the same shell, still reports the four errors. tests/ci passes, 177 tests, up "
        "from 172. All four controls behave as required: the root-relative wiring and the "
        "cd-one-level-too-far wiring each produce a problem naming the unresolved mypy_path entry, "
        "removing the invocation fails closed rather than reporting nothing checked, and the "
        "positive control - a root-relative invocation of the worker that declares no mypy_path - "
        "is accepted."
    ),
    "defect_found_and_fixed": (
        "1. `.github/workflows/ci.yml` ran `python -m mypy workers/backtest/src` from the "
        "repository root, where the mypy_path its configuration declares resolves to nothing. Each "
        "worker is now invoked from its own directory in a subshell, so neither cd leaks into the "
        "next line and a cd that fails fails the step. 2. The comment above mypy_path in "
        "workers/backtest/pyproject.toml claimed the entry mirrors the pytest pythonpath 'so the "
        "two tools resolve the package from the same place'. They resolve from different "
        "directories; the comment is corrected in place with the measured numbers. 3. Nothing "
        "executed this step, so nothing reported it: "
        "test_every_worker_typecheck_runs_where_its_configured_paths_resolve now reads every "
        "mypy invocation in the workflow, resolves the configuration it will load, and verifies "
        "each configured path against the invocation's working directory."
    ),
    "significance": (
        "This is the repository's own recurring shape with a new disguise. Every previous instance "
        "was a gate that passed having checked nothing; this one is a gate that could not pass and "
        "had never been run. The two look different in the run list and are equally invisible: one "
        "is green, the other is simply absent, and neither produces a finding to review. The "
        "pyproject.toml comment is the part worth keeping - a false statement about tool "
        "behaviour, sitting directly above the configuration it misdescribes, is the kind of "
        "comment that survives every review because it explains itself convincingly."
    ),
    "caveats": (
        "The step was executed on Windows under Git Bash, not on an ubuntu runner. The shell "
        "wrapper is the workflow's own `set -euo pipefail` block and both mypy invocations are "
        "platform-independent, but the runner's own execution remains unobserved - gh is installed "
        "and unauthenticated for this repository, as EV-091 records.\n\n"
        "NOT CHANGED, and deliberately: webtrade-research ships no py.typed marker, so an installed "
        "copy is invisible to mypy even when the invocation is correct. That is a packaging gap "
        "rather than a broken gate, it does not affect this step once the working directory is "
        "right, and fixing it would change what mypy resolves - the source tree today, a "
        "site-packages copy tomorrow. It is recorded rather than actioned.\n\n"
        "WI-141 records 'ruff and mypy strict clean on both workers' among its verified partial "
        "results. That claim was true of a correctly-invoked run and remains true; what it did not "
        "cover was whether the workflow could reproduce it."
    ),
    "exception": (
        "No exception. No step was skipped, no check weakened, and no configuration weakened to "
        "reach a green result. The fix is the invocation, and the assertion that guards it."
    ),
    "artifacts": ARTIFACTS,
    "supersedes": [],
}


def main() -> bool:
    doc = json.loads(ITEMS.read_text(encoding="utf-8"))
    items = doc["items"]
    by_id = {i["id"]: i for i in items}

    changed = False
    existing = by_id.get(WI_192["id"])
    if existing is None:
        items.append(WI_192)
        changed = True
        print(f"recorded {WI_192['id']}")
    elif existing != WI_192:
        items[items.index(existing)] = WI_192
        changed = True
        print(f"updated {WI_192['id']}")
    else:
        print(f"unchanged: {WI_192['id']}")

    if changed:
        ITEMS.write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )

    recorded = set()
    if EVIDENCE.exists():
        for line in EVIDENCE.read_text(encoding="utf-8").splitlines():
            if line.strip():
                recorded.add(json.loads(line).get("evidence_id"))

    appended = []
    with io.open(EVIDENCE, "a", encoding="utf-8", newline="\n") as handle:
        for record in (EV_093,):
            if record["evidence_id"] in recorded:
                continue
            handle.write(
                json.dumps(
                    {
                        "schema": "ecc.project-brain/evidence/v7",
                        "evidence_id": record["evidence_id"],
                        "recorded_at": STAMP,
                        "recorded_by": "team-lead",
                        "work_item": record["work_item"],
                        "claim": record["claim"],
                        "status": "RESOLVED",
                        "method": record["method"],
                        "result": record["result"],
                        "defect_found_and_fixed": record["defect_found_and_fixed"],
                        "significance": record["significance"],
                        "caveats": record["caveats"],
                        "exception": record["exception"],
                        "artifacts": record["artifacts"],
                        "supersedes": record["supersedes"],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            appended.append(record["evidence_id"])

    print(f"recorded {', '.join(appended)}" if appended else "evidence already recorded")
    return changed


if __name__ == "__main__":
    main()
