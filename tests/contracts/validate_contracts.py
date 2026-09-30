#!/usr/bin/env python3
"""Canonical contract conformance validator.

Runs the shared corpus in ``contracts/fixtures/conformance.json`` against the JSON Schema
definitions in ``contracts/schema/`` and reports a result per case.

This is the enforcement mechanism behind docs/02_POLYGLOT_ENGINEERING_STANDARD.md section 9:
canonical decimal, timestamp, identifier, enum, error, and pagination representations are
tested against shared fixtures, and a component cannot promote if its contract fixtures
disagree with the canonical contract repository.

This validator proves the *contracts* are internally consistent and that every declared
accept/reject case behaves as specified. It does not validate a language binding; bindings
run the same corpus in their own test suites and report per-language status.

Usage:
    python tests/contracts/validate_contracts.py [--verbose]

Exit codes:
    0  every case behaved exactly as the corpus declares
    1  at least one case contradicted the corpus
    2  the corpus or a schema could not be loaded
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    import jsonschema
    from referencing import Registry, Resource
except ImportError:  # pragma: no cover
    sys.stderr.write(
        "FATAL: the 'jsonschema' and 'referencing' packages are required.\n"
        "       Install with: python -m pip install jsonschema\n"
    )
    raise SystemExit(2)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO_ROOT / "contracts" / "schema"
FIXTURE_PATH = REPO_ROOT / "contracts" / "fixtures" / "conformance.json"


def load_schemas() -> dict[str, dict[str, Any]]:
    """Load every schema keyed by its $id, verifying there are no duplicate ids."""
    schemas: dict[str, dict[str, Any]] = {}
    for path in sorted(SCHEMA_DIR.glob("*.schema.json")):
        with path.open(encoding="utf-8") as handle:
            schema = json.load(handle)
        schema_id = schema.get("$id")
        if not schema_id:
            raise ValueError(f"{path.name}: missing $id")
        if schema_id in schemas:
            raise ValueError(f"duplicate schema id: {schema_id}")
        schemas[schema_id] = schema
    return schemas


def build_registry(schemas: dict[str, dict[str, Any]]) -> Registry:
    """Build a registry so that relative $refs such as 'decimal.schema.json' resolve."""
    resources = [(uri, Resource.from_contents(body)) for uri, body in schemas.items()]
    return Registry().with_resources(resources)


def resolve_local(schemas: dict[str, dict[str, Any]], filename: str) -> str:
    """Map a corpus schema filename to its full $id."""
    for uri, body in schemas.items():
        if uri.endswith(f"/{filename}"):
            return uri
    raise KeyError(f"corpus references unknown schema file: {filename}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the canonical contract corpus.")
    parser.add_argument("--verbose", action="store_true", help="print a line per case")
    args = parser.parse_args()

    try:
        schemas = load_schemas()
        registry = build_registry(schemas)
        with FIXTURE_PATH.open(encoding="utf-8") as handle:
            corpus = json.load(handle)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"FATAL: could not load contracts: {exc}\n")
        return 2

    cases = corpus.get("cases", [])
    if not cases:
        sys.stderr.write("FATAL: conformance corpus contains no cases\n")
        return 2

    validator_cls = jsonschema.validators.validator_for(
        schemas[next(iter(schemas))], default=jsonschema.Draft202012Validator
    )
    validator_cls.check_schema(next(iter(schemas.values())))

    passed = 0
    failures: list[tuple[str, str, str]] = []

    for case in cases:
        name = case.get("name", "<unnamed>")
        expect = case.get("expect")
        value = case.get("value")
        try:
            uri = resolve_local(schemas, case["schema"])
        except KeyError as exc:
            failures.append((name, "unknown-schema", str(exc)))
            continue

        validator = validator_cls(schema=schemas[uri], registry=registry)
        is_valid = validator.is_valid(value)

        if expect == "accept" and is_valid:
            passed += 1
            if args.verbose:
                print(f"PASS  accept  {name}")
        elif expect == "reject" and not is_valid:
            passed += 1
            if args.verbose:
                print(f"PASS  reject  {name}")
        elif expect == "accept":
            reason = _first_error(validator, value)
            failures.append((name, "expected accept, got reject", reason))
        elif expect == "reject":
            failures.append((name, "expected reject, got accept", "schema did not reject the value"))
        else:
            failures.append((name, "malformed case", f"unknown expect value: {expect!r}"))

    total = len(cases)
    print()
    print(f"contract conformance: {passed}/{total} cases behaved as declared")
    print(f"contract package version: {corpus.get('contract_package_version')}")
    print(f"schemas loaded: {len(schemas)}")

    if failures:
        print()
        print("FAILURES:")
        for name, summary, detail in failures:
            print(f"  - {name}: {summary}")
            if detail:
                print(f"      {detail.splitlines()[0]}")
        return 1

    bindings = corpus.get("binding_conformance", {}).get("status_by_binding", {})
    if bindings:
        print()
        print("language binding status (not exercised by this validator):")
        for language, status in sorted(bindings.items()):
            print(f"  - {language}: {status}")
    print()
    print("CONTRACTS VALID: the canonical corpus and schemas agree.")
    return 0


def _first_error(validator: Any, value: Any) -> str:
    error = next(iter(validator.iter_errors(value)), None)
    if error is None:
        return "unknown validation error"
    location = "/".join(str(part) for part in error.absolute_path) or "<root>"
    return f"{location}: {error.message}"


if __name__ == "__main__":
    raise SystemExit(main())
