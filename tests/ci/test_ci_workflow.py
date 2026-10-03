"""Static validation of the CI workflow.

This is not a substitute for running the workflow, and it is not claimed to be one. It
catches the class of error that would otherwise be discovered only after pushing: a
malformed document, an action pinned to something that is not a commit SHA, or a step
referencing an output id that does not exist.

The SHA check is the important one. docs/02_POLYGLOT_ENGINEERING_STANDARD.md section 10
requires a locked, attested dependency graph, and a CI step pinned to a mutable tag like
`@v4` is a supply-chain hole. A workflow that looks pinned but is not would be worse than
an obviously unpinned one, because review would not catch it.

Run:
    python -m pytest tests/ci -q
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="PyYAML is required to parse the workflow")

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

FULL_SHA = re.compile(r"^[0-9a-f]{40}$")

# Every action this workflow references, mapped to the tag the SHA was resolved from.
# The comment on each `uses:` line must agree with this map, so a SHA cannot be silently
# repointed at a different tag.
EXPECTED_ACTIONS = {
    "actions/checkout": "v4.2.2",
    "actions/setup-go": "v5.5.0",
    "actions/setup-node": "v4.1.0",
    "actions/setup-python": "v5.6.0",
    "actions/upload-artifact": "v4.6.2",
    "github/codeql-action": "v3.28.17",
    "anchore/sbom-action": "v0.20.6",
    "sigstore/cosign-installer": "v3.8.2",
    "docker/build-push-action": "v6.17.0",
}


@pytest.fixture(scope="module")
def workflow() -> dict:
    if not WORKFLOW.is_file():
        pytest.skip("ci.yml not present")
    parsed = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict), "workflow must parse to a mapping"
    return parsed


def _uses_entries(workflow: dict) -> list[tuple[str, str]]:
    """Yield (action_path, pinned_ref) for every `uses:` in the workflow.

    A subpath action (`github/codeql-action/init`) is normalised back to its repository
    so it can be checked against EXPECTED_ACTIONS.
    """
    found: list[tuple[str, str]] = []
    for job in (workflow.get("jobs") or {}).values():
        for step in (job or {}).get("steps") or []:
            uses = step.get("uses")
            if not uses:
                continue
            parts = uses.split("@", 1)
            if len(parts) != 2:
                continue
            action, ref = parts
            owner_repo, _, _subpath = action.partition("/")[0] + "/" + action.partition("/")[1].split("/")[0], "", ""
            # action looks like "owner/repo" or "owner/repo/subpath"
            segments = action.split("/")
            owner_repo = "/".join(segments[:2])
            found.append((owner_repo, ref))
    return found


def test_workflow_parses_and_declares_triggers(workflow: dict) -> None:
    # PyYAML resolves the bare key `on` to the boolean True, a YAML 1.1 quirk. Accept
    # either so the test does not depend on how the loader normalises it.
    triggers = workflow.get("on", workflow.get(True))
    assert triggers, "workflow must declare triggers"
    assert "pull_request" in triggers, "PRs must be validated before merge"


def test_project_brain_gate_runs_on_every_merge(workflow: dict) -> None:
    """The Project Brain is the record of what this project has verified. Its gate must run
    in CI, and its own failure modes must be tested there, otherwise the ledger can
    quietly drift into overstating what was actually checked while still looking healthy."""
    jobs = workflow.get("jobs") or {}
    assert "project-brain" in jobs, (
        "the Project Brain integrity gate must run in CI; it is the only thing standing "
        "between a stale or overstating ledger and a green build"
    )
    steps = yaml.safe_load(yaml.safe_dump(jobs["project-brain"]))["steps"]
    runs = [
        s.get("run", "") for s in steps if isinstance(s, dict) and s.get("run")
    ]
    joined = "\n".join(runs)
    assert "scripts/verify_project_brain.py" in joined, (
        "the project-brain job must actually run the gate, not merely exist"
    )
    assert "tests/ci/test_verify_project_brain.py" in joined, (
        "the project-brain job must run the gate's own tests, so a gate that has stopped "
        "rejecting tampering fails here rather than at the next real integrity incident"
    )


def test_every_job_that_runs_the_ci_suite_first_installs_its_dependencies(
    workflow: dict,
) -> None:
    """Any job that runs tests/ci must install that suite's pinned dependencies first.

    This is not hypothetical, and it was not one job. The toolchain job went straight from
    actions/setup-python to `python -m pytest tests/ci` with no install step, so on the runner
    pytest was absent and the step exited 1 in under a second; because the workflow is
    fail-fast, that one missing line left all eleven other jobs skipped. The spec-gate and
    project-brain jobs carried the identical defect, hidden behind the same fail-fast, and each
    died in about five seconds for the same reason. None of it involved the code under test.

    So this is asserted for EVERY such job rather than for the one that happened to be
    diagnosed. A new gate job added without the install would otherwise fail for want of its own
    dependency, and the error would name a missing module rather than the missing line.

    Order is part of the assertion: an install placed after the pytest call is the same defect
    with extra lines.
    """
    jobs = workflow.get("jobs") or {}
    assert jobs, "the workflow declares no jobs, so this assertion is vacuous"

    offenders: list[str] = []
    checked = 0
    for name, job in jobs.items():
        steps = (job or {}).get("steps") or []
        runs = [
            s.get("run", "") for s in steps if isinstance(s, dict) and s.get("run")
        ]
        first_use = next(
            (i for i, run in enumerate(runs) if "pytest" in run and "tests/ci" in run),
            None,
        )
        if first_use is None:
            continue
        checked += 1
        installed = any(
            "pip install" in run and "tests/ci/requirements.txt" in run
            for run in runs[:first_use]
        )
        if not installed:
            offenders.append(
                f"{name} (runs tests/ci at step {first_use} with no earlier "
                f"pip install of tests/ci/requirements.txt)"
            )

    assert checked, (
        "no job runs tests/ci any more, so the gates' own negative cases are unverified; a gate "
        "that has stopped rejecting bad input is trusted and therefore worse than no gate"
    )
    assert not offenders, (
        "these jobs run the CI suite without installing its dependencies. actions/setup-python "
        "gives a clean interpreter with no pytest, so `python -m pytest tests/ci/...` fails with "
        "'No module named pytest' before any test runs:\n  "
        + "\n  ".join(offenders)
    )


def test_the_ci_suite_dependencies_are_pinned_not_floating(workflow: dict) -> None:
    """tests/ci's requirements must be exact pins.

    pytest.importorskip means a missing PyYAML makes tests/ci/test_ci_workflow.py skip
    instead of fail, so an unpinned dependency that resolves differently on the runner is
    the difference between 141 executed tests and 113 executed tests, reported the same
    green either way.
    """
    requirements = REPO_ROOT / "tests" / "ci" / "requirements.txt"
    assert requirements.is_file(), (
        "tests/ci/requirements.txt is missing, so the toolchain job cannot install what the "
        "suite needs and the job cannot start"
    )
    pins = [
        line.strip()
        for line in requirements.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert pins, "tests/ci/requirements.txt declares no dependencies, so nothing is installed"
    unpinned = [p for p in pins if "==" not in p]
    assert not unpinned, (
        f"tests/ci/requirements.txt must pin every dependency exactly; unpinned: {unpinned}"
    )


def test_every_action_is_pinned_to_a_full_commit_sha(workflow: dict) -> None:
    uses_entries = _uses_entries(workflow)
    assert uses_entries, "no actions referenced; the test would otherwise pass vacuously"
    for action, ref in uses_entries:
        assert FULL_SHA.match(ref), (
            f"{action} is pinned to {ref!r}, which is not a 40-character commit SHA. "
            f"Mutable tags such as @v4 are a supply-chain hole (docs/02 section 10)."
        )


def test_every_uses_line_is_sha_pinned_and_annotated(workflow: dict) -> None:
    """Catches the common regression: someone 'simplifies' a SHA back to a tag.

    Each `uses:` must pin a full commit SHA *and* carry a `# <tag>` annotation. The
    annotation matters as much as the pin: without it, the next person cannot tell which
    release a SHA corresponds to and has no way to verify it.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    pattern = re.compile(r"^\s*-?\s*uses:\s*(\S+?)@(\S+)\s*(#.*)?$", re.MULTILINE)
    entries = pattern.findall(text)
    assert entries, "no `uses:` lines found; the test would otherwise pass vacuously"
    for action, ref, comment in entries:
        assert FULL_SHA.match(ref), (
            f"{action} uses ref {ref!r}, which is not a 40-character commit SHA. "
            f"Mutable tags such as @v4 are a supply-chain hole (docs/02 section 10)."
        )
        assert comment.strip().startswith("#"), (
            f"{action} is pinned to {ref} but has no '# <tag>' annotation, so the pin "
            f"cannot be traced back to a release or independently verified"
        )


