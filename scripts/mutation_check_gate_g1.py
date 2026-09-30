"""Confirm the G1 gate criteria can fail.

A gate that always prints PASS is worse than no gate, because it converts an unverified claim
into a certified one. Each mutation below breaks one criterion's real control and requires
that criterion to report FAIL. Bytes are used throughout and every file is restored
byte-for-byte, because a text-mode rewrite on Windows converts a shell or Go file to CRLF and
would damage the artifact under test.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_gate_g1 as gate  # noqa: E402

MONEY = gate.ROOT / "contracts/go/money.go"
IDENTIFIER = gate.ROOT / "contracts/go/identifier.go"
CONFIG_SIGN = gate.ROOT / "services/control-plane/config/sign.go"


def mutate(path: Path, old: str, new: str) -> None:
    text = path.read_bytes().decode("utf-8")
    if old not in text:
        raise SystemExit(f"anchor not found in {path.name}: {old[:60]!r}")
    path.write_bytes(text.replace(old, new, 1).encode("utf-8"))


def main() -> int:
    money = MONEY.read_bytes()
    identifier = IDENTIFIER.read_bytes()
    config_sign = CONFIG_SIGN.read_bytes()
    missed = 0
    try:
        # 1. Binary floating point in the money type. no_float_test.go exists precisely to
        #    forbid this, so the criterion must go red rather than pass on artifact presence.
        mutate(MONEY, "type Money struct {", "type Money struct {\n\tlegacyRate float32")
        result = gate.criterion_money()
        print(f"  {'CAUGHT' if result.status == 'FAIL' else 'MISSED'} "
              f"float32 introduced into Money")
        missed += result.status != "FAIL"
        MONEY.write_bytes(money)

        # 2. The canonical ID implementation removed entirely.
        IDENTIFIER.unlink()
        result = gate.criterion_canonical_ids()
        print(f"  {'CAUGHT' if result.status == 'FAIL' else 'MISSED'} "
              f"contracts/go/identifier.go deleted")
        missed += result.status != "FAIL"
        IDENTIFIER.write_bytes(identifier)

        # 3. The configuration signing implementation removed entirely.
        CONFIG_SIGN.unlink()
        result = gate.criterion_config_boundaries()
        print(f"  {'CAUGHT' if result.status == 'FAIL' else 'MISSED'} "
              f"config/sign.go deleted")
        missed += result.status != "FAIL"
        CONFIG_SIGN.write_bytes(config_sign)

        # 4. A migration made irreversible. real_migrations_test.go parses the repository's
        #    own files, so removing a down body must fail the migrations criterion.
        migration = gate.ROOT / "db/migrations/0002_audit.sql"
        original_migration = migration.read_bytes()
        text = original_migration.decode("utf-8")
        head, _, _tail = text.partition("-- migrate:down")
        # The down body is replaced, not merely annotated. An earlier version of this
        # mutation re-appended the original tail, which left the body intact and reported a
        # criterion as undetected when in fact nothing had been broken.
        migration.write_bytes((head + "-- migrate:down\n-- body removed\n").encode("utf-8"))
        result = gate.criterion_migrations()
        print(f"  {'CAUGHT' if result.status == 'FAIL' else 'MISSED'} "
              f"0002_audit.sql down body emptied")
        missed += result.status != "FAIL"
        migration.write_bytes(original_migration)
    finally:
        MONEY.write_bytes(money)
        IDENTIFIER.write_bytes(identifier)
        CONFIG_SIGN.write_bytes(config_sign)

    for path, data in ((MONEY, money), (IDENTIFIER, identifier), (CONFIG_SIGN, config_sign)):
        if path.read_bytes() != data:
            print(f"  ERROR  {path.name} was not restored byte-for-byte")
            return 1

    print()
    print("all gate criteria detect their failure" if not missed
          else f"{missed} criterion/criteria did NOT detect a broken control")
    return 1 if missed else 0


if __name__ == "__main__":
    raise SystemExit(main())
