"""Mutation check: confirm each static test fails when the property it guards is broken.

A test that cannot fail is documentation, not a control. Each mutation breaks exactly one
property in the real artifact, runs the suite, and restores the file. The artifact is
restored in a `finally` so an interrupted run cannot leave a weakened file behind.
"""

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "infra" / "compose.yaml"
INIT = ROOT / "infra" / "postgres" / "init" / "10-environments.sh"
GITATTRIBUTES = ROOT / ".gitattributes"

MUTATIONS = [
    ("credential given a default password", COMPOSE,
     "WEBTRADE_DEV_PASSWORD:?set WEBTRADE_DEV_PASSWORD in .env}",
     "WEBTRADE_DEV_PASSWORD:-devpassword}"),
    ("isolation revoke removed", INIT,
     "REVOKE ALL ON DATABASE ${database} FROM PUBLIC;", ""),
    ("application role made superuser", INIT,
     "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE", "LOGIN SUPERUSER CREATEDB"),
    ("loopback binding widened to all interfaces", COMPOSE,
     '"127.0.0.1:${WEBTRADE_PG_PORT:-5432}:5432"',
     '"${WEBTRADE_PG_PORT:-5432}:5432"'),
    ("paper environment provisioned locally", INIT,
     "make_environment web_trade_test",
     'make_environment web_trade_paper web_trade_paper "$X" "paper"\nmake_environment web_trade_test'),
    ("isolation failure no longer aborts initialisation", INIT,
     'not isolated" >&2\n    exit 1', 'not isolated" >&2'),
    ("isolation probe result no longer gates the abort", INIT,
     'if [ "${dev_to_test}" != "FATAL" ] && ! printf \'%s\' "${dev_to_test}" | grep -q "permission denied"; then',
     "if false; then"),
    ("init directory mounted writable", COMPOSE,
     ":/docker-entrypoint-initdb.d:ro", ":/docker-entrypoint-initdb.d"),
    ("postgres image unpinned", COMPOSE, "image: postgres:17-alpine", "image: postgres:alpine"),
    ("init script converted to CRLF", INIT, "\n", "\r\n"),
    ("LF rule dropped from .gitattributes", GITATTRIBUTES,
     "*.sh text eol=lf", "# removed"),
]


def read(path: pathlib.Path) -> bytes:
    return path.read_bytes()


def write(path: pathlib.Path, data: bytes) -> None:
    path.write_bytes(data)


def main() -> int:
    # Bytes, not text. `Path.write_text` opens in text mode with universal newlines, and on
    # Windows that rewrites every LF as CRLF. A shell script that gains CRLF fails to run
    # under /bin/sh, so a text-mode mutation harness silently breaks the artifact it is
    # supposed to be checking. This exact failure happened once during development: the
    # harness restored a correct script as a broken one and the live check failed for
    # reasons that had nothing to do with the code under test.
    original = {p: read(p) for p in (COMPOSE, INIT, GITATTRIBUTES)}
    missed = 0
    try:
        for label, path, old, new in MUTATIONS:
            print(f"  ...   {label}", flush=True)
            text = original[path].decode("utf-8")
            if old not in text:
                print(f"  SKIP   {label}: anchor not found, cannot verify this test")
                missed += 1
                continue
            write(path, text.replace(old, new, 1).encode("utf-8"))
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "tests/ci/test_local_env.py", "-q", "--no-header"],
                capture_output=True, text=True, cwd=ROOT,
                # stdin closed: an inherited console handle lets a child that decides to
                # prompt block forever, which is indistinguishable from a slow test.
                stdin=subprocess.DEVNULL, timeout=300,
            )
            write(path, original[path])
            if result.returncode != 0:
                print(f"  CAUGHT {label}")
            else:
                print(f"  MISSED {label}  <-- the suite still passed with this broken")
                missed += 1
    finally:
        for path, data in original.items():
            write(path, data)

    # Prove the restore was exact rather than assuming it.
    for path, data in original.items():
        if read(path) != data:
            print(f"  ERROR  {path} was not restored byte-for-byte")
            return 1

    print()
    print("all mutations detected and all files restored byte-for-byte"
          if not missed else f"{missed} mutation(s) NOT detected")
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())