def test_action_tag_comments_match_the_expected_map(workflow: dict) -> None:
    """A SHA must be discoverably traceable to the tag it was resolved from."""
    text = WORKFLOW.read_text(encoding="utf-8")
    seen: dict[str, str] = {}
    for match in re.finditer(r"uses:\s*(\S+?)@([0-9a-f]{40})\s*#\s*(\S+)", text):
        action, _sha, tag = match.group(1), match.group(2), match.group(3)
        segments = action.split("/")
        owner_repo = "/".join(segments[:2])
        seen[owner_repo] = tag

    missing = set(EXPECTED_ACTIONS) - set(seen)
    assert not missing, f"these actions have no tag annotation: {sorted(missing)}"
    for action, expected_tag in EXPECTED_ACTIONS.items():
        assert seen[action] == expected_tag, (
            f"{action} is annotated as {seen[action]!r} but this test expects "
            f"{expected_tag!r}. If the pin was deliberately changed, update both."
        )


def test_every_annotated_action_is_in_the_expected_map(workflow: dict) -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for match in re.finditer(r"uses:\s*(\S+?)@[0-9a-f]{40}", text):
        segments = match.group(1).split("/")
        owner_repo = "/".join(segments[:2])
        assert owner_repo in EXPECTED_ACTIONS, (
            f"{owner_repo} is referenced but has no verified SHA recorded in this test; "
            f"resolve it and add it to EXPECTED_ACTIONS"
        )


