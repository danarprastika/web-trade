"""One-off: generate valid 64-char sha-256 digests for the model package test constants.

The literals previously in lifecycle_test.go were 63 characters, so Digest.Valid rejected
them. The rejection was correct; the constants were wrong. A digest that is one character
short is exactly the truncation the validation exists to catch, so the fix is to use real
sha-256 outputs rather than to loosen the check.
"""

from __future__ import annotations

import hashlib

NAMES = [
    "dataset",
    "eval",
    "rollback",
    "approval",
    "prompt",
    "context",
    "result",
    "args",
    "artifact",
]


def main() -> int:
    for name in NAMES:
        digest = hashlib.sha256(f"webtrade-wi141-{name}".encode()).hexdigest()
        print(f'\tdigest{name.capitalize():<9} = Digest("{digest}")')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
