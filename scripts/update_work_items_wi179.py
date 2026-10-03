"""Record WI-179 and WI-180: two gates whose own comments described controls that did not exist.

Neither finding is new behaviour in the repository's runtime; both are gates that could report
success without having examined the thing they named - the class EV-064, EV-065, WI-171 and WI-175
have already recorded four times.

Idempotent.
"""

import io
import json
import pathlib

BRAIN = pathlib.Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
STORE = BRAIN / "work-items.json"


WI_179 = {
    "id": "WI-179",
    "phase": 2,
    "title": (
        "The Go vulnerability scan could still exit 0 having scanned nothing, because a missing "
        "modules.txt fails its redirect silently in a step without errexit"
    ),
    "status": "COMPLETED",
    "priority": "high",
    "acceptance_criteria": [
        "The scan step refuses a missing modules.txt by name, before iterating it, so a missing "
        "list is a stated failure rather than a silent pass over zero modules",
        "The scan step carries errexit, so a failure in any line other than the scanner itself is "
        "not swallowed - while a failing module is still tolerated so every module is scanned",
        "An EMPTY module list is refused as well as a missing one, and that property is asserted by "
        "an executed scenario, because `[ ! -e ]` would still catch a missing file while accepting "
        "a zero-byte one",
        "The ability to fail is proved by executing the committed run: block against a scanner that "
        "reports a finding, and observe the proof fail when the guard is removed and separately when "
        "`-s` is weakened to `-e`",
    ],
    "source": "Review of the change set that hardened the scan step introduced for WI-178; "
    "scripts/prove_vuln_scan_gate.py scenario_empty_module_list_fails; and the printed output of "
    "the proof itself, which contradicted the scenario's own docstring",
    "reproduction": "The step as committed in 93be7f4 read `set -uo pipefail`, had no guard, and "
    "iterated with `done < modules.txt`. With modules.txt absent the redirect fails; without "
    "errexit the loop body never runs, `status` stays 0, and the step exits 0 having scanned "
    "nothing. Observed directly under bash. It was unreachable only because the resolve step runs "
    "immediately before it in the same job and directory - the same invisibility as the original "
    "defect, one step removed.\n\n"
    "The second half is a finding about the proof rather than the step. scenario_empty_list_is_"
    "unguarded_by_the_scan_step asserted nothing and carried a docstring claiming 'The scan step "
    "iterates modules.txt and has no empty-list guard of its own, so an empty list exits 0 having "
    "scanned nothing'. Once the `[ ! -s modules.txt ]` guard was added that sentence became false, "
    "and the scenario stayed in a reported-not-asserted list on a premise no longer true. The proof's "
    "own output printed the contradiction: `[info] exit 1, 0 invocations` on a line whose text said "
    "the empty case exits 0.",
    "notes": "The corrected scenario is now asserted rather than reported, and the reason it is a "
    "separate property rather than a variation of the missing-file case is narrow and specific: a "
    "guard weakened from `[ ! -s ]` to `[ ! -e ]` still refuses a missing modules.txt, so the "
    "missing-file scenario would keep passing while the empty case - go.work resolving to zero "
    "modules, which is the same pass-over-nothing - went back to exiting 0 with nothing asserting "
    "it. Only a scenario that seeds an empty file tells those two apart, and that was verified by "
    "execution rather than argued: weakening `-s` to `-e` leaves 'a missing module list fails the "
    "step' green and turns 'an empty module list fails the step' red.\n\n"
    "Deleting the guard outright fails both, and fails them differently - the missing case on the "
    "message and the empty case on the exit code - which is the more useful of the two signals: "
    "the missing-file scenario also asserts that the step SAYS it is refusing to scan nothing, so a "
    "guard that fails for an unrelated reason does not satisfy it.",
    "dependencies": ["WI-178"],
    "evidence_ref": ["EV-081"],
}