def test_default_permissions_are_read_only(workflow: dict) -> None:
    perms = workflow.get("permissions")
    assert perms == {"contents": "read"}, (
        f"top-level permissions must be read-only; got {perms!r}. "
        f"Jobs needing more must request it explicitly."
    )


def test_no_job_writes_secrets_to_the_log(workflow: dict) -> None:
    """A secret echoed into a CI log is a disclosure, not a diagnostic."""
    text = WORKFLOW.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert "echo ${{ secrets." not in stripped, f"secret echoed to log: {stripped!r}"
        assert "set -x" not in stripped, "shell tracing can disclose secrets"


def test_go_commands_do_not_use_a_root_relative_package_pattern(workflow: dict) -> None:
    r"""Regression guard for a real bug found by running the workflow's commands locally.

    `go vet ./...` and `go test ./...` at the repository root FAIL in a Go workspace:
    go.work lists modules in subdirectories, so a root-relative pattern matches no
    module and the tool reports "directory prefix . does not contain modules listed in
    go.work". The CI job would have failed on every single run.

    Modules are therefore addressed per module, and the list is taken from
    `go work edit -json` rather than parsed out of go.work by hand: a naive
    `/^use\s+/` pattern captures the literal "(" from the `use (...)` block and gates
    nothing.
    """
    go_job = (workflow.get("jobs") or {}).get("go") or {}
    steps = go_job.get("steps") or []
    scripts = "\n".join(str(s.get("run", "")) for s in steps)

    for bad in ("go vet ./...", "go test ./...", "go build ./...", "gofmt -l . | xargs"):
        assert bad not in scripts, (
            f"{bad!r} does not work against the repository root in a Go workspace; "
            f"iterate the modules from `go work edit -json` instead"
        )

    assert "go work edit -json" in scripts, (
        "the Go job must derive its module list from `go work edit -json` so the block "
        "and single-line `use` forms both work and adding a module needs no workflow edit"
    )
    # Every module-scoped Go command must be driven by the resolved module list, so a
    # module added to go.work cannot escape the gate.
    for command in ("go vet", "go build", "go test", "go mod verify"):
        assert re.search(rf"{re.escape(command)}.*\$m", scripts, re.DOTALL) or command in scripts, (
            f"{command} must be run per module, driven by the resolved module list"
        )
    # Guard the empty-workspace case: a gate over zero modules passes vacuously.
    assert "refusing to run an empty gate" in scripts, (
        "the Go job must fail when go.work resolves to zero modules, otherwise the gate "
        "passes vacuously over nothing"
    )


def test_dependency_scan_and_integration_use_module_scoped_patterns(workflow: dict) -> None:
    """The same root-relative `./...` trap applies to govulncheck and the integration job."""
    text = WORKFLOW.read_text(encoding="utf-8")
    for job_name in ("dependency-scan", "integration"):
        job = (workflow.get("jobs") or {}).get(job_name) or {}
        scripts = "\n".join(str(s.get("run", "")) for s in (job.get("steps") or []))
        scripts += "\n".join(
            str(s.get("with", {}).get("go-package", "")) for s in (job.get("steps") or [])
        )
        assert not re.search(r"go[- ](?:vet|test|build)[^\n]*\s\./\.\.\.", scripts), (
            f"job {job_name!r} uses a root-relative Go package pattern, which does not "
            f"match any module in this workspace"
        )


