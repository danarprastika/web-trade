"""Record EV-080: WI-178 - the Go vulnerability scan had never run.

Idempotent, append-only, written without a BOM.
"""

import io
import json
import pathlib

BRAIN = pathlib.Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"

EVIDENCE_ID = "EV-080"
STAMP = "2026-10-03T12:27:16Z"
WORK_ITEM = "WI-178"

CLAIM = (
    "The Go vulnerability scan now runs against all six modules and blocks on a finding. It had "
    "never run at all: govulncheck resolves a single module rooted at its working directory, the CI "
    "workflow invoked it at a repository root that has go.work and no go.mod, and every run exited 1 "
    "with 'no go.mod file' before scanning a line of code."
)

METHOD = (
    "The defect was found by running the workflow's own command rather than by reading it. The "
    "dependency-scan job resolved its module list correctly - `go work edit -json`, per the same "
    "reasoning as the go job, because a regex over go.work captures the literal '(' from the "
    "`use (...)` block - and handed the result to golang/govulncheck-action. That action expands to "
    "`govulncheck -C ${work-dir} -format ${output-format} ${go-package}` with work-dir defaulting "
    "to '.'. Read that way the command looks correct: real package patterns, resolved from the "
    "workspace, not a root-relative './...' that matches no module.\n\n"
    "Running it is what established the defect. From the repository root, with the real scanner and "
    "with the fake one, `govulncheck -C . -format text ./contracts/go/...` exits 1 with 'no go.mod "
    "file'. The same command with GOWORK=off, and with no pattern at all, behaves identically "
    "(`no package patterns provided`, exit 2, when there is no pattern), so the refusal is about the "
    "working directory having no go.mod rather than about the pattern. Pointed at a module "
    "directory the same binary exits 0.\n\n"
    "Why it survived review is the part worth recording. A gate that always errors produces no "
    "findings, so there is never a finding to contradict the claim that the scan works. The job was "
    "red, but for a reason that read like any other infrastructure failure, and EV-014 already "
    "carried the honest caveat - govulncheck 'verified as configuration only, never as observed "
    "output' - which is exactly the caveat a broken gate generates about itself and which therefore "
    "looked like ordinary prudence.\n\n"
    "The fix was chosen between three options. A root go.mod was rejected: it would give the "
    "repository a second build definition covering no code, against docs/02 section 8, and it would "
    "turn the root-relative './...' into a scan of an empty module that reports success. Keeping the "
    "action and pointing work-dir at one module was rejected: six modules, one work-dir. One "
    "invocation per module with -C, driven by the same `go work edit -json` list the go job already "
    "builds, is what was left.\n\n"
    "A gate is only worth having if it has been observed failing, so the new step was proved rather "
    "than argued. scripts/prove_vuln_scan_gate.py extracts the committed `run:` block and executes "
    "it under bash against a fake scanner that records its argument list."
)

RESULT = (
    "The scan step now runs govulncheck once per module with -C, over the module list resolved from "
    "`go work edit -json`. Five properties are asserted structurally in "
    "tests/ci/test_ci_workflow.py: the action is gone, the install is version-pinned rather than "
    "@latest, the module list comes from the Go toolchain, every invocation carries -C naming a "
    "module, and the step exits non-zero when any module failed.\n\n"
    "Six properties are executed by scripts/prove_vuln_scan_gate.py against the committed step, all "
    "passing:\n\n"
    "  clean scan scans every module: 6 invocations, exit 0\n"
    "  a finding fails the step: exit 1, affected module named\n"
    "  a finding does not stop the scan: all 6 modules scanned, aggregated failure preserved\n"
    "  a scanner failure fails the step: exit 1 on a scanner that could not run\n"
    "  scan step over an empty module list: exit 0, 0 invocations (reported, not asserted)\n"
    "  real govulncheck refuses the repository root: refused with 'no go.mod file'; per-module "
    "invocation exits 0\n\n"
    "The last one checks the premise against the real scanner and the real tree, so if govulncheck "
    "ever learns to resolve workspaces the redundant per-module structure is flagged rather than "
    "left behind unexplained.\n\n"
    "The proof was then shown to fail on purpose. Replacing the step's failure branch with `|| "
    "true` - keeping the loop, the -C, and the aggregation - made three of the six properties fail, "
    "including 'a finding fails the step' and 'a scanner failure fails the step', and the script "
    "exited 1. ci.yml was restored byte-for-byte and the proof re-run to PASS.\n\n"
    "Two Windows-specific defects were found and fixed while building the proof, both of which "
    "would have made it pass for the wrong reason. The fake scanner was first written in text mode, "
    "which translated its shebang to `#!/usr/bin/env bash\\r`, so the shim never ran and every "
    "scenario reported a scanner failure - the exact CRLF trap check_workflow_bash.py documents. "
    "And the fake scanner was first configured through an environment variable, which does not "
    "survive the Windows-to-Linux boundary when the bash on PATH is WSL: WSL translates PATH and a "
    "small set of well-known names and drops the rest, so the shim saw an empty variable, never "
    "reported its finding, and the two scenarios that must fail reported success. Configuration is "
    "now baked into the generated scripts, and every scenario independently asserts how many times "
    "the shim ran, read from the shim's own log rather than from anything the harness remembers.\n\n"
    "The workflow's own bash is valid: scripts/check_workflow_bash.py parses 50 run: blocks clean. "
    "tests/ci passes 144 tests."
)

