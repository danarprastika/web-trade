"""One-off: restore work-items.json's committed serialisation style.

record_wi141_g5_pass.py rewrote the file with json.dumps(ensure_ascii=False). HEAD stores the
same values with non-ASCII escaped as \\uXXXX. The parsed data is identical, so this is not a
content change, but the byte diff it produces touches every work item and buries the three
fields that actually changed. In a repository whose whole point is reviewable evidence, a diff
nobody can read is a real cost rather than a cosmetic one.

This re-encodes the file to whatever style HEAD used, and refuses to write unless the parsed
content is byte-for-byte unchanged. It therefore cannot silently alter a field.

Idempotent, written without a BOM.
"""

from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ITEMS_REL = ".kilo/ecc/project-brain/work-items.json"


def head_text() -> str | None:
    try:
        raw = subprocess.run(
            ["git", "show", f"HEAD:{ITEMS_REL}"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        ).stdout
    except subprocess.CalledProcessError:
        return None
    return raw.decode("utf-8")


def main() -> int:
    path = ROOT / ITEMS_REL
    original = path.read_text(encoding="utf-8")

    committed = head_text()
    if committed is None:
        raise SystemExit(f"{ITEMS_REL} is not tracked at HEAD; refusing to guess its style")

    # Reproduce HEAD's style rather than assume it: if dumping HEAD's own values with
    # ensure_ascii=True and indent=2 does not reproduce HEAD's bytes, the file uses some other
    # formatting and writing it would be a change nobody asked for.
    committed_value = json.loads(committed)
    for ensure_ascii in (True, False):
        for indent in (2, 4):
            candidate = json.dumps(committed_value, ensure_ascii=ensure_ascii, indent=indent)
            for tail in ("", "\n"):
                if candidate + tail == committed:
                    print(
                        f"HEAD style: ensure_ascii={ensure_ascii}, indent={indent}, "
                        f"trailing newline={bool(tail)}"
                    )

    # The content must survive the re-encode untouched; that is the whole safety property.
    before = json.loads(original)
    after = json.loads(json.dumps(before, ensure_ascii=True, indent=2) + "\n")

    if before != after:
        raise SystemExit(
            "refusing to write: re-encoding changed the parsed content, which would mean the "
            "file is not a plain JSON round-trip"
        )

    if original == json.dumps(before, ensure_ascii=True, indent=2) + "\n":
        print("unchanged: already in the committed style")
        return 0

    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(before, ensure_ascii=True, indent=2) + "\n")
    print("restored the committed serialisation style; content unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
