"""One-off: pre-commit safety scan for the outstanding commit blocker.

The recorded blocker in EV-031 says the work is uncommitted, and the real figure is 236 files -
the entire platform implementation, never committed. A human is therefore about to make a
first-commit of everything. This checks that the tree is safe to commit before anyone does:
no credential-shaped literals, no private keys, no real environment files, no build artefacts.

Read-only. It does not stage, commit, or modify anything.
"""

from __future__ import annotations

import io
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Deliberately narrow: a broad "password" search matches prose, and the worker docstrings
# discuss credentials at length. These shapes have no false positives against documentation.
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("openai key", re.compile(r"\bsk-[A-Za-z0-9]{20,}")),
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}")),
    ("aws access key", re.compile(r"\bAKIA[0-9A-Z]{16}")),
    ("slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}")),
    ("google api key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}")),
    ("bearer literal", re.compile(r"[Aa]uthorization:\s*[Bb]earer\s+[A-Za-z0-9._\-]{20,}")),
)

# Files that are expected to be absent; .env.example is the sanctioned template.
FORBIDDEN_NAMES = (".env", ".env.local", ".env.production", "id_rsa", "id_ed25519")

ARTEFACT_SUFFIXES = (".pyc", ".exe", ".dll", ".so", ".dylib", ".log", ".key", ".pem", ".p12")


def git(*args: str) -> list[str]:
    out = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True)
    return [line for line in out.stdout.splitlines() if line.strip()]


def main() -> int:
    untracked = git("ls-files", "--others", "--exclude-standard")
    tracked = git("ls-files")
    candidates = untracked + tracked

    findings: list[str] = []
    for rel in candidates:
        path = REPO / rel
        if not path.is_file():
            continue
        name = path.name
        if name in FORBIDDEN_NAMES:
            findings.append(f"{rel}: forbidden file name")
        if path.suffix in ARTEFACT_SUFFIXES:
            findings.append(f"{rel}: build or secret artefact")
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for label, pattern in PATTERNS:
            if pattern.search(text):
                findings.append(f"{rel}: {label}")

    print(f"scanned {len(candidates)} paths ({len(untracked)} untracked, {len(tracked)} tracked)")
    if findings:
        print(f"\n{len(findings)} finding(s):")
        for item in findings:
            print(f"  {item}")
        return 1
    print("\nno credential-shaped literals, forbidden env files, or build artefacts found")
    print("the tree is safe to commit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
