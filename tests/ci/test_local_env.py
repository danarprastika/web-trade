"""Static checks on the local PostgreSQL stack definition.

WI-108's second criterion — no credential in the repository — is a property of the committed
tree, so it is asserted here rather than in the live check. The live check in
`scripts/verify_local_env.py` proves the stack comes up healthy and that the environments are
genuinely isolated; it needs a running Docker daemon, so it cannot run in every CI context.
These checks run anywhere.

The properties asserted are the ones that fail silently. A stack that starts with a default
password, or that lets every role reach every database, both work perfectly well on a
developer's machine right up until the moment they matter.

Run:
    python -m pytest tests/ci -q
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "infra" / "compose.yaml"
INIT_SCRIPT = REPO_ROOT / "infra" / "postgres" / "init" / "10-environments.sh"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
GITIGNORE = REPO_ROOT / ".gitignore"

SECRET_VARS = [
    "WEBTRADE_PG_SUPERUSER_PASSWORD",
    "WEBTRADE_DEV_PASSWORD",
    "WEBTRADE_TEST_PASSWORD",
]

# Environments that exist somewhere in the platform but must never be provisioned by a local
# stack: live is out of scope entirely, and a local paper or shadow database would create the
# impression of a lower-fidelity live environment running on a laptop.
NON_LOCAL_DATABASES = ["paper", "shadow", "live"]


@pytest.fixture(scope="module")
def compose() -> str:
    if not COMPOSE_FILE.is_file():
        pytest.skip("infra/compose.yaml not present")
    return COMPOSE_FILE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def init_script() -> str:
    if not INIT_SCRIPT.is_file():
        pytest.skip("infra/postgres/init/10-environments.sh not present")
    return INIT_SCRIPT.read_text(encoding="utf-8")


def test_every_credential_is_required_with_no_default(compose: str) -> None:
    """`${VAR:?message}` is the mechanism, and `:-` is the failure.

    PostgreSQL's image refuses to initialise without POSTGRES_PASSWORD, but the failure then
    arrives as an opaque container log rather than a named missing variable, and nothing stops
    someone from satisfying it with a default written into the compose file. A default there is
    a credential in the repository, which is the thing this whole file exists to prevent.
    """
    for name in SECRET_VARS:
        modifiers = re.findall(r"\$\{" + name + r"(:[-?][^}]*)?\}", compose)
        assert modifiers, (
            f"{name} is not referenced at all in the compose file; expected "
            f"${{{name}:?message}} so the stack refuses to start without it"
        )
        for modifier in modifiers:
            assert modifier.startswith(":?"), (
                f"{name} uses {modifier or 'a bare reference'} rather than ':?'; a defaulting "
                f"or silent modifier lets the stack start without a supplied credential"
            )


def test_no_credential_has_a_literal_value(compose: str) -> None:
    """A credential name may appear only inside an interpolation, never beside a value.

    Stated as a removal rather than as a left-hand-side capture because the name legitimately
    appears on both sides: `POSTGRES_PASSWORD: ${WEBTRADE_PG_SUPERUSER_PASSWORD:?set ...}`
    uses it as the value of one variable and as the source of another. Removing every
    `${NAME...}` interpolation and then finding the name in what remains is the one formulation
    that catches a literal wherever it appears.
    """
    for line in compose.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for name in SECRET_VARS:
            # The name is legitimate as the compose key, and legitimate inside an
            # interpolation. Anything left over is the name sitting beside a value.
            residual = re.sub(r"^" + name + r"\s*:", "", stripped)
            residual = re.sub(r"\$\{" + name + r"(:[-?][^}]*)?\}", "", residual)
            assert name not in residual, (
                f"{name} appears beside a literal value rather than only as a compose key or an "
                f"environment reference: {stripped!r}"
            )


def test_env_example_declares_every_variable_empty() -> None:
    """`.env.example` documents the contract without supplying a usable secret.

    An example file that ships a working password is the most common way a real credential
    enters a repository, because the value gets copied into `.env` unchanged.
    """
    if not ENV_EXAMPLE.is_file():
        pytest.skip(".env.example not present")
    example = ENV_EXAMPLE.read_text(encoding="utf-8")
    for name in SECRET_VARS:
        assert re.search(rf"^{name}=\s*$", example, re.MULTILINE), (
            f"{name} must be declared in .env.example with an empty value"
        )
    # A connection string carrying a non-empty password is the same leak by another route.
    for line in example.splitlines():
        if line.strip().startswith("#"):
            continue
        match = re.match(r"^\s*\w*DATABASE_URL=(\S+)", line)
        if match:
            assert ":@" in match.group(1), (
                f"a connection string in .env.example carries a password: {line!r}"
            )


def test_gitignore_excludes_the_real_env_file() -> None:
    """`.env` must never be committable, and its absence is asserted, not assumed."""
    if not GITIGNORE.is_file():
        pytest.skip(".gitignore not present")
    patterns = [
        line.strip().lstrip("/")
        for line in GITIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert ".env" in patterns, f".gitignore does not exclude .env; entries: {patterns}"
    assert not (REPO_ROOT / ".env").exists(), (
        "a populated .env exists in the working tree; it must be removed and never committed"
    )


def test_image_is_pinned_and_published_only_to_loopback(compose: str) -> None:
    """A floating tag breaks reproducibility; a published port wider than loopback exposes it.

    docs/02 section 10 requires pinned images, and a development database published on all
    interfaces would be reachable from the network with a password that is a throwaway.
    """
    image = re.search(r"^\s*image:\s*(\S+)", compose, re.MULTILINE)
    assert image, "no image declared for the postgres service"
    reference = image.group(1)
    assert ":" in reference and not reference.endswith(":latest"), (
        f"postgres image {reference!r} is not pinned to an explicit non-latest tag"
    )
    assert re.search(r"^\s*image:\s*postgres:17", compose, re.MULTILINE), (
        f"docs/05 names PostgreSQL 17 as the system of record, but the stack uses {reference!r}"
    )
    # The ports block is parsed line by line rather than scanned for IP-shaped lines.
    # Scanning for the pattern looks equivalent and is not: a binding widened to all
    # interfaces contains no literal IP, matches nothing, and is skipped — which is exactly
    # the case this exists to catch. A single regex over the block is also wrong, because the
    # block carries a comment line and a comment breaks the run of list items. Every entry
    # must therefore be enumerated, and each must name a loopback host.
    lines = compose.splitlines()
    start = next((i for i, l in enumerate(lines) if re.match(r"^\s*ports:\s*$", l)), None)
    assert start is not None, "no ports block found; the published port is not bound to loopback"
    entries = []
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.match(r"^\s*-\s+(\S+)", line)
        if not match:
            break  # dedented out of the ports block
        entries.append(match.group(1).strip("\"'"))
    assert entries, "the ports block is empty"
    for entry in entries:
        assert entry.startswith("127.0.0.1:"), (
            f"port mapping {entry!r} is not bound to 127.0.0.1; a development database "
            f"published on all interfaces is reachable from the network"
        )


def test_init_script_creates_one_role_and_database_per_environment(init_script: str) -> None:
    """Each environment gets its own role and its own database, not a shared one.

    The calls are positional — `make_environment <role> <database> <password> <label>` — so the
    role and database are asserted as the first two arguments of each call rather than by
    name, which would only prove the function body mentions them somewhere.
    """
    calls = re.findall(r"^make_environment\s+(\S+)\s+(\S+)\s", init_script, re.MULTILINE)
    assert calls, "no make_environment calls found; no environment would be created"
    for role, database in (("web_trade_dev", "web_trade_dev"), ("web_trade_test", "web_trade_test")):
        assert (role, database) in calls, (
            f"expected make_environment {role} {database}; found {calls}"
        )


def test_application_roles_are_created_without_superuser_privileges(init_script: str) -> None:
    """A migration that needs superuser would mean production lacks permissions it needs.

    The role is verified here at creation time rather than only in a live check, because
    `NOSUPERUSER NOCREATEDB NOCREATEROLE` written in the script is the control; a later edit
    that drops a clause is a privilege escalation that is invisible in a smoke test.

    Comments are stripped first. The script explains the reasoning in prose that names
    `CREATE ROLE`, and matching a comment would capture text from the `psql` invocation that
    follows it — which is how an earlier version of this check reported a false failure
    against a correct script.
    """
    without_comments = "\n".join(
        line for line in init_script.splitlines() if not line.strip().startswith("#")
    )
    create = re.search(r"CREATE ROLE\s+(\S+)([^;]*);", without_comments, re.DOTALL)
    assert create, "no CREATE ROLE statement found"
    attributes = create.group(2).upper()
    for clause in ("NOSUPERUSER", "NOCREATEDB", "NOCREATEROLE"):
        assert clause in attributes, (
            f"application role is missing {clause}: CREATE ROLE{create.group(2).strip()}"
        )
    assert "SUPERUSER" not in attributes.replace("NOSUPERUSER", ""), (
        "the application role is created with SUPERUSER"
    )


def test_init_script_revokes_connect_from_public_and_grants_only_the_owner(init_script: str) -> None:
    """PostgreSQL grants CONNECT to PUBLIC by default, so isolation must be revoked.

    The pattern here is revoke-from-everyone then grant-to-one-role, which is stronger than
    revoking per pair: any role that did not exist when the script ran is excluded too. What
    must never appear is a GRANT of CONNECT to a second role, or to PUBLIC.
    """
    assert re.search(r"REVOKE\s+ALL\s+ON\s+DATABASE\s+\$\{database\}\s+FROM\s+PUBLIC", init_script, re.IGNORECASE), (
        "no REVOKE ... FROM PUBLIC on the database; every role can reach it by default"
    )
    grants = re.findall(r"GRANT\s+CONNECT[^;]*?TO\s+([^;]+);", init_script, re.IGNORECASE)
    assert grants, "no explicit GRANT of CONNECT after the revoke; the owner would be locked out"
    for grantee in grants:
        assert grantee.strip() == "${role}", (
            f"CONNECT is granted to {grantee.strip()!r}; only the owning role may connect"
        )
    assert not re.search(r"GRANT\s+CONNECT[^;]*?TO\s+PUBLIC", init_script, re.IGNORECASE), (
        "CONNECT is granted to PUBLIC, which defeats the isolation"
    )


def test_init_script_asserts_its_own_isolation(init_script: str) -> None:
    """The script must verify the isolation it claims, not merely perform it.

    The revoke statements prove the intent. This assertion proves the effect, and it sits
    while the roles exist, which is the only moment it is cheap. Both halves matter: the
    probes and the `exit 1` that follows them. A script that probes and then continues would
    report a broken stack as healthy, which is the failure mode a warning cannot survive.
    """
    for role, database in (("web_trade_dev", "web_trade_test"), ("web_trade_test", "web_trade_dev")):
        assert re.search(rf"--username\s+{role}\s+--dbname\s+{database}", init_script), (
            f"the script does not test that {role} is refused by {database}"
        )
    # Each failure message must be followed by an abort. Requiring only that some `exit 1`
    # exists is satisfied by the second direction alone, so removing the first direction's
    # abort would still pass — a half-enforced control is easy to mistake for an enforced one.
    aborting = re.findall(r'not isolated" >&2\s*\n\s*exit 1', init_script)
    assert len(aborting) == 2, (
        f"expected both isolation failures to abort initialisation, found {len(aborting)} "
        f"aborting block(s) of 2"
    )
    # The probe result must gate the abort. Checking that the probe exists and that an `exit 1`
    # exists is not enough on its own: replacing the condition with `if false` leaves both in
    # place while making the check permanently pass, which reports a broken stack as healthy.
    captures = re.findall(r'^(\w+)="\$\(psql', init_script, re.MULTILINE)
    assert len(captures) == 2, (
        f"expected one captured probe per direction, found {captures}"
    )
    for name in captures:
        assert re.search(rf'if \[ [^\n]*\$\{{{name}\}}', init_script), (
            f"probe result {name!r} is captured but never tested in a condition, so the "
            f"isolation check cannot fail"
        )


def test_init_script_does_not_provision_non_local_environments(init_script: str) -> None:
    """Paper, shadow, and live must not be creatable from the local stack."""
    calls = re.findall(r"^make_environment\s+(\S+)\s+(\S+)\s", init_script, re.MULTILINE)
    for role, database in calls:
        for environment in NON_LOCAL_DATABASES:
            assert environment not in (role, database), (
                f"the local stack provisions a {environment} environment; "
                f"only dev and test are local"
            )
    assert len(calls) == 2, f"expected exactly dev and test, found {calls}"


def test_init_script_uses_unix_line_endings() -> None:
    """CRLF in the init script is a broken init script, and the failure is far from the cause.

    A carriage return is read by /bin/sh as part of the command, so `set -eu\\r` aborts the
    script before it creates a single role. What a developer sees is a container that reports
    itself unhealthy, which points at PostgreSQL rather than at line endings.

    This is not a hypothetical. A test harness that rewrote the script through a text-mode
    write on Windows produced exactly this, and every static check kept passing while the live
    stack failed. `.gitattributes` pins the checkout, and this asserts the file on disk.
    """
    if not INIT_SCRIPT.is_file():
        pytest.skip("init script not present")
    raw = INIT_SCRIPT.read_bytes()
    assert b"\r\n" not in raw, (
        f"{INIT_SCRIPT.name} contains CRLF line endings; it must be LF for /bin/sh. "
        f"Found {raw.count(bytes([13, 10]))} CRLF sequence(s)."
    )
    assert raw.startswith(b"#!/bin/sh\n"), (
        f"{INIT_SCRIPT.name} must start with a /bin/sh shebang on an LF line"
    )


def test_line_endings_are_pinned_for_executable_and_data_files() -> None:
    """`.gitattributes` must pin LF, so a Windows checkout cannot produce a broken script.

    Without this the file on disk depends on each developer's `core.autocrlf` setting, and the
    defect appears only for the people whose machines are configured the other way.
    """
    attributes = REPO_ROOT / ".gitattributes"
    if not attributes.is_file():
        pytest.skip(".gitattributes not present")
    text = attributes.read_text(encoding="utf-8")
    assert re.search(r"^\*\.sh\s+text\s+eol=lf", text, re.MULTILINE), (
        "*.sh must be pinned to LF in .gitattributes"
    )
    assert "* text=auto eol=lf" in text, (
        "a default LF rule is required so new files do not depend on autocrlf"
    )


def test_init_script_is_actually_mounted_into_the_container(compose: str) -> None:
    """A correct init script that is never mounted changes nothing.

    The whole directory is mounted rather than the individual file, so this asserts the mount
    source is the directory the script actually lives in. Every other check in this file would
    still pass — against a script that never runs — if the path were wrong or the directory
    were omitted from the compose file entirely.
    """
    assert "/docker-entrypoint-initdb.d" in compose, (
        "the postgres service mounts no initdb.d directory; no role would ever be created"
    )
    mount = re.search(r"-\s+(\S+):/docker-entrypoint-initdb\.d:ro", compose)
    assert mount, (
        "the initdb.d mount is absent or not read-only; a writable mount lets a process in "
        "the container rewrite the isolation this stack depends on"
    )
    mounted_source = (COMPOSE_FILE.parent / mount.group(1)).resolve()
    assert mounted_source == INIT_SCRIPT.parent.resolve(), (
        f"compose mounts {mount.group(1)} but the init script lives in {INIT_SCRIPT.parent}"
    )
    assert INIT_SCRIPT.is_file(), f"{INIT_SCRIPT} does not exist, so the mount is empty"