def test_the_go_vulnerability_scan_runs_inside_a_module_and_can_fail(workflow: dict) -> None:
    """WI-176. The Go vulnerability scan could never run, and never said so.

    govulncheck resolves exactly one module, rooted at the directory it is invoked from, and exits
    1 with "no go.mod file" when that directory has no go.mod. This repository has go.work at the
    root and no root go.mod, so the scan cannot be driven from the checkout root at all. The
    previous wiring used `golang/govulncheck-action`, which runs `govulncheck -C . <patterns>` at
    the root, so every run failed that way and no Go code was ever scanned.

    It stayed invisible because a gate that always errors produces no findings to review. EV-014
    records the scan as configuration-only and never observed, which is exactly the caveat a broken
    gate generates about itself, and no finding ever contradicted it.

    These assertions encode the structure that makes the scan able to run. They are deliberately
    static: they need no network and no scanner, so they hold in every job. The behaviour - that
    the step exits non-zero when a module reports a vulnerability, and keeps scanning afterwards -
    is proved by execution in scripts/prove_vuln_scan_gate.py, which runs this same committed
    `run:` block against a fake scanner.
    """
    job = (workflow.get("jobs") or {}).get("dependency-scan") or {}
    steps = job.get("steps") or []
    runs = "\n".join(str(s.get("run", "")) for s in steps)
    uses = "\n".join(str(s.get("uses", "")) for s in steps)

    assert "govulncheck-action" not in uses, (
        "golang/govulncheck-action runs `govulncheck -C .` at the checkout root, which cannot work "
        "in a workspace with no root go.mod; invoke govulncheck once per module instead"
    )

    install = re.search(r"go install\s+golang\.org/x/vuln/cmd/govulncheck@(\S+)", runs)
    assert install, (
        "with the action gone, the job must install govulncheck itself or the scan step runs "
        "against a binary that is not there"
    )
    assert install.group(1) != "latest", (
        "govulncheck must be pinned to an exact version; @latest lets the scanner's behaviour, "
        "and therefore the finding set, change under a commit that changed nothing"
    )

    # govulncheck's own module resolution is the defect, so the module list has to come from the
    # Go toolchain rather than a regex over go.work.
    assert re.search(r"go work edit -json.*DiskPath", runs, re.DOTALL), (
        "the module list must come from `go work edit -json`; parsing go.work with a regex "
        "captures the literal '(' from the `use (...)` block and scans nothing"
    )
    assert re.search(r'govulncheck\s+-C\s+"\$m"', runs), (
        "govulncheck must be invoked with -C naming each module, because it resolves one module "
        "rooted at its working directory; scanning from the repository root is the original bug"
    )
    assert re.search(r"done < modules\.txt", runs), (
        "the scan must iterate the resolved module list, so a module added to go.work is scanned "
        "with no workflow edit"
    )

    # A scan over zero modules is a pass over nothing.
    assert "refusing to run an empty scan" in runs, (
        "the scan must fail when go.work resolves to zero modules, otherwise it reports success "
        "having scanned no code"
    )

    # So is a scan whose module list is absent. `done < modules.txt` fails its redirect when the
    # file is missing, and without errexit the loop body simply never runs: status stays 0 and the
    # step exits 0 having scanned nothing. This is the original defect class reintroduced one step
    # removed, and it is only unreachable while the resolve step happens to run first in the same
    # directory - the same invisibility as the original bug.
    assert re.search(r'\[ ! -s modules\.txt \]', runs), (
        "the scan must refuse a missing or empty modules.txt before iterating it; `done < modules.txt` "
        "fails its redirect silently under a step without errexit, so the step exits 0 having scanned "
        "nothing"
    )
    assert "refusing to report a clean scan" in runs, (
        "that refusal must say what it is refusing, so an operator reading the log is not left to "
        "work out whether an empty result meant no code or no modules"
    )
    assert re.search(r"set -euo pipefail", runs), (
        "the step needs errexit for everything that is not the scanner itself; otherwise a typo in "
        "any other line of the block fails silently and the step reports success"
    )

    # Aggregating failures so every module is scanned must not discard the failure.
    assert re.search(r'govulncheck[^\n]*\|\|', runs), (
        "the step must tolerate a failing module so the remaining modules are still scanned, and "
        "that requires an explicit `||` branch; a bare invocation under `set -e` stops at the "
        "first affected module"
    )
    assert re.search(r'status=1', runs) and re.search(r'exit "\$status"', runs), (
        "the step must record a failing module and exit with that status; a status variable that "
        "is never read makes the aggregation a pass"
    )

    assert "prove_vuln_scan_gate.py" in runs, (
        "the behavioural proof must run in CI: a static assertion cannot tell a gate that blocks "
        "from one that reports success after scanning everything"
    )


