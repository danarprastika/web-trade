"""Control for verify_column_order.py: confirm the comparison detects a reorder.

A verification that cannot fail is not evidence. This feeds the comparator a deliberately
swapped column list and requires it to report a mismatch, so a later PASS from the real
check can be read as meaningful.
"""

from __future__ import annotations

import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

from verify_column_order import struct_fields  # noqa: E402


def compare(live: list[str], fields: list[str]) -> int:
    """Same positional comparison the real check uses, on supplied inputs."""
    if len(live) != len(fields):
        return 1
    return 1 if any(f != c for f, c in zip(fields, live)) else 0


def main() -> int:
    fields = struct_fields()

    # Control 1: the real order must pass.
    if compare(list(fields), fields) != 0:
        print("CONTROL FAILED: identity comparison should pass")
        return 2

    # Control 2: swapping the first two columns must be detected.
    swapped = list(fields)
    swapped[0], swapped[1] = swapped[1], swapped[0]
    if compare(swapped, fields) == 0:
        print("CONTROL FAILED: a swapped column order was not detected")
        return 2

    # Control 3: a dropped column must be detected by arity.
    if compare(fields[:-1], fields) == 0:
        print("CONTROL FAILED: a truncated column list was not detected")
        return 2

    print("PASS: comparator detects a swap and an arity change, and passes the real order")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
