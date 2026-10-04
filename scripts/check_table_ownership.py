#!/usr/bin/env python3
"""Enforce WI-120's third criterion: cross-module mutation only through commands or events.

A generated query belongs to the module whose query file declares it. This refuses any other package
calling a *mutating* query of that module, which is the mechanical form of "no cross-module mutation":
if module B cannot call module A's INSERT, then a state transition owned by A can only happen through
A's own command surface or through an event A chose to publish.

Reads are deliberately not restricted. Two modules reading the same table is how a join and a
consistency check get written, and forbidding it would produce a gate whose pressure is to copy the
read into a hand-written string - which is the bypass `check_no_stray_sql` exists to catch.

The ownership map is three entries and each carries a reason. What is enforced is not the map but the
rule that uses it: every mutating query's callers must be its owner, so a new query file or a new
module fails the gate until someone says who owns it.

Run:  python scripts/check_table_ownership.py
Exit: 0 clean, 1 violations, 2 the check could not run.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTROL_PLANE = "services/control-plane"
QUERIES = ROOT / CONTROL_PLANE / "db" / "queries"

# query file stem -> the Go package that owns those tables, and why the names differ where they do.
OWNERS: dict[str, tuple[str, str]] = {
    "audit": ("audit", "0002_audit.sql creates unqualified audit_* tables; the audit module owns them"),
    "ledger": ("ledger", "0001_ledger.sql creates the ledger schema; the ledger module owns it"),
    "model_registry": (
        "model",
        "0004_model_registry.sql creates model_registry.* and workload_* tables, and the model module "
        "is their only writer. The stems differ, so the mapping is declared rather than inferred - a "
        "guessed name mapping silently acquires a second owner the first time a table moves",
    ),
}

_NAME = re.compile(r"^--\s*name:\s*(\w+)", re.MULTILINE)
# `ON CONFLICT ... DO UPDATE SET` matches a naive UPDATE pattern and yields SET as the table, so the
# insert target wins where both appear and the conflict clause is excluded from the search.
_INSERT = re.compile(r"(?i)\bINSERT\s+INTO\s+([\w.]+)")
_DELETE = re.compile(r"(?i)\bDELETE\s+FROM\s+([\w.]+)")
_UPDATE = re.compile(r"(?i)(?<!DO )\bUPDATE\s+(?!SET\b)([\w.]+)\s+SET\b")
_SELECT = re.compile(r"(?i)\bSELECT\b")


def statements() -> dict[str, dict]:
    """Every `-- name:` block as {query name: {stem, mutating, tables}}."""
    found: dict[str, dict] = {}
    for path in sorted(QUERIES.glob("*.sql")):
        text = path.read_text(encoding="utf-8")
        code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("--"))
        starts = [m.start() for m in _NAME.finditer(text)]
        for index, start in enumerate(starts):
            name = _NAME.match(text, start).group(1)
            # Bound each statement to the next name comment. Comments are stripped from the body, so
            # a later statement's verb cannot be read as this one's - which is also how the prose in
            # these files, which names tables and verbs in prose, stays out of the table list.
            nxt = text.find("-- name:", starts[index + 1]) if index + 1 < len(starts) else -1
            raw = text[start : nxt if nxt != -1 else len(text)]
            raw_code = "\n".join(l for l in raw.splitlines() if not l.lstrip().startswith("--"))
            tables = {
                t.lower()
                for pattern in (_INSERT, _DELETE, _UPDATE)
                for t in pattern.findall(raw_code)
            }
            found[name] = {
                "stem": path.stem,
                "mutating": bool(tables) and not _SELECT.search(raw_code),
                "tables": sorted(tables),
            }
    return found


_LINE_COMMENT = re.compile(r"//[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


def code_only(text: str) -> str:
    """Go source with comments blanked out, so prose cannot be read as a call.

    This repository documents its reasoning in comments next to the code it describes, and several of
    these files name the queries they do not own in the explanation of why they do not. Matching raw
    text would flag the explanation, so the selector pattern - which is deliberately loose enough to
    catch a method value handed to a function - needs the comments gone first.
    """
    blanked = _LINE_COMMENT.sub(lambda m: " " * len(m.group(0)), text)
    return _BLOCK_COMMENT.sub(lambda m: " " * len(m.group(0)), blanked)


def go_callers(query_names: dict[str, dict]) -> dict[str, set[str]]:
    """Every package that calls each query, outside dbgen and outside tests.

    A query is matched as a selector on anything - `.AppendAuditRecord` - rather than only as a
    call with parentheses, because a method value passed straight to a function is the same
    cross-module write with one fewer character, and a rule that only reads the parenthesised form is
    a rule with a hole in the easiest possible shape. The earlier version required `Name(` and
    consequently reported PASS on a planted method value; that was found by running the control,
    not by reading the pattern.
    """
    listed = subprocess.run(
        ["git", "ls-files", "-z", "*.go"], cwd=ROOT, capture_output=True, check=True
    )
    callers: dict[str, set[str]] = defaultdict(set)
    for name in listed.stdout.decode("utf-8").split("\0"):
        if not name or name.endswith("_test.go") or f"/db/" in name:
            continue
        text = code_only((ROOT / name).read_text(encoding="utf-8"))
        package = name.split("/")[2] if name.startswith(CONTROL_PLANE + "/") else "?"
        for query in query_names:
            if re.search(rf"\.\s*{re.escape(query)}\b", text):
                callers[query].add(package)
    return callers


def main() -> int:
    if not QUERIES.is_dir():
        print(f"check_table_ownership: SKIP: {QUERIES} is not present")
        return 2
    query_names = statements()
    if not query_names:
        print("check_table_ownership: FAIL: no queries were parsed, so nothing was checked")
        return 1

    mutating = {name: info for name, info in query_names.items() if info["mutating"]}
    callers = go_callers(query_names)

    violations: list[str] = []
    for query, info in sorted(mutating.items()):
        stem = info["stem"]
        if stem not in OWNERS:
            violations.append(
                f"{query}: query file {stem}.sql declares a write and no owner is declared for it. "
                "Add it to OWNERS with the reason, or the write has no module that may perform it."
            )
            continue
        owner, _reason = OWNERS[stem]
        for package in sorted(callers.get(query, set()) - {owner}):
            violations.append(
                f"{package} calls {query}, which mutates {', '.join(info['tables'])} and belongs "
                f"to the {owner} package. A cross-module write is only legal through an explicit "
                "command or a transactional event, and calling another module's generated query is "
                "neither."
            )

    for stem in sorted({info["stem"] for info in mutating.values()}):
        if stem not in OWNERS:
            continue
        owner, _ = OWNERS[stem]
        package_dir = ROOT / CONTROL_PLANE / owner
        if not package_dir.is_dir():
            violations.append(
                f"{stem}.sql declares writes owned by the {owner} package, which does not exist at "
                f"{package_dir.relative_to(ROOT)}. An owner that cannot be reached is not an owner."
            )

    if violations:
        print("check_table_ownership: FAIL: a module mutates a table it does not own")
        for item in violations:
            print(f"  {item}")
        return 1

    unused = [q for q in OWNERS if q not in {i["stem"] for i in query_names.values()}]
    note = f" (declared owners with no query file: {', '.join(unused)})" if unused else ""
    called_mutating = sorted(q for q in mutating if callers.get(q))
    uncalled_mutating = sorted(q for q in mutating if not callers.get(q))
    pending = f" (not yet called from Go: {', '.join(uncalled_mutating)})" if uncalled_mutating else ""
    print(
        f"check_table_ownership: PASS ({len(mutating)} mutating queries, "
        f"{len(called_mutating)} of them called from Go, across "
        f"{len({i['stem'] for i in mutating.values()})} owning modules){note}{pending}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())