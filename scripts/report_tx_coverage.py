#!/usr/bin/env python3
"""Report which authoritative write paths establish a transaction. WI-199, for WI-120 AC1.

WI-120's first acceptance criterion reads "Database transactions wrap every authoritative state
transition". Nothing in the repository could answer whether that held. This reports it.

Run:  python scripts/report_tx_coverage.py

This REPORTS and does not fail. That is deliberate, and the reason is the finding rather than an
omission: a path that performs one statement is already atomic, because PostgreSQL runs each
statement in its own transaction. Adding BEGIN/COMMIT around a single INSERT changes nothing, and a
gate that demanded it would produce a green diff and no safety.

The transaction earns its existence when it has to carry more than the mutation. docs/22 section 4
requires the authoritative audit stream to be written transactionally with the business mutation, and
WI-121's outbox row is the third thing that has to be inside the same boundary. Until the outbox table
exists, "wrap these two files in a transaction" would satisfy the wording of AC1 while leaving the
boundary that matters unbuilt. WI-199 records that measurement; the criterion itself stays PENDING on
WI-120 and WI-121.

The read side of this - which query mutates, and which package may call it - is not reimplemented here.
It is imported from scripts/check_table_ownership.py, so the two cannot disagree about what counts as
an authoritative write. That gate was added by WI-197 and is what made this measurement cheap; neither
existed before it.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

# A transaction is established by opening one or by deriving queries from one. Both are matched, and
# `sql.Tx` is included so a helper that accepts a tx counts even when it does not open one.
_TX = re.compile(r"BeginTx|\.WithTx\(|sql\.Tx")


def _ownership():
    """Import scripts/check_table_ownership.py by path, sharing its parse of the query files."""
    path = ROOT / "scripts" / "check_table_ownership.py"
    spec = importlib.util.spec_from_file_location("_check_table_ownership", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    # @dataclass resolves its annotations through sys.modules[cls.__module__], so the entry has to
    # exist for the duration of exec_module or the class body raises while being built.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    ownership = _ownership()
    mutating = {
        name: info for name, info in ownership.statements().items() if info["mutating"]
    }
    if not mutating:
        print("report_tx_coverage: FAIL: no mutating queries were parsed, so nothing was checked")
        return 1

    listed = subprocess.run(
        ["git", "ls-files", "-z", "*.go"], cwd=ROOT, capture_output=True, check=True
    )
    files = [f for f in listed.stdout.decode("utf-8").split("\0") if f]

    rows: list[tuple[str, list[str], bool]] = []
    for name in sorted(files):
        if name.endswith("_test.go"):
            continue
        text = ownership.code_only((ROOT / name).read_text(encoding="utf-8"))
        calls = sorted(q for q in mutating if re.search(rf"\.\s*{re.escape(q)}\b", text))
        if calls:
            rows.append((name, calls, bool(_TX.search(text))))

    width = max((len(name) for name, _, _ in rows), default=10)
    print("{:<{w}}  {:>5}  {}".format("file", "writes", "transaction", w=width))
    print("-" * (width + 22))
    for name, calls, has_tx in rows:
        print(
            "{:<{w}}  {:>5}  {}".format(
                name, len(calls), "yes" if has_tx else "no", w=width
            )
        )
        if not has_tx:
            print("{:<{w}}         {}".format("", ", ".join(calls), w=width))

    without = [name for name, _, has_tx in rows if not has_tx]
    print()
    print(f"{len(mutating)} mutating queries declared; {len(rows)} non-test file(s) write.")
    print(f"{len(rows) - len(without)} establish a transaction; {len(without)} do not.")
    if without:
        print(
            "A path listed as 'no' is NOT automatically a defect: a single-statement write is already "
            "atomic in PostgreSQL. See WI-199 - the boundary that matters spans the mutation, its "
            "audit record and its outbox row, and the outbox does not exist yet (WI-121)."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
