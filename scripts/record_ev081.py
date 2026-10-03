"""Record EV-081: WI-179 and WI-180 - two gates whose comments described controls that did not exist.

Idempotent, append-only, written without a BOM.
"""

import io
import json
import pathlib

BRAIN = pathlib.Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"

EVIDENCE_ID = "EV-081"
STAMP = "2026-10-03T15:40:00Z"
WORK_ITEM = "WI-179, WI-180"

CLAIM = (
    "Both gates now fail on the condition they name. The Go vulnerability scan step refused a "
    "missing or empty module list instead of exiting 0 over nothing, and the workflow's copies of "
    "toolchain/versions.env's pins are compared against versions.env - including the Postgres image "
    "the integration job actually runs, which was previously compared in a form nothing read. Both "
    "findings were defects in gates whose own comments asserted controls that did not exist."
)

METHOD = (
    "Neither was found by reading. Both were found by an adversarial review of an uncommitted "
    "change set that had already passed every check the repository runs, and both survived my own "
    "first verification because I verified the properties I had built rather than the properties "
    "that mattered.\n\n"
    "For WI-179 the reviewer's route was the proof's own output. The proof printed a line reading "
    "'exit 1, 0 invocations - the resolve step's refusal is what keeps this from being a pass over "
    "nothing' from a scenario whose docstring asserted that the scan step had no empty-list guard "
    "and therefore exited 0 over an empty list. Both could not be true. The scenario was asserting "
    "nothing, so the contradiction cost nothing at the time; it cost everything once the guard "
    "existed and the docstring had become a false claim inside the proof built to eliminate false "
    "claims.\n\n"
    "For WI-180 the reviewer's route was a search for consumers. It found that POSTGRES_IMAGE was "
    "declared in the workflow's env block and referenced nowhere in the repository, while the image "
    "the integration job runs was a literal at ci.yml:786. It then made the value decisive by "
    "mutating that literal to postgres:16-alpine and observing zero failures. I reproduced that: "
    "the gate I had written reported 'toolchain gate: PASS' while the database CI ran had been "
    "rolled back a major version. That is the EV-064 shape exactly - a gate reporting success "
    "without having examined the thing it named - and it was in the change whose stated purpose was "
    "to close an instance of that shape.\n\n"
    "The same review found that the change's provenance claim was false. Both files asserted 'That "
    "check did not exist until 93be7f4', implying the gap had been closed by the commit before. "
    "`git log --all -S verify_workflow_env -- scripts/verify_toolchain.py` returns nothing: the check "
    "is introduced by this change set, and the gap ran through 93be7f4 and ce6dc50 unaddressed. In "
    "a repository where a comment is treated as a constraint, a wrong claim about the provenance of "
    "the control under discussion is not a smaller problem than the defect it describes.\n\n"
    "And it found that the PYTHON_VERSION exclusion rested on a false premise. My stated reason was "
    "that 'verify_python_drift enforces the series'. verify_python_drift reads the two "
    "pyproject.toml files and never opens the workflow, so env.PYTHON_VERSION - the interpreter "
    "actions/setup-python installs in six places - was constrained by nothing. Mutating it to "
    "'3.13', and deleting the key outright, both produced zero failures.\n\n"
    "The tempting fix for the Postgres image was indirection: `image: ${{ env.POSTGRES_IMAGE }}`. "
    "Before writing it I checked GitHub's context-availability table, which allows github, needs, "
    "strategy, matrix, vars and inputs at `jobs.<job_id>.services` and NOT env. That expression would "
    "not resolve and the workflow would be rejected - so the check reads the literal where it is "
    "written instead, and refuses an expression there with a message that says why."
)

