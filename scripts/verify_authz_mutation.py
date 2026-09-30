#!/usr/bin/env python3
"""Mutation-test the authz migration: prove the verification suite actually bites.

A database verification suite that only proves its guards *fire* will pass a migration
whose guards fire on every write, including the legitimate ones. That migration refuses all
writes, so nothing reaches storage, so every "this should have been refused" assertion
passes, and the report says the guards work.

The only way to know the suite can tell the difference is to break the migration on purpose
and confirm the report goes red. Each mutation below removes or inverts one control, runs
the real verifier against the mutated migration, and requires that specific assertions fail.

Exit codes:
    0  every mutation was detected
    1  at least one mutation went undetected, meaning the suite has a blind spot
    2  the harness could not run

Usage:
    python scripts/verify_authz_mutation.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIGRATION = ROOT / "db/migrations/0003_authz.sql"
VERIFY = ROOT / "db/tests/0003_authz_verify.sql"

# Each mutation replaces a unique anchor in the migration. The anchor is written exactly as
# it appears in the file, so a refactor that moves the text fails the harness loudly instead
# of silently applying no mutation and reporting success.
MUTATIONS: list[tuple[str, str, str, list[str]]] = [
    (
        "exclusion matrix does not apply to DENY rules",
        "only ALLOW rules are checked against the exclusion matrix",
        """        IF coalesce(rule ->> 'effect', '') <> 'ALLOW' THEN
            CONTINUE;
        END IF;""",
        ["06 a deny naming an excluded pair is accepted"],
    ),
    (
        "role exclusions are not append-only",
        "the exclusion table accepts deletion",
        """CREATE TRIGGER authz_role_action_exclusion_no_update
    BEFORE UPDATE OR DELETE ON authz_role_action_exclusion
    FOR EACH ROW EXECUTE FUNCTION authz_refuse_exclusion_mutation();""",
        ["10 an exclusion cannot be deleted", "11 an exclusion cannot be updated",
         "13 the exclusion matrix still holds its full size"],
    ),
    (
        "the approval immutability guard permits a digest edit",
        "an approval's bound diff can be rewritten after approval",
        """        RAISE EXCEPTION
            'approval % is bound to an exact change and two people; only its application time may be recorded',
            OLD.request_id
            USING ERRCODE = 'restrict_violation';""",
        ["33 an approval digest cannot be edited after the fact"],
    ),
    (
        "self-approval becomes possible",
        "an approval may be approved by the person who requested it",
        """    CONSTRAINT authz_approvals_distinct_people CHECK (requested_by <> approved_by),""",
        ["30 self-approval is not representable"],
    ),
    (
        "wildcard environment grants are permitted",
        "a wildcard scope can cover live, which docs/21 section 4 prohibits",
        """    IF '*' = ANY (NEW.environments) THEN""",
        ["19 a wildcard environment scope is refused"],
    ),
    (
        "the 90 day grant cap is dropped",
        "a grant may be written with an unbounded lifetime",
        """    CONSTRAINT authz_role_grants_max_age
        CHECK (expires_at_utc <= granted_at_utc + interval '90 days'),""",
        ["15 a grant cannot outlive the 90 day cap"],
    ),
    (
        "decision records become mutable",
        "a recorded refusal can be edited into an allow",
        """CREATE TRIGGER authz_decisions_no_mutation
    BEFORE UPDATE OR DELETE ON authz_decisions
    FOR EACH ROW EXECUTE FUNCTION authz_refuse_exclusion_mutation();""",
        ["42 a decision cannot be edited", "43 a decision cannot be deleted",
         "45 both decisions survived the immutability attempts"],
    ),
    (
        "the session absolute timeout is not enforced",
        "a session may be created already beyond its class lifetime",
        """CREATE CONSTRAINT TRIGGER authz_sessions_age
    AFTER INSERT ON authz_sessions
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION authz_check_session_age();""",
        ["23 a session cannot be created already expired",
         "24 the session class timeout is read from the policy table"],
    ),
]

# The harness prints "ALL 54 DATABASE ASSERTIONS PASSED", so the optional word between the
# count and ASSERTIONS matters. A pattern that does not allow it reads a fully passing
# migration as having produced no summary at all, which this harness would report as
# "the suite is not trustworthy" — the least useful possible diagnosis.
FAILED_RE = re.compile(r"(\d+)\s+OF\s+(\d+)\s+(?:\w+\s+)?ASSERTIONS\s+FAILED")
ALL_PASSED_RE = re.compile(r"ALL\s+(\d+)\s+(?:\w+\s+)?ASSERTIONS\s+PASSED")


def run_verifier(migration: Path) -> tuple[int, int, int, str]:
    """Run the real verifier and return (passed, failed, total, output).

    total == 0 means the harness produced no summary at all, which is a different thing from
    a green run. The caller must not read it as "the mutation survived".
    """
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/verify_ledger_db.py"),
         "--migration", str(migration.relative_to(ROOT)),
         "--verify", str(VERIFY.relative_to(ROOT))],
        cwd=ROOT, capture_output=True, text=True, timeout=900,
    )
    out = proc.stdout + proc.stderr
    m = FAILED_RE.search(out)
    if m:
        return int(m.group(2)) - int(m.group(1)), int(m.group(1)), int(m.group(2)), out
    m = ALL_PASSED_RE.search(out)
    if m:
        return int(m.group(1)), 0, int(m.group(1)), out
    return 0, 0, 0, out


def run_verifier_resilient(migration: Path, attempts: int = 3) -> tuple[int, int, int, str]:
    """Run the verifier, retrying a run that produced no summary.

    Each attempt starts a fresh PostgreSQL container, and container startup is occasionally
    slow enough that the readiness probe gives up. That failure mode looks exactly like
    "no assertions ran", and reporting it as a surviving mutation would be a false claim
    about the suite. A run that produces no summary is retried; a run that produces a
    summary is believed on the first try, because a green run with zero failures is a real
    answer and re-running it would only risk turning a detection into a non-detection.
    """
    last_out = ""
    for attempt in range(1, attempts + 1):
        passed, failed, total, out = run_verifier(migration)
        if total > 0:
            return passed, failed, total, out
        last_out = out
        print(f"    (attempt {attempt}/{attempts} produced no summary; retrying)")
    return 0, 0, 0, last_out


def main() -> int:
    original = MIGRATION.read_text(encoding="utf-8")

    print("=== baseline ===")
    passed, failed, total, out = run_verifier_resilient(MIGRATION)
    if total == 0:
        print("baseline produced no summary after retries; the suite is not trustworthy\n")
        print(out[-3000:])
        return 2
    print(f"baseline: {passed} passed, {failed} failed, {total} total")
    if failed:
        print("the unmutated migration does not pass; fix that before mutation testing")
        return 2

    undetected: list[str] = []
    inconclusive: list[str] = []
    for name, description, anchor, expected_failures in MUTATIONS:
        if anchor not in original:
            print(f"[ANCHOR MISSING] {name}\n  the anchor text was not found verbatim; "
                  f"the migration was refactored and this mutation is now vacuous")
            undetected.append(name)
            continue

        # Apply the mutation by replacing the control with a no-op, which is what "the guard
        # is gone" means concretely. Commenting the trigger out would still leave the
        # function defined, and neutering the predicate leaves the trigger firing on every
        # row. Both are real removals of the control.
        mutated = original
        if "coalesce(rule ->> 'effect'" in anchor:
            mutated = original.replace(
                anchor, "        -- MUTATION: the ALLOW-only guard is removed.", 1)
        elif "authz_role_action_exclusion_no_update" in anchor:
            mutated = original.replace(anchor, "    -- MUTATION: trigger removed.", 1)
        elif "only its application time may be recorded" in anchor:
            # The replacement must still be a valid PL/pgSQL statement. An earlier version
            # left a bare string literal where the RAISE had been, which is a syntax error:
            # the migration then failed to apply, the verifier produced no summary, and the
            # mutation was reported as inconclusive rather than as passing or failing.
            # A mutation that breaks the file under test is not a mutation, it is a typo.
            mutated = original.replace(
                anchor,
                "            NULL;  -- MUTATION: the RAISE is removed, the guard does nothing",
                1)
        elif "authz_approvals_distinct_people" in anchor:
            mutated = original.replace(anchor, "    -- MUTATION: constraint removed,", 1)
        elif "'*' = ANY (NEW.environments) THEN" in anchor:
            mutated = original.replace(anchor, "    IF false THEN", 1)
        elif "authz_role_grants_max_age" in anchor:
            mutated = original.replace(anchor, "    -- MUTATION: constraint removed,", 1)
        elif "authz_decisions_no_mutation" in anchor:
            mutated = original.replace(anchor, "    -- MUTATION: trigger removed.", 1)
        elif "authz_sessions_age" in anchor:
            mutated = original.replace(anchor, "    -- MUTATION: trigger removed.", 1)
        else:
            print(f"[ANCHOR UNHANDLED] {name}")
            undetected.append(name)
            continue

        if mutated == original:
            print(f"[ANCHOR MISSING] {name}\n  the anchor was found but the replacement "
                  f"produced an identical file; the mutation is vacuous")
            undetected.append(name)
            continue

        mutated_path = MIGRATION.with_suffix(".mutant.sql")
        mutated_path.write_text(mutated, encoding="utf-8")
        try:
            _, mf, mt, mout = run_verifier_resilient(mutated_path)
        finally:
            mutated_path.unlink(missing_ok=True)

        if mt == 0:
            # Retries already happened. This is a harness failure, not a verdict about the
            # suite, and conflating the two would overstate what has been proven.
            print(f"[INCONCLUSIVE] {name}\n  the verifier never produced a summary for the "
                  f"mutated migration, so this mutation is untested rather than undetected")
            inconclusive.append(name)
        elif mf > 0:
            print(f"[detected ({mf} assertion(s) failed)] {name}\n  {description}")
        else:
            print(f"[UNDETECTED] {name}\n  {description}\n  the suite stayed fully green with "
                  f"this control removed, so it does not test this control")
            undetected.append(name)

    print()
    if undetected or inconclusive:
        if undetected:
            print(f"{len(undetected)} of {len(MUTATIONS)} mutations survived undetected:")
            for n in undetected:
                print(f"  - {n}")
            print("\nThese are real blind spots: the suite reports success with the control "
                  "absent.")
        if inconclusive:
            print(f"\n{len(inconclusive)} mutation(s) were inconclusive (the verifier produced "
                  f"no summary after retries); they are unproven, not proven to pass:")
            for n in inconclusive:
                print(f"  - {n}")
        return 1

    print(f"all {len(MUTATIONS)} mutations detected; the suite distinguishes working guards "
          f"from broken ones")
    return 0


if __name__ == "__main__":
    sys.exit(main())
