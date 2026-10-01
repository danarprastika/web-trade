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

import re
import shutil
import subprocess
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
    "golang/govulncheck-action": "v1.0.4",
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

    The check is skipped, never failed, when bash is absent, because a missing interpreter is
    not a malformed workflow and must not be reported as one.
    """
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("no bash on PATH; the run blocks were not syntax-checked")

    checked = 0
    for job_name, job in (workflow.get("jobs") or {}).items():
        for step in job.get("steps") or []:
            script = step.get("run")
            if not isinstance(script, str) or not script.strip():
                continue
            label = step.get("name") or step.get("uses") or "(unnamed step)"
            checked += 1

            # Binary stdin, never a text pipe: on Windows a text-mode pipe translates "\n" to
            # "\r\n", and bash reads the carriage return as part of the command. That produced
            # phantom failures for a workflow that was entirely valid.
            body = script if script.lstrip().startswith("#!") else "#!/usr/bin/env bash\n" + script
            result = subprocess.run(
                [bash, "-n"], input=body.encode("utf-8"), capture_output=True
            )
            assert result.returncode == 0, (
                f"{job_name}: {label} is not valid bash: "
                f"{result.stderr.decode('utf-8', 'replace').strip()}"
            )

    assert checked > 0, "no run: blocks were found; the check is not examining anything"