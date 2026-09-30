"""Static checks on the operator console image definition.

The container build cannot be exercised locally while the Docker daemon is unavailable
(BLK-1), so these checks assert the properties that would otherwise only fail inside CI
or, worse, in a deployed artifact. They are deliberately narrow: they assert the supply
chain and hardening intent, not the full Docker grammar.

Run:
    python -m pytest tests/ci -q
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "apps" / "web" / "Dockerfile"
NEXT_CONFIG = REPO_ROOT / "apps" / "web" / "next.config.ts"


@pytest.fixture(scope="module")
def dockerfile() -> str:
    if not DOCKERFILE.is_file():
        pytest.skip("apps/web/Dockerfile not present")
    return DOCKERFILE.read_text(encoding="utf-8")


def test_base_images_are_pinned_to_exact_tags(dockerfile: str) -> None:
    """A floating base tag destroys artifact reproducibility (docs/02 section 10)."""
    from_lines = re.findall(r"^FROM\s+(\S+)", dockerfile, re.MULTILINE)
    assert from_lines, "no FROM instructions found"
    for image in from_lines:
        assert ":" in image, f"base image {image!r} has no explicit tag"
        tag = image.rsplit(":", 1)[1]
        assert tag != "latest", f"base image {image!r} uses a floating tag"
        assert re.search(r"\d+\.\d+", tag), f"base image {image!r} is not pinned to a version"


def test_node_base_image_matches_the_pinned_toolchain(dockerfile: str) -> None:
    """The image must build on the Node version toolchain/versions.env pins.

    A Dockerfile silently on a different Node major than the verified local toolchain
    would make the CI build and the developer's build different products.
    """
    versions = (REPO_ROOT / "toolchain" / "versions.env").read_text(encoding="utf-8")
    match = re.search(r"^NODE_VERSION=(\S+)", versions, re.MULTILINE)
    assert match, "NODE_VERSION not declared in toolchain/versions.env"
    node_version = match.group(1)
    for image in re.findall(r"^FROM\s+node:(\S+)", dockerfile, re.MULTILINE):
        assert image.startswith(node_version), (
            f"Dockerfile uses node:{image} but toolchain/versions.env pins {node_version}"
        )


def test_build_stage_is_discarded_and_runtime_runs_as_non_root(dockerfile: str) -> None:
    """Multi-stage with a non-root runtime keeps devDependencies out of the artifact.

    docs/02 section 10 excludes development convenience dependencies from production
    artifacts, and docs/06 section 4 forbids credentials and privilege in the image.
    """
    stages = re.findall(r"^FROM\s+\S+\s+AS\s+(\S+)", dockerfile, re.MULTILINE | re.IGNORECASE)
    assert "build" in stages, "expected a named build stage"
    assert "runtime" in stages, "expected a named runtime stage"
    assert stages[-1] == "runtime", (
        f"the final stage must be the runtime stage, got {stages[-1]!r}; "
        f"an accidentally last build stage would ship build tooling"
    )
    assert re.search(r"^USER\s+(?!root)\S+", dockerfile, re.MULTILINE), (
        "runtime stage must drop to a non-root USER"
    )


def test_dependencies_install_from_the_lockfile_only(dockerfile: str) -> None:
    """`npm ci` is the lockfile-drift gate; `npm install` would bypass it."""
    ci_lines = [line for line in dockerfile.splitlines() if re.search(r"\bnpm\s+ci\b", line)]
    assert ci_lines, "expected an `npm ci` install step"
    assert not re.search(r"\bnpm\s+install\b", dockerfile), (
        "`npm install` resolves floating versions and must not appear in the image build"
    )
    assert re.search(r"COPY\s+package\.json\s+package-lock\.json", dockerfile), (
        "package-lock.json must be copied into the build stage or npm ci cannot verify the graph"
    )


def test_no_secrets_or_credentials_are_baked_in(dockerfile: str) -> None:
    """docs/06 section 4: no credentials embedded in container images."""
    for line in dockerfile.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for pattern in (r"\bARG\s+.*(SECRET|TOKEN|PASSWORD|KEY)", r"\bENV\s+.*(SECRET|TOKEN|PASSWORD)="):
            assert not re.search(pattern, stripped, re.IGNORECASE), (
                f"Dockerfile appears to define a credential: {stripped!r}"
            )


def test_copy_sources_exist_in_the_build_context(dockerfile: str) -> None:
    """A COPY from a path the build never produces fails the image build.

    The failure mode this guards against is subtle: `public/` does not exist in the
    scaffold, so a `COPY ... /app/public` would break the build only once someone adds
    static assets, or immediately, depending on how the context is assembled.
    """
    known_present = {
        "package.json",
        "package-lock.json",
        ".",  # the whole context
    }
    for source in re.findall(r"^COPY\s+--from=build\s+(?:--chown=\S+\s+)?(\S+)", dockerfile, re.MULTILINE):
        # Sources are absolute within the build stage, e.g. /app/.next/standalone.
        # Strip the leading slash and the WORKDIR prefix so the comparison is against
        # build-context-relative names.
        normalised = source.lstrip("/")
        if normalised.startswith("app/"):
            normalised = normalised[len("app/") :]
        # `.next/...` paths are build outputs, not source files, so they are checked
        # against the Next.js configuration below rather than the source tree.
        if normalised.startswith(".next/"):
            continue
        assert normalised in known_present, (
            f"Dockerfile copies {source!r}, which is not present in the build context"
        )


def test_standalone_output_is_enabled(dockerfile: str) -> None:
    """The runtime stage copies `.next/standalone`; the config must produce it."""
    assert re.search(r"^COPY\s+--from=build.*\.next/standalone", dockerfile, re.MULTILINE), (
        "runtime stage expects standalone output"
    )
    if not NEXT_CONFIG.is_file():
        pytest.skip("next.config.ts not present")
    config = NEXT_CONFIG.read_text(encoding="utf-8")
    assert re.search(r"output\s*:\s*[\"']standalone[\"']", config), (
        "next.config.ts must set output: 'standalone' for the Dockerfile's runtime stage "
        "to have a self-contained server to copy"
    )