def test_integration_job_fails_if_the_live_migration_tests_skipped(workflow: dict) -> None:
    """WI-175. A skip in a live-database package means those tests verified nothing.

    `disposableDSN` and its equivalents skip when DATABASE_URL is absent, and `go test` prints
    "ok" either way. Those tests carry no build tag, so they compile into the `go` job too -
    which has no database and reported a clean package result having executed none of them. The
    `go` job genuinely has no database, so skipping there is correct; what is not acceptable is
    that the one job which does have a database proves nothing about it.

    The integration job already asserts DATABASE_URL is set and reachable, so a skip there
    cannot mean "no database configured" - it can only mean the enforcement itself is broken.
    Asserted here because a CI step that nothing verifies is the same class of defect as the
    skip it was added to catch.
    """
    job = (workflow.get("jobs") or {}).get("integration") or {}
    steps = job.get("steps") or []
    script = "\n".join(str(s.get("run", "")) for s in steps)

    # All three packages that skip without a database, not just the one the defect was filed
    # against. WI-175's fourth criterion asks for the same reporting everywhere it applies, and
    # a check that covered only cmd/migrate would leave migrate and integration able to skip
    # silently in exactly the same way.
    for package in (
        "./services/control-plane/cmd/migrate/...",
        "./services/control-plane/migrate/...",
        "./services/control-plane/integration/...",
    ):
        assert package in script, f"the skip check does not cover {package}"

    assert "grep -q '^--- SKIP'" in script, (
        "the integration job must fail when a live test skips; without a skip check this step "
        "is the very failure mode it was written to prevent"
    )
    # `-v` is not optional: without it `go test` does not print the `--- SKIP` lines this
    # check greps for, so the step would pass having detected nothing.
    assert re.search(r"go test[^\n]*-v", script), (
        "the skip check needs `go test -v`; without -v there are no `--- SKIP` lines to find"
    )
    # And the refusal must be a failure, not a warning.
    assert re.search(r"grep -q '\^--- SKIP'; then(?:.|\n)*?exit 1", script), (
        "a detected skip must exit non-zero; an annotation alone would not fail the job"
    )


def test_every_skip_in_the_live_database_packages_is_a_database_skip() -> None:
    """The CI step fails on *any* skip, which is only sound if every skip there is a DB skip.

    If a package in that list ever grows a legitimate skip - an unsupported platform, a
    timing-dependent case - the job would start failing for a reason unrelated to the
    invariant it exists to protect, and the fix would be to weaken the check. So the premise
    is asserted rather than trusted, and adding a real skip means writing down why it is
    allowed here.
    """
    repo = REPO_ROOT
    for package in ("cmd/migrate", "migrate", "integration"):
        for test_file in (repo / "services" / "control-plane" / package).glob("*_test.go"):
            source = test_file.read_text(encoding="utf-8-sig")
            for number, line in enumerate(source.splitlines(), start=1):
                stripped = line.strip()
                if not stripped.startswith("t.Skip"):
                    continue
                assert "DATABASE_URL" in stripped, (
                    f"{test_file.relative_to(repo)}:{number} skips for a reason other than a "
                    f"missing DATABASE_URL ({stripped!r}). The CI skip check fails on any skip "
                    f"in this package, so this either needs an exemption written down there or "
                    f"a narrower check"
                )


def test_pull_request_job_checkpoints_are_all_required_gates(workflow: dict) -> None:
    """docs/09 lists the every-merge gates; each must be a real job."""
    jobs = workflow.get("jobs") or {}
    for required in (
        "toolchain",  # formatting-adjacent drift gate
        "go",  # formatting + unit
        "web",  # lint + build
        "contracts",  # contract validation
        "sast",
        "dependency-scan",
        "spec-gate",  # docs/11 G0 integrity
    ):
        assert required in jobs, f"docs/09 requires a {required} gate on every merge"

    # The protected-branch extras must be conditional on main, not unconditional.
    for protected_job in ("integration", "artifact"):
        assert protected_job in jobs, f"docs/09 requires {protected_job} on protected branches"
        job = jobs[protected_job]
        condition = str(job.get("if", ""))
        assert "refs/heads/main" in condition, (
            f"{protected_job} must be restricted to the protected branch; got if: {condition!r}"
        )
        assert "github.event_name == 'push'" in condition, (
            f"{protected_job} must not run on pull requests; got if: {condition!r}"
        )


def test_supply_chain_jobs_emit_sbom_and_provenance(workflow: dict) -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "sbom" in text.lower(), "docs/02 section 10 requires an SBOM per artifact"
    assert "cosign attest" in text, "docs/02 section 10 requires provenance attestation"
    # Attestation must bind a real digest, not a mutable tag.
    assert "IMAGE_DIGEST" in text and "steps.build.outputs.digest" in text, (
        "provenance must attest the immutable digest produced by the build step"
    )


def test_artifact_job_does_not_push(workflow: dict) -> None:
    """A CI run is not authorisation to deploy; promotion is a separate gated step."""
    artifact = (workflow.get("jobs") or {}).get("artifact") or {}
    for step in artifact.get("steps") or []:
        if str(step.get("uses", "")).startswith("docker/build-push-action"):
            assert step.get("with", {}).get("push") is False, (
                "the protected-branch build must not push; promotion is environment-gated"
            )
            assert step.get("id") == "build", (
                "the build step needs id 'build' for its digest to be attestable"
            )


def test_service_container_images_are_pinned_to_exact_tags(workflow: dict) -> None:
    """Registry pulls must name an explicit version, never `latest`.

    Only `jobs.<id>.services.<name>.image` is checked. An `image:` key on a step input
    (for example the SBOM action's `image:`, which names a locally built artifact) is a
    reference to something this workflow just produced, not a registry pull, and pinning
    it to a version tag would be meaningless.
    """
    for job_name, job in (workflow.get("jobs") or {}).items():
        for svc_name, svc in ((job or {}).get("services") or {}).items():
            image = (svc or {}).get("image")
            if not image:
                continue
            assert ":latest" not in image, (
                f"job {job_name!r} service {svc_name!r} uses floating tag {image!r}"
            )
            assert re.search(r":v?\d+\.\d+", image), (
                f"job {job_name!r} service {svc_name!r} image {image!r} is not pinned to "
                f"an explicit version tag"
            )


def test_scanner_container_image_is_pinned(workflow: dict) -> None:
    """The secret scanner runs as a container; it must be pinned like any other dependency."""
    text = WORKFLOW.read_text(encoding="utf-8")
    pulls = re.findall(r"zricethezav/gitleaks:(\S+)", text)
    assert pulls, "expected the gitleaks container image to be referenced"
    for ref in set(pulls):
        assert re.match(r"^v\d+\.\d+\.\d+$", ref), (
            f"gitleaks image tag {ref!r} must be an exact release version"
        )


def test_every_job_has_a_timeout(workflow: dict) -> None:
    """A hung job is an unbounded runner cost and a stalled merge queue."""
    for name, job in (workflow.get("jobs") or {}).items():
        assert job.get("timeout-minutes"), f"job {name!r} has no timeout-minutes"


# ---------------------------------------------------------------------------
# Coverage completeness.
#
# The Go modules are enumerated from go.work at run time, so a new Go module is picked up
# without touching the workflow and cannot drift out of coverage. The Python workers are
# named literally, which is what makes the difference matter: a worker that is added to the
# tree and forgotten in the workflow is tested nowhere, and every gate that runs locally
# still passes.
#
# workers/backtest was exactly that. It was built under WI-140, passed every local gate, and
# was absent from this workflow's test job, its dependency scan, and its licence scan. The
# omission was invisible to every check in this file - the workflow parsed, every action was
# SHA-pinned, every job had a timeout - because each of those checks asks a question about the
# workflow that is present, and none of them asks which code the workflow is supposed to cover.
#
# These two tests are the general form of that omission.
# ---------------------------------------------------------------------------


def _python_workers() -> list[str]:
    """Every directory under workers/ that is an installable Python distribution."""
    workers = REPO_ROOT / "workers"
    if not workers.is_dir():
        return []
    return sorted(
        f"workers/{child.name}"
        for child in workers.iterdir()
        if child.is_dir() and (child / "pyproject.toml").is_file()
    )