DEFECT_FOUND_AND_FIXED = (
    "1. .github/workflows/ci.yml dependency-scan: govulncheck was invoked through "
    "golang/govulncheck-action, which runs `govulncheck -C .` at the checkout root. With no root "
    "go.mod the scanner refused to start, so no Go code was ever scanned and the step's only "
    "observable behaviour was an exit code nobody was reading.\n"
    "2. The scanner was installed at `@latest` inside that action, so the finding set could change "
    "under a commit that changed nothing. It is now installed by the job at an exact version, "
    "verified against the Go checksum database by `go install module@version` - which is enforced by "
    "the toolchain rather than asserted in a comment, and is a stronger property than the SHA "
    "comment it replaces.\n"
    "3. scripts/prove_vuln_scan_gate.py, first version: the fake scanner was written in text mode, "
    "producing a CRLF shebang so the shim never executed. Every scenario then reported a scanner "
    "failure and the proof would have passed while exercising nothing.\n"
    "4. scripts/prove_vuln_scan_gate.py, first version: the fake scanner was configured through an "
    "environment variable, which WSL drops when the bash on PATH is the WSL bash. The shim saw an "
    "empty variable, reported no finding, and the two scenarios whose entire purpose is to fail "
    "reported success - the proof was green because it was not working."
)

SIGNIFICANCE = (
    "The class of defect is worth naming precisely, because it is not 'a gate that always passes'. "
    "A gate that always passes is caught the first time it fails to catch something. This one "
    "always FAILED, loudly, on every run, and that is why it survived: a permanently red job reads "
    "as broken infrastructure, and a permanently red job whose failure nobody triaged is "
    "indistinguishable from one that is merely flaky. What removed it was not attention but a single "
    "act of running the workflow's own command on the developer's machine, which is a different and "
    "much cheaper event than waiting for a red CI job to be read.\n\n"
    "The same shape appears three times in this repository's own record, which is why it is worth "
    "writing down rather than fixing once. EV-064 and EV-065 are checks that reported success "
    "without exercising anything. WI-171's guard lived in a test file `go run ./cmd/migrate` never "
    "executes - present in the repository, absent from the product. WI-175 was a package that\n"
    "reported 'ok' having skipped every test that covered the shipped behaviour. In each case the\n"
    "signal that would have caught it existed but was never observed, and the report that should\n"
    "have caught it was the report nobody read.\n\n"
    "The generalisable rule is that a gate's own claim is not evidence for the gate. scripts/\n"
    "prove_vuln_scan_gate.py exists because the first version of this fix could have been wrong in\n"
    "the same direction - a scan step that looks correct, scans every module, and exits 0 when the\n"
    "scanner reports something - and would have passed every static assertion written about it. The\n"
    "negative control is what distinguishes them, and it is cheap: the gate was made to fail on\n"
    "purpose and observed to fail.\n\n"
    "The three mutation gates that are not wired into CI - mutation_check_model.py,\n"
    "mutation_check_local_env.py, mutation_check_gate_g1.py - were checked while doing this and\n"
    "all three pass locally. They remain unwired by the explicit decision recorded in WI-174 ('The\n"
    "gate is not wired into CI, and this entry does not change that'), not by oversight, and this\n"
    "item does not change it either. All three are slow - 711s, 80s and 49s respectively - and the\n"
    "go job carries timeout-minutes: 15, so wiring them is a budget decision rather than a\n"
    "one-line edit. It is reported here so that the fact is on the record rather than rediscovered."
)

CAVEATS = (
    "NOT VERIFIED on a GitHub runner. Everything above was executed on this host, Windows, with the "
    "bash on PATH being the WSL bash, and the resolve-step scenarios were SKIPPED because jq is not "
    "installed here. Those three scenarios - that the resolve block lists every module, refuses an "
    "empty workspace, and refuses a module with no go.mod - are asserted statically in "
    "tests/ci/test_ci_workflow.py and will execute on the Ubuntu runner, which has jq. They are\n"
    "genuinely unexecuted until then and are not claimed otherwise.\n\n"
    "The scan was not observed to catch a real vulnerability. The negative control proves the step\n"
    "fails when the scanner reports something, using a fake scanner that exits 3 exactly as\n"
    "govulncheck does. That establishes the plumbing, not that the scanner's reachability analysis\n"
    "is accurate.\n\n"
    "The 1.26.8 bump and this fix are in the same commit but are separate findings with separate\n"
    "evidence records (EV-079 and EV-080). The scan gate could not have caught the seven\n"
    "standard-library CVEs at 1.26.2 for the reason this record is about, so the bump's verification\n"
    "does not depend on this fix and neither depends on the other.\n\n"
    "Dropping the action also drops its Go setup and caching. The job already runs "
    "actions/setup-go with cache: true before this point, so nothing is lost, and the action's own "
    "repo-checkout step was a redundant second checkout of a tree the job had already checked out."
)

EXCEPTION = (
    "No exception. The step that was broken is the step that was repaired, and it is repaired by\n"
    "removing the wiring that could not work rather than by adjusting it."
)

ARTIFACTS = [
    ".kilo/ecc/project-brain/evidence.jsonl",
    ".kilo/ecc/project-brain/work-items.json",
    ".github/workflows/ci.yml",
    "scripts/prove_vuln_scan_gate.py",
    "tests/ci/test_ci_workflow.py",
    "scripts/record_ev080.py",
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