RESULT = (
    "scripts/verify_toolchain.py reports 18 checks, up from 14. The four added are the three env "
    "pins (GO_VERSION, NODE_VERSION exact; PYTHON_VERSION by series) and the Postgres service image. "
    "\n\n"
    "scripts/prove_vuln_scan_gate.py reports PASS (7 properties), up from 5 asserted plus 1 "
    "reported. The empty-list case moved from the reported list into the asserted list, and the "
    "reported list is gone rather than left empty:\n\n"
    "  clean scan scans every module: 6 invocations, exit 0\n"
    "  a finding fails the step: exit 1, affected module named\n"
    "  a finding does not stop the scan: all 6 modules scanned, aggregated failure preserved\n"
    "  a scanner failure fails the step: exit 1 on a scanner that could not run\n"
    "  a missing module list fails the step: exit 1, 0 invocations\n"
    "  an empty module list fails the step: exit 1, 0 invocations\n"
    "  real govulncheck refuses the repository root: root invocation refused with 'no go.mod file'; "
    "per-module invocation exited 0\n\n"
    "Six negative controls were run and observed to fail, which is the part that makes the six "
    "passes evidence rather than description.\n\n"
    "On the real ci.yml, restoring a byte-identical copy after each:\n"
    "  env.GO_VERSION 1.26.8 -> 1.26.2                          gate FAILS, names env.GO_VERSION\n"
    "  services.postgres.image -> postgres:16-alpine            gate FAILS, names the literal\n"
    "  services.postgres.image -> ${{ env.POSTGRES_IMAGE }}     gate FAILS, explains that GitHub "
    "cannot resolve env at jobs.<job_id>.services\n"
    "  services.postgres.image removed                          gate FAILS, 'not examining it'\n"
    "  env.PYTHON_VERSION '3.14' -> '3.13'                     gate FAILS, names the series\n\n"
    "On the real ci.yml scan step, restoring byte-identically after each:\n"
    "  the `[ ! -s modules.txt ]` guard deleted                 2 of 7 properties fail, exit 1\n"
    "  the guard weakened `[ ! -s ]` -> `[ ! -e ]`              1 of 7 properties fail, exit 1\n\n"
    "The second is the one that justifies the first existing as a separate scenario. With `-e`, "
    "'a missing module list fails the step' stays GREEN and only 'an empty module list fails the "
    "step' turns red. Before this change set nothing asserted the empty case at all, so that "
    "weakening would have passed every check in the repository. The reviewer's claim that the "
    "emptiness test was unasserted was verified by execution and is corrected.\n\n"
    "Also verified, all after the corrections: tests/ci passes 165 tests (144 at EV-080, plus 11 "
    "toolchain cases and 5 for the proof's real-scanner scenario, replacing the 5 the toolchain "
    "section had); scripts/check_workflow_bash.py parses 50 run: blocks clean; "
    "scripts/generate_g5_gate_report.py --check reports the report current against 94 artifact "
    "digests; scripts/verify_project_brain.py passes; govulncheck v1.8.0 reports 'No vulnerabilities "
    "found' and exit 0 on all six modules; go build and go vet pass on all six modules; and go test "
    "-race -count=1 passes on all six."
)

