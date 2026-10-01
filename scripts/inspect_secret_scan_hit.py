"""One-off: show the secret-scan hit in evidence.jsonl in context.

A pre-commit pattern scan flagged one line in the evidence ledger. It is almost certainly prose
describing a scan rather than a real credential, but "almost certainly" is exactly the reasoning
this repository keeps refusing to accept, so the line is read rather than assumed.
"""

import json
import re
import sys
from pathlib import Path

LEDGER = Path(".kilo/ecc/project-brain/evidence.jsonl")
PATTERN = re.compile(
    r"(?i)(api[_-]?key|secret[_-]?key|password\s*=|private[_-]?key"
    r"|BEGIN (?:RSA|OPENSSH|EC|PGP) PRIVATE KEY|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})"
)


def main() -> int:
    for raw in LEDGER.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        record = json.loads(raw)
        for field in ("claim", "method", "result", "defect_found_and_fixed", "caveats"):
            value = str(record.get(field) or "")
            for match in PATTERN.finditer(value):
                start = max(0, match.start() - 120)
                end = min(len(value), match.end() + 120)
                print(f"  {record['evidence_id']} / {field}:")
                print("    ..." + value[start:end].replace("\n", " ") + "...")
                print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
