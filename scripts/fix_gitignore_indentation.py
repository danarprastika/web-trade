"""One-off: de-indent the final section of .gitignore.

Every non-blank line in the last section carries two leading spaces. In a .gitignore a leading
space is not formatting: it is part of the pattern, so `  .kilo/ecc/project-brain/*.tmp` matches a
file whose name literally begins with two spaces and nothing else. Those two patterns have never
worked - Project Brain scratch files were never actually ignored - and the same mistake is why a
newly added `_driver_probe/` rule matched nothing.

Comments with leading spaces are harmless, so this de-indents all non-blank indented lines and
leaves whitespace-only lines alone. Only lines 70-81 are affected; lines 1-69 have no leading
whitespace and are not touched.

Verified after running: git check-ignore matches each de-indented pattern, and a file that should
be ignored is.

Idempotent, written without a BOM, preserves the file's existing encoding byte for byte apart
from the removed leading whitespace.
"""

from __future__ import annotations

import io
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IGNORE = ROOT / ".gitignore"


def deindent() -> bool:
    raw = IGNORE.read_bytes().decode("utf-8")
    trailing_newline = raw.endswith("\n")
    lines = raw.split("\n")
    if trailing_newline:
        lines = lines[:-1]

    changed = False
    out = []
    for number, line in enumerate(lines, start=1):
        if line.strip() == "":
            # A whitespace-only line carries no pattern, so it is left exactly as found rather
            # than tidied, keeping the diff to the lines that were actually wrong.
            out.append(line)
            continue
        stripped = line.lstrip(" \t")
        if stripped != line:
            out.append(stripped)
            changed = True
        else:
            out.append(line)

    if not changed:
        print("unchanged: no indented patterns remain")
        return False

    payload = "\n".join(out) + ("\n" if trailing_newline else "")
    with io.open(IGNORE, "w", encoding="utf-8", newline="") as handle:
        handle.write(payload)
    print(f"de-indented .gitignore; {len(out)} lines written")
    return True


if __name__ == "__main__":
    deindent()