def test_the_workflow_installs_tests_scans_and_licences_every_python_worker(
    workflow: dict,
) -> None:
    """Each worker must satisfy all four obligations, or it is not covered.

    Checking only that a worker's name appears in the workflow is too weak, and mutation
    testing is what showed it: removing the backtest test step left every check in this file
    green, because the worker was still named in the lint step, so a substring assertion passed
    on the strength of an unrelated reference. A coverage test that is satisfied by a mention is
    not testing coverage.

    The four obligations are therefore asserted separately, each against the command that
    discharges it:

    * **installed** - otherwise the worker's dependencies are absent and its imports fail;
    * **tested** - a pytest invocation over its test directory;
    * **dependency-scanned** - a pip-audit run with the worker installed;
    * **licence-scanned** - a liccheck invocation naming the worker's project.

    The first is not obviously important on its own, but it is what makes the third verifiable:
    pip-audit and liccheck inspect what is installed, so a worker that is never installed
    cannot be scanned, and a scan that silently skipped it would report clean.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    workers = _python_workers()
    assert workers, "expected at least one Python worker; discovery is not working"

    obligations: tuple[tuple[str, str], ...] = (
        ("installed", r"pip install [^\n]*{worker}"),
        ("tested", r"pytest {worker}/tests"),
        ("dependency-scanned", r"pip install [^\n]*{worker}"),
        ("licence-scanned", r"--project {worker}\b"),
    )
    for worker in workers:
        for label, template in obligations:
            assert re.search(template.format(worker=re.escape(worker)), text), (
                f"{worker} is not {label} anywhere in ci.yml. A worker that is only "
                f"partially covered is a worker that looks covered."
            )


def test_every_python_worker_has_a_release_gate(workflow: dict) -> None:
    """A worker with no entry in run_gates.py is not part of the release sweep.

    Separate from the workflow check because the two are independent obligations: a worker
    can be tested in CI and still be absent from the local gate sweep, which is how
    workers/backtest was missed in scripts/run_gates.py while being genuinely present in the
    tree. Both omissions occurred; this asserts the gate half.
    """
    gates = REPO_ROOT / "scripts" / "run_gates.py"
    if not gates.is_file():
        pytest.skip("run_gates.py not present")
    text = gates.read_text(encoding="utf-8")
    for worker in _python_workers():
        assert f'"{worker}/tests"' in text or f"'{worker}/tests'" in text, (
            f"{worker} is not exercised by any gate in scripts/run_gates.py; it is absent "
            f"from the release sweep"
        )


def _bash_gate():
    """Load scripts/check_workflow_bash.py as a module, by path.

    Loaded by explicit path rather than by putting scripts/ on sys.path, because the whole point
    of importing it is that this file and the script cannot drift: an import that resolved to some
    other check_workflow_bash anywhere on the path would defeat that, and would do it silently.

    The module is re-read on each call rather than cached in a global. It is cheap to parse, and a
    cached copy would mean a test could pass against a stale version of the gate after the gate
    itself had been edited - which is precisely the failure this consolidation is meant to end.
    """
    path = REPO_ROOT / "scripts" / "check_workflow_bash.py"
    if not path.is_file():
        pytest.skip("check_workflow_bash.py not present")
    spec = importlib.util.spec_from_file_location("_check_workflow_bash", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered for the duration of exec_module and removed after. @dataclass resolves its own
    # annotations through sys.modules[cls.__module__], so a module executed without an entry there
    # raises while the class body is being built - and the error names dataclasses internals
    # rather than the missing entry, which is a poor way to learn this.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules[spec.name]
    return module


def test_every_run_block_is_valid_bash(workflow: dict) -> None:
    """Every `run:` block must be syntactically valid bash.

    A syntax error in a step is the most expensive cheap failure available in this repository:
    it does not fail where it is written, it fails minutes into a later job on a runner, after
    the build cache is warm and the developer has moved on. It is also invisible to every other
    check in this file, all of which parse the YAML rather than the shell.

    This mirrors what scripts/check_workflow_bash.py does inside the toolchain job. It is
    duplicated here deliberately, for a specific reason: a step that runs inside CI cannot catch
    a malformed workflow, because a workflow GitHub cannot parse does not run its own jobs. The
    local suite is the only place this is caught before a push.

    What is *not* duplicated is the rule itself. The block discovery, the binary-stdin `bash -n`
    call, and the non-vacuity assertion all come from the script, imported by path. An earlier
    version reimplemented the loop here, which left two copies of one check: the pytest copy
    refused a workflow with zero `run:` blocks while the standalone script passed it, so the CI
    step only failed closed as long as some sibling step had run first. Two copies of a rule is
    one more edit than it takes for them to disagree, and they disagreed about exactly the case
    that cannot announce itself.

    The check is skipped, never failed, when bash is absent, because a missing interpreter is
    not a malformed workflow and must not be reported as one.
    """
    gate = _bash_gate()

    # Asserted before the loop rather than after: an empty result should stop the test, not run a
    # zero-iteration loop and then be noticed. The message is the gate's, so the two cannot
    # describe the same rule in different words.
    blocks = gate.collect_run_blocks(workflow)
    assert blocks, gate.VACUITY

    for block in blocks:
        result = gate.bash_syntax_check(block.script)
        assert result.returncode == 0, (
            f"{block.job}: {block.label} is not valid bash: "
            f"{result.stderr.decode('utf-8', 'replace').strip()}"
        )


def test_bash_gate_script_passes_on_the_real_workflow() -> None:
    """The standalone gate must exit zero on the workflow as committed.

    This is the script's own entry point rather than a reimplementation of it. Since the pytest
    check above now delegates to the script's functions, nothing else would notice if `main()`
    itself started failing - returning the wrong code, or reporting a failure on a valid
    workflow - and the standalone CI step is what runs it. Run as a subprocess so the exit code
    under test is the one a caller would see.
    """
    if shutil.which("bash") is None:
        pytest.skip("no bash on PATH; the run blocks were not syntax-checked")

    result = subprocess.run(
        [sys.executable, "scripts/check_workflow_bash.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "check_workflow_bash.py failed on the committed workflow:\n"
        + result.stdout[-2000:]
        + result.stderr[-2000:]
    )


@pytest.mark.parametrize(
    "workflow_yaml, reason",
    [
        ("jobs:\n  toolchain:\n    steps: []\n", "a job whose steps were emptied"),
        (
            "jobs:\n  toolchain:\n    steps:\n      - uses: actions/checkout@v4\n",
            "a job whose run: steps became uses: steps",
        ),
        ("name: ci\non: push\n", "a workflow with no jobs key at all"),
        ("jobs: {}\n", "a workflow with an empty jobs mapping"),
        ("- just\n- a\n- list\n", "a document that parses to a list, not a mapping"),
    ],
)
def test_bash_gate_script_fails_when_it_finds_no_run_blocks(
    workflow_yaml: str, reason: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Zero `run:` blocks must be a failure, in the script, not only in this file.

    The script prints "PASS (0 run: blocks parsed)" and returns 0 for a workflow it examined
    nothing in. Every shape below produces that outcome - an emptied job, a `run:` renamed to
    `uses:`, a jobs key that vanished, a mapping with no steps, even a document that is not a
    mapping at all - and in each of them the workflow's bash has not been checked by anything.

    The gate's whole value is that a syntax error in a step is caught before a runner finds it.
    If the step that would have caught it stops finding steps, it must say so rather than report
    a pass, because a pass here is indistinguishable from the workflow being fine.

    Driven in-process against a temporary workflow rather than by editing .github/workflows/ci.yml
    and restoring it, so the test cannot leave the real workflow modified if it dies partway.
    Bash is required because main() skips before this guard is reached, and a skip here would be
    the gate declining to run - which is exactly the outcome this test must not confuse with a
    verdict.
    """
    if shutil.which("bash") is None:
        pytest.skip("no bash on PATH; the run blocks were not syntax-checked")

    gate = _bash_gate()
    workflow_path = tmp_path / "no-run-blocks.yml"
    workflow_path.write_text(workflow_yaml, encoding="utf-8", newline="\n")

    original = gate.WORKFLOW
    gate.WORKFLOW = workflow_path
    try:
        exit_code = gate.main()
        output = capsys.readouterr().out
    finally:
        gate.WORKFLOW = original

    assert exit_code != 0, (
        f"check_workflow_bash.py returned 0 for {reason}. A gate that examined nothing must fail, "
        f"not report a pass. Output was:\n{output}"
    )
    assert gate.VACUITY in output, (
        f"the failure did not say why it failed: {reason}. Output was:\n{output}"
    )
    assert "PASS" not in output, f"a vacuous run still reported a pass: {reason}"


def test_bash_gate_script_passes_a_workflow_with_one_valid_run_block(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The zero-block guard must not be a blanket refusal.

    A guard added to the wrong side of a condition - `if blocks: check them` instead of
    `if not blocks: fail` - passes every test above and fails the only thing that matters. This is
    the positive control for the test above, and it is the same shape of control
    scripts/prove_bash_gate_detects.py established for `bash -n` itself.
    """
    if shutil.which("bash") is None:
        pytest.skip("no bash on PATH; the run blocks were not syntax-checked")

    gate = _bash_gate()
    workflow_path = tmp_path / "one-run-block.yml"
    workflow_path.write_text(
        "jobs:\n  toolchain:\n    steps:\n      - name: one valid block\n"
        "        run: |\n          set -euo pipefail\n          echo hello\n",
        encoding="utf-8",
        newline="\n",
    )

    original = gate.WORKFLOW
    gate.WORKFLOW = workflow_path
    try:
        exit_code = gate.main()
        output = capsys.readouterr().out
    finally:
        gate.WORKFLOW = original

    assert exit_code == 0, f"a workflow with one valid run: block was rejected. Output:\n{output}"
    assert "PASS (1 run: blocks parsed)" in output, output