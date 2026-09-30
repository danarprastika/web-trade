"""One-off: count untracked paths by area, for the commit-blocker correction.

The recorded blocker text in EV-031 says "23 paths in the working tree are untracked or
modified". That is wrong by an order of magnitude, and a reviewer would reason about the size of
the outstanding commit from it. This produces the real figures.
"""

from __future__ import annotations

import collections
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def run(*args: str) -> list[str]:
    out = subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=True
    )
    return [line for line in out.stdout.splitlines() if line.strip()]


def main() -> int:
    tracked = run("ls-files")
    untracked = run("ls-files", "--others", "--exclude-standard")
    modified = run("ls-files", "--modified")
    head = run("log", "--oneline", "-1")

    print(f"HEAD: {head[0]}")
    print(f"tracked:   {len(tracked)}")
    print(f"untracked: {len(untracked)}")
    print(f"modified:  {len(modified)}")

    print("\nuntracked by top-level area:")
    counts: collections.Counter[str] = collections.Counter(p.split("/", 1)[0] for p in untracked)
    for area, count in counts.most_common():
        print(f"  {count:5}  {area}")

    print("\ntracked by top-level area:")
    tcounts: collections.Counter[str] = collections.Counter(p.split("/", 1)[0] for p in tracked)
    for area, count in tcounts.most_common():
        print(f"  {count:5}  {area}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