DEFECT_FOUND_AND_FIXED = (
    "1. .github/workflows/ci.yml, the Go vulnerability scan step: `set -uo pipefail`, no guard, "
    "`done < modules.txt`. A missing modules.txt fails its redirect, the loop body never runs, "
    "`status` stays 0, and the step exits 0 having scanned nothing. Now `[ ! -s modules.txt ]` with "
    "a named refusal, under `set -euo pipefail`, with the scanner's failure the one deliberate "
    "exception via `|| rc=$?`.\n"
    "2. scripts/prove_vuln_scan_gate.py, scenario_empty_list_is_unguarded_by_the_scan_step: asserted "
    "nothing, was typed `-> Outcome` while returning a str, and its docstring claimed the scan step "
    "had no empty-list guard - false once (1) landed. Replaced by scenario_empty_module_list_fails, "
    "which asserts the empty case and explains why it is not a variation of the missing-file case.\n"
    "3. scripts/prove_vuln_scan_gate.py, the real-scanner scenario's exit-3 branch: it returned a "
    "green Outcome whose text read 'reported a reachable vulnerability' and DISCARDED the scanner's "
    "output. A security finding was being rendered as a passing checkmark with its content thrown "
    "away - a fourth instance of the confusion this repository has already recorded three times, in "
    "the proof built to catch it. Now it still passes, because the property asserts the scanner "
    "runs and the scan step is what blocks on a finding, but it raises a WARN quoting the "
    "scanner's own text. Five tests in tests/ci/test_prove_vuln_scan_gate.py pin this, including the "
    "negative control that a clean scan raises no warning.\n"
    "4. scripts/verify_toolchain.py, WORKFLOW_ENV_KEYS: compared POSTGRES_IMAGE, a value declared in "
    "the workflow's env block and read by nothing, while the literal the integration job runs was "
    "checked by nothing. Comparing the dead copy produced a gate that passed while the live value "
    "drifted. POSTGRES_IMAGE was removed from the env block, the literal is now checked where it is "
    "written, and an expression there is refused with the reason GitHub cannot resolve it.\n"
    "5. scripts/verify_toolchain.py and .github/workflows/ci.yml: both claimed the workflow-pin "
    "check 'did not exist until 93be7f4'. It did not exist there or at ce6dc50; this change set "
    "introduces it.\n"
    "6. scripts/verify_toolchain.py: PYTHON_VERSION was excluded from the comparison on the stated "
    "ground that verify_python_drift enforces the series. It does not read the workflow at all, so "
    "the pin was unconstrained. Now compared by major.minor, with the reason corrected in the code, "
    "in the test docstring and in the workflow comment.\n"
    "7. tests/ci/test_verify_toolchain.py: the fixture had no services block, so the service-image "
    "tests exercised nothing. The fixture now carries one, shaped like the real workflow - bare "
    "unquoted image value, indented under services - and six tests cover the literal, including a "
    "second drifting declaration (only the first is compared otherwise) and a nested image key that "
    "must not be mistaken for the service's own.\n"
    "8. tests/ci/requirements.txt: the comment still said 'the 28 workflow-integrity tests' twice. "
    "This change set deleted the identical stale count from ci.yml for exactly this reason and left "
    "the sibling copy, and test_ci_workflow.py collects 31. Now no count at all, with the reason.\n"
    "9. .github/workflows/ci.yml: a comment described the scanner's failure branch as "
    "`|| { status=1; }`, a construct this same change set removed in favour of `|| rc=$?`. The two "
    "comments described different code."
)

SIGNIFICANCE = (
    "The common thread is that both findings lived in code whose stated purpose was to eliminate a "
    "false pass. That is worth stating plainly, because it is the argument for adversarial review "
    "even on changes that are already green.\n\n"
    "The failure mode in both cases is not 'the check is wrong'. It is 'the check examines a "
    "different thing than the one it is named for, and reports success'. WI-180's first version "
    "compared an env variable that nothing read while the literal the job actually ran drifted a "
    "major version under a green gate. That is the EV-064 shape reproduced one level up, by the "
    "change written to close EV-064's shape. Nothing about running the gate would have found it: "
    "the gate reported 17 checks passed, and every one of them passed.\n\n"
    "WI-179's second half is the mirror image, and it is the more interesting half. The proof's "
    "empty-list scenario asserted nothing and carried a docstring that became false when the guard "
    "was added. A scenario that asserts nothing cannot fail, so it cannot report the contradiction "
    "either - the contradiction was visible only in the proof's printed output, as a line whose text "
    "said one thing and whose exit code said another. A reviewer reading the code would have had to "
    "notice that the docstring and the new guard disagreed; a reviewer reading the output saw it "
    "immediately. Neither of them saw it, because neither the code nor the output was read by anyone "
    "who was looking for it.\n\n"
    "The generalisable rule is the one this repository has now established five times: a gate's own "
    "claim is not evidence for the gate. It applies to docstrings and comments with the same force "
    "as it applies to test names, and the specific failure here was a docstring that had quietly "
    "become a false claim about behaviour that had changed three lines above it.\n\n"
    "The other thing worth recording is that both fixes were verified by making them fail. Six "
    "negative controls, each restored byte-identically afterwards. The `-s` to `-e` weakening is the "
    "one that matters most, because before this change set it would have passed every check in the "
    "repository - including the missing-file scenario, which stays green under it. A gate that only "
    "distinguishes the cases somebody thought of is a gate that passes on the case somebody did not."
)

