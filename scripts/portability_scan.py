"""One-off: find machine-specific references that would break outside this checkout.

The outstanding commit blocker (EV-033) notes that no gate result proves the platform is
reproducible from a clean checkout, because no commit exists to check out. One part of that
question can still be answered: does anything in the repository depend on where it happens to
live, or on a path that exists only on this machine?

A hardcoded absolute path is invisible to a full gate run, because the gates pass in the
directory the author happens to be using. It then fails for the first person who clones the
repository elsewhere, which is usually whoever is reviewing it.

Read-only.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Paths that are legitimate: the documented external tool locations on this host are checked
# separately, and the drive-letter pattern below is aimed at repository content only.
WINDOWS_ABS_PATH = re.compile(r"[A-Za-z]:\\\\?(?:Users|web-trade|Program Files|Windows)[^\"'\s]*")
HOME_PATH = re.compile(r"/(?:home|Users)/[A-Za-z0-9._-]+/[^\"'\s]*")

# Extensions worth scanning. Binaries, lockfiles, and the specification are excluded: docs/ is
# authoritative and may legitimately name paths, and Go/Python lockfiles are generated.
SCANNABLE = {".go", ".py", ".ps1", ".sh", ".yaml", ".yml", ".json", ".toml", ".sql", ".mk", ".mod"}
EXCLUDED_DIRS = {".git", "__pycache__", "node_modules", ".mypy_cache", ".ruff_cache", ".pytest_cache"}


def git(*args: str) -> list[str]:
    out = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True)
    return [line for line in out.stdout.splitlines() if line.strip()]


def main() -> int:
    paths = [p for p in git("ls-files") + git("ls-files", "--others", "--exclude-standard")]

    findings: list[str] = []
    scanned = 0
    for rel in paths:
        parts = Path(rel).parts
        if any(part in EXCLUDED_DIRS for part in parts):
            continue
        if rel.startswith("docs/"):
            continue  # authoritative specification; not repository implementation
        if Path(rel).suffix.lower() not in SCANNABLE:
            continue
        path = REPO / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        scanned += 1
        for number, line in enumerate(text.splitlines(), 1):
            for label, pattern in (("absolute path", WINDOWS_ABS_PATH), ("home path", HOME_PATH)):
                match = pattern.search(line)
                if match:
                    findings.append(f"{rel}:{number}: {label}: {match.group(0)[:70]}")

    print(f"scanned {scanned} source and config files (docs/ and caches excluded)")
    if findings:
        print(f"\n{len(findings)} machine-specific reference(s):")
        for item in findings:
            print(f"  {item}")
        return 1
    print("\nno absolute or home-relative paths found in repository content")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