WI_180 = {
    "id": "WI-180",
    "phase": 2,
    "title": (
        "The workflow repeated toolchain/versions.env's pins with nothing comparing the two "
        "copies, while a comment claimed the toolchain job did exactly that"
    ),
    "status": "COMPLETED",
    "priority": "high",
    "acceptance_criteria": [
        "Every pin the workflow's env block repeats is compared against versions.env, and a drifted "
        "copy fails the toolchain gate by name",
        "A pin the workflow cannot express as an env reference - the integration job's Postgres "
        "image - is compared where it is actually written, rather than through an env variable "
        "nothing reads",
        "An expression is refused where GitHub cannot resolve it, and the message says why, so the "
        "obvious 'fix' of indirection is not discovered by breaking the workflow",
        "A pin compared by series rather than exactly is justified by what consumes it, and the "
        "reasoning is true",
        "Every value compared is one some step or job actually uses; a check over dead values is "
        "removed rather than kept",
        "An absent workflow, an absent key, an absent image, an unparseable env block and an "
        "ambiguous env block each fail rather than being skipped",
    ],
    "source": "Review of the change set introducing verify_workflow_env; the comment at "
    ".github/workflows/ci.yml that read 'The `toolchain` job asserts the two agree, so this "
    "duplication cannot silently rot'; GitHub's context-availability table",
    "reproduction": "Before this change set, scripts/verify_toolchain.py compared versions.env "
    "against six go.mod files, go.work, two package.json files, two pyproject.toml files and the "
    "lockfiles. It never opened .github/workflows/ci.yml, and the comment above the workflow's env "
    "block asserted that it did. env.GO_VERSION is what actions/setup-go installs in three jobs, so "
    "a workflow left behind at an older pin would have built every job on a different toolchain "
    "than the modules declare while all fourteen checks passed - which is what 93be7f4 did, rolling "
    "six go.mod files and versions.env to 1.26.8 and leaving the workflow's copy at nothing until "
    "this change set corrected both.\n\n"
    "The Postgres image is the case that made the first version of the fix wrong in a way worth "
    "recording. POSTGRES_IMAGE was declared in the workflow's env block and read by nothing; the "
    "image the integration job actually runs was the literal `postgres:17.11-alpine` under "
    "services.postgres. Comparing the dead copy produced a green gate that had never looked at the "
    "value it named: rolling the literal back to postgres:16-alpine left the gate passing. The "
    "tempting repair - indirection via `${{ env.POSTGRES_IMAGE }}` - would have broken the "
    "workflow, because GitHub's context-availability table allows github, needs, strategy, matrix, "
    "vars and inputs at `jobs.<job_id>.services` and not env.",
    "notes": "PYTHON_VERSION was originally excluded from the comparison on the stated ground that "
    "'verify_python_drift enforces the series'. That was false: verify_python_drift reads only the "
    "two pyproject.toml files and never opens the workflow, so env.PYTHON_VERSION - the interpreter "
    "actions/setup-python installs in six places - was constrained by nothing at all. It is now "
    "compared by major.minor, which is a constraint rather than an exemption, and versions.env's "
    "full patch against the workflow's series is not reported as drift.\n\n"
    "The workflow is parsed with a regex rather than a YAML parser because this script is the FIRST "
    "step of the toolchain job, before anything installs PyYAML, and a check that cannot start is a "
    "check that never runs. That choice is paid for in strictness: the parser requires exactly one "
    "top-level `env:` block and fails loudly otherwise, because an ambiguous pin is not a pin and a "
    "parser that quietly stopped matching would be the EV-064 shape one layer down.",
    "dependencies": ["WI-107"],
    "dependency_exemptions": {
        "WI-107": (
            "Correct, and recorded here because the distinction matters rather than because the "
            "dependency is spurious. WI-107 stays IN_PROGRESS for one reason: no CI run has ever "
            "been observed on a GitHub runner, so its container-build, gitleaks, CodeQL, govulncheck, "
            "cosign, integration and SBOM criteria remain configuration-only, exactly as EV-014 "
            "states. That is an unmet condition about OBSERVED OUTPUT and says nothing about whether "
            "this gate is complete.\n\n"
            "WI-180 is the drift gate behind WI-107's 'CI fails on toolchain drift' criterion, and "
            "it is finished: 18 checks, with negative controls run against the real workflow and "
            "observed to fail. Holding it IN_PROGRESS until somebody pushes to a runner would make "
            "the item's status a function of remote infrastructure rather than of the work, and "
            "would record a green local gate as unfinished - the same confusion in the opposite "
            "direction. WI-107's blocker text is unchanged and still records the real gap."
        )
    },
    "evidence_ref": ["EV-081"],
}


def main() -> bool:
    doc = json.loads(STORE.read_text(encoding="utf-8"))
    items = doc["items"]
    by_id = {i["id"]: i for i in items}

    changed = False
    for candidate in (WI_179, WI_180):
        existing = by_id.get(candidate["id"])
        if existing is None:
            items.append(candidate)
            changed = True
        elif existing != candidate:
            items[items.index(existing)] = candidate
            changed = True

    if not changed:
        print("unchanged: WI-179 and WI-180 already recorded")
        return False

    out = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    with io.open(STORE, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(out)

    print("WI-179 and WI-180 recorded")
    return True


if __name__ == "__main__":
    main()