CAVEATS = (
    "NOT VERIFIED on a GitHub runner. Everything above was executed on this host, Windows, with the "
    "bash on PATH being the WSL bash. The three resolve-step scenarios are SKIPPED here because jq "
    "is not installed on this host; they are asserted statically in tests/ci/test_ci_workflow.py and "
    "will execute on the Ubuntu runner, which has jq. They are genuinely unexecuted until then.\n\n"
    "The claim that GitHub cannot resolve `${{ env.X }}` at `jobs.<job_id>.services` rests on "
    "GitHub's published context-availability table, read on 2026-10-03, not on a run of the "
    "workflow. That table is the documentation GitHub's own renderer is built from, and the "
    "sibling `jobs.<job_id>.container.image` row is corroborated by github/docs issue 25520, where "
    "the env and secrets contexts are reported as unresolvable there and the docs team treats it as "
    "intended. It has not been observed on a runner.\n\n"
    "ONE UNEXPLAINED OBSERVATION, recorded rather than normalised. On the first execution of the "
    "proof after the change set was written, the real-scanner scenario reported the per-module "
    "invocation exiting 3 - govulncheck's code for a reachable vulnerability - and passed. That was "
    "real: the return code came from the real scanner against the real tree, and no fake shim was on "
    "PATH (the tool is resolved before any sandbox is built). It has not recurred in any subsequent "
    "run: govulncheck v1.8.0 reports 'No vulnerabilities found' and exit 0 on all six modules, "
    "repeatedly and including a direct re-run of the exact two-invocation sequence the scenario "
    "performs. The root cause was NOT established and is not guessed at here. It matters because if "
    "that exit 3 was genuine, the dependency-scan job would have failed on this commit, and the "
    "scan step - not this proof - is what would have reported it. The disclosure fix described in "
    "defect 3 exists because of this event: it was the reason to stop letting a finding render as a "
    "green line with its text discarded.\n\n"
    "The scan was not observed to catch a real vulnerability. The negative controls prove the step "
    "fails when the scanner reports something, using a fake scanner that exits 3 exactly as "
    "govulncheck does. That establishes the plumbing, not the scanner's reachability analysis.\n\n"
    "No Go source changed in this commit, so the Go results above re-establish rather than extend "
    "EV-079's verification. They are recorded because the final gate for a commit is a full sweep "
    "at that commit, not a sweep at the commit where the last change happened to land."
)

EXCEPTION = (
    "No exception. Both gates that were wrong are the gates that were repaired, and each was "
    "repaired by removing the part that could not work rather than by adjusting it."
)

ARTIFACTS = [
    ".kilo/ecc/project-brain/evidence.jsonl",
    ".kilo/ecc/project-brain/work-items.json",
    ".github/workflows/ci.yml",
    "scripts/prove_vuln_scan_gate.py",
    "scripts/verify_toolchain.py",
    "tests/ci/test_ci_workflow.py",
    "tests/ci/test_prove_vuln_scan_gate.py",
    "tests/ci/test_verify_toolchain.py",
    "tests/ci/requirements.txt",
    "scripts/update_work_items_wi179.py",
    "scripts/record_ev081.py",
]

SUPERSEDES = []


def record() -> bool:
    store = BRAIN / "evidence.jsonl"

    line = json.dumps(
        {
            "schema": "ecc.project-brain/evidence/v7",
            "evidence_id": EVIDENCE_ID,
            "recorded_at": STAMP,
            "recorded_by": "team-lead",
            "work_item": WORK_ITEM,
            "claim": CLAIM,
            "status": "RESOLVED",
            "method": METHOD,
            "result": RESULT,
            "defect_found_and_fixed": DEFECT_FOUND_AND_FIXED,
            "significance": SIGNIFICANCE,
            "caveats": CAVEATS,
            "exception": EXCEPTION,
            "artifacts": ARTIFACTS,
            "supersedes": SUPERSEDES,
        },
        ensure_ascii=False,
    )

    if store.exists():
        for existing in store.read_text(encoding="utf-8").splitlines():
            if existing.strip() and json.loads(existing).get("evidence_id") == EVIDENCE_ID:
                print("unchanged: " + EVIDENCE_ID + " already recorded")
                return False

    with io.open(store, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")
    print("recorded " + EVIDENCE_ID)
    return True


if __name__ == "__main__":
    record()
