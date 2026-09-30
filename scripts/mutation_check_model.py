"""Mutation check for the model package (WI-141).

A test suite that has never been shown to fail is not evidence. This injects defects into
services/control-plane/model, requires the package's own tests to go red for each one, and
restores the file byte-for-byte afterwards. It is the mechanical form of the claim that the
package's guarantees are enforced rather than asserted.

Every mutation here targets a rule that the package's doc comments claim is enforced. The
point is that removing the enforcement must remove a passing test, so a future reader can
tell the difference between a rule that is checked and a rule that is written down.

Two of these mutations are regressions against real defects found while building the
package, and are marked as such below.
"""

from __future__ import annotations

import hashlib
import io
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PKG = REPO / "services" / "control-plane" / "model"
CONTROL_PLANE = REPO / "services" / "control-plane"


@dataclass(frozen=True)
class Mutation:
    """One injected defect and the file it lives in.

    scope, when set, confines the replacement to the characters following the scope marker.
    It exists because several rules share an actor set: APPROVED, PROMOTED, and
    quarantine-clearing all permit humanActors, so a plain whole-file replace of that line
    would hit the first occurrence and mutate a different transition than intended. The
    first version of this harness used long literal anchors including the intervening
    comment, and gofmt reflowed the comment out from under it, so the mutation was skipped
    silently and reported as neither detected nor survived. A scoped replace is both more
    robust and easier to verify by reading.
    """

    name: str
    filename: str
    old: str
    new: str
    why: str
    regression: bool = False
    scope: str | None = None
    window: int = 2000


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        name="M1 financial tool permitted on the direct path",
        filename="tools.go",
        old='if tool.Classification == ClassFinancial && req.Path != PathGoCommand {',
        new="if false {",
        why="docs/07 section 5: financial tools may only be invoked through the Go command "
        "path, which is what subjects them to authorization and the risk veto",
    ),
    Mutation(
        name="M2 allowlist match ignores the subject identity",
        filename="tools.go",
        old="if list.SubjectID != req.SubjectID {",
        new="if false {",
        why="an allowlist is bound to one identity; permitting a transfer would let a "
        "revoked or lesser workload use another's grants",
    ),
    Mutation(
        name="M3 independence check removed from the approve path",
        filename="lifecycle.go",
        old="if declared.RequiresIndependentApprover {\n\t\tif err := checkIndependence(req, declared); err != nil {\n\t\t\treturn Outcome{}, err\n\t\t}\n\t}",
        new="if false {\n\t\t_ = checkIndependence\n\t}",
        why="acceptance criterion two: no model may authorize its own execution, and an "
        "author or owner approving their own model is the shape it takes",
    ),
    Mutation(
        name="M4 request lookup reverts to the single-source command map",
        filename="lifecycle.go",
        old="byFromCmd[transitionKey{state: from, command: cmd}]",
        new="byCmd[cmd]",
        why="REGRESSION. The quarantine command is declared on eight edges; a single-valued "
        "command map keeps one edge, so quarantine would silently not apply from seven of "
        "eight states and a compromised model would stay promotable in those states",
        regression=True,
    ),
    Mutation(
        name="M5 clearing a quarantine permitted for a system actor",
        filename="lifecycle.go",
        old="humanActors,",
        new="securityActors,",
        why="REGRESSION. A compromised workload able to schedule its own restoration inverts "
        "the containment requirement entirely",
        regression=True,
        scope="From: StateQuarantined, To: StateRetired,",
    ),
    Mutation(
        name="M6 quarantine reachability check removed from the declaration",
        filename="lifecycle.go",
        old="if !canQuarantine {\n\t\t\treturn declarationProblem{fmt.Sprintf(",
        new="if false {\n\t\t\treturn declarationProblem{fmt.Sprintf(",
        why="docs/25 section 6 requires promotion to be blocked after a compromise; without "
        "this a state with no quarantine edge would survive one",
    ),
    Mutation(
        name="M7 record validation skips the required-field sweep",
        filename="record.go",
        old="for _, f := range requiredFields {\n\t\tif f.empty(r) {",
        new="for _, f := range requiredFields {\n\t\tif false {",
        why="docs/07 requires every field of the model record; a registry that accepts a "
        "partial record cannot answer whether a model is promotable",
    ),
    Mutation(
        name="M8 digest length check loosened",
        filename="record.go",
        old="if len(d) != 64 {",
        new="if len(d) == 0 {",
        why="a truncated fingerprint must not pass as a recorded one; lineage is evidence "
        "only if the digest identifies bytes",
    ),
    Mutation(
        name="M9 monitoring coverage requirement removed",
        filename="monitoring.go",
        old="if len(missing) > 0 {",
        new="if false {",
        why="docs/07 section 4 requires all seven signals; a monitor missing data freshness "
        "reports a model fed stale inputs as healthy",
    ),
    Mutation(
        name="M10 automatic pause may be disabled",
        filename="monitoring.go",
        old="if !autoPause {",
        new="if false {",
        why="docs/07 section 4: a breached threshold causes automatic pause",
    ),
    Mutation(
        name="M11 decision authority assertion neutered",
        filename="decision.go",
        old="if call.Classification == ClassFinancial && call.Path != PathGoCommand {",
        new="if false {",
        why="the ledger and the authorization check must not disagree; an authorized "
        "financial call off the command path means they do",
    ),
    Mutation(
        name="M12 refused tool call may omit its reason",
        filename="decision.go",
        old='if !call.Authorized && call.RefusalCode == "" {',
        new="if false {",
        why="a denial without a reason is not reconstructable, and the absence of a reason "
        "reads as though no denial was attempted",
    ),
    Mutation(
        name="M14 deployment-scope check removed from the record",
        filename="record.go",
        old='{"deployment_scope", func(r Record) bool { return strings.TrimSpace(r.DeploymentScope) == "" }},',
        new='{"deployment_scope", func(r Record) bool { return false }},',
        why="an empty deployment scope is an unbounded deployment, which must be rejected "
        "rather than defaulted",
    ),
    Mutation(
        name="M15 idempotency key requirement dropped",
        filename="lifecycle.go",
        old="if len(req.IdempotencyKey) < 8 {",
        new="if false {",
        why="a transition without a key could be applied twice on retry",
    ),
    Mutation(
        name="M16 authority preconditions weakened",
        filename="lifecycle.go",
        old="if !preconditionSatisfied(declared.Precondition, req.PreconditionsSatisfied) {",
        new="if false {",
        why="a caller must not satisfy a transition by asserting a different precondition name",
    ),
    Mutation(
        name="M17 revocation not consulted when authenticating",
        filename="identity.go",
        old='if rev, revoked := r.revocations[p.Identity]; revoked {',
        new="if rev, revoked := r.revocations[p.Identity]; false && revoked {",
        why="docs/25 section 5 requires revocation tests; without this a revoked workload "
        "identity keeps authenticating",
    ),
    Mutation(
        name="M18 expiry not checked when authenticating",
        filename="identity.go",
        old="if held.Expired(now) {",
        new="if false {",
        why="docs/25 section 5 requires a short-lived workload identity",
    ),
    Mutation(
        name="M19 model version binding not enforced",
        filename="identity.go",
        old="if p.ModelID != held.ModelID || p.ModelVersion != held.ModelVersion {",
        new="if false {",
        why="an identity bound to one exact model version must not authenticate for another; "
        "otherwise a revocation aimed at a compromised version is either too narrow or too "
        "broad",
    ),
    Mutation(
        name="M20 containment reports revocation without performing it",
        filename="compromise.go",
        old="revocation, err := registry.Revoke(c.WorkloadIdentity, c.Reason, c.EvidenceRef)\n\tif err != nil {\n\t\treturn CompromiseResponse{}, err\n\t}",
        new="revocation := Revocation{Identity: c.WorkloadIdentity, Reason: c.Reason, EvidenceRef: c.EvidenceRef}\n\tvar err error",
        why="the response must perform the revocation, not assert it; this is the exact "
        "weakness Contain took a caller boolean for",
    ),
    Mutation(
        name="M21 a revoked identity may be re-minted",
        filename="identity.go",
        old="if _, previously := r.revocations[identity]; previously {",
        new="if _, previously := r.revocations[identity]; false && previously {",
        why="a compromised workload must re-enter through a new identity, not resurrect the "
        "one that was just revoked",
    ),
    Mutation(
        name="M22 revocation requires no reason",
        filename="identity.go",
        old='if strings.TrimSpace(reason) == "" {\n\t\treturn Revocation{}, reject(contracts.CodeValidation, ErrIncompleteRecord,\n\t\t\t"a revocation requires a reason; an unattributed revocation is not auditable and "+\n\t\t\t\t"revocation is an action that gets disputed")\n\t}',
        new="if false {\n\t}",
        why="revocation is an action that gets disputed, so an unattributed one is not "
        "auditable",
    ),
    Mutation(
        name="M23 a refused audit record still applies the state change",
        filename="journal.go",
        old="\tif _, err := j.chain.Append([]audit.Record{record}); err != nil {\n\t\treturn Outcome{}, reject(contracts.CodeInternal, ErrIncompleteRecord,\n\t\t\t\"the audit chain refused the record for this %s, so it was not applied: %v\",\n\t\t\taction, err)\n\t}",
        new="\t_, _ = j.chain.Append([]audit.Record{record})",
        why="the entire point of the journal: a state change that cannot be recorded must "
        "not happen, because a model promoted with no trace is indistinguishable from one "
        "that was never promoted",
    ),
    Mutation(
        name="M24 the journal skips the current-state check",
        filename="journal.go",
        old="\tif current != from {",
        new="\tif false {",
        why="the transition table says which edges exist, not where this model is; without "
        "this a quarantined model could be promoted by describing it as REGISTERED",
    ),
    Mutation(
        name="M25 an idempotency retry appends a second audit record",
        filename="journal.go",
        old="\t\tif prior.fingerprint != fingerprint {\n\t\t\treturn Outcome{}, reject(contracts.CodeConflict, ErrIncompleteRecord,\n\t\t\t\t\"idempotency key %q was already used in scope %s for a different request; \"+\n\t\t\t\t\t\"two different intents share one key and neither may be silently preferred\",\n\t\t\t\treq.IdempotencyKey, outcome.IdempotencyScope)\n\t\t}\n\t\treturn prior.outcome, nil",
        new="\t\t_ = prior",
        why="a retried transition is the same record, not a second one; and two different "
        "intents sharing a key must be refused rather than one of them silently preferred",
    ),
    Mutation(
        name="M26 owners share one audit partition",
        filename="journal.go",
        old="\tpartition := rec.Owner",
        new='\tpartition := "model-governance"',
        why="records chained under one owner's scope must not be usable to reason about "
        "another owner's; a single shared partition destroys the tamper isolation the audit "
        "package provides",
    ),
    Mutation(
        name="M27 a rejected request still writes an audit record",
        filename="journal.go",
        old='\t\t\t"model %s is not registered; a lifecycle transition for an unregistered model "+',
        new='\t\t\t"model %s is not registered; a lifecycle transition for an unregistered model "+\n\t\tj.chain.Append([]audit.Record{{AuditID: "rejected", Partition: rec.Owner, Sequence: j.chain.LastSequence(rec.Owner) + 1, ActorID: "x", ActorType: contracts.ActorService, Action: action, TargetType: "model", TargetID: rec.ModelID.String(), Environment: j.environment, OccurredAt: audit.TimestampFrom(j.clock()), RecordedAt: audit.TimestampFrom(j.clock()), Reason: action, Result: audit.ResultRefused}})',
        why="a refusal is not a state change, and a journal that recorded every rejected "
        "call would bury the changes that actually happened",
    ),
    Mutation(
        name="M28 the lifecycle permits an undeclared empty source state",
        filename="lifecycle.go",
        old='\t\tif t.Command != CommandRegister || t.To != StateRegistered {\n\t\t\t\treturn declarationProblem{fmt.Sprintf(\n\t\t\t\t\t"transition %s declares an empty source state, which only %s may do, and "+\n\t\t\t\t\t\t"only into REGISTERED", t.Command, CommandRegister)}\n\t\t\t}',
        new='\t\tif false {\n\t\t\t_ = t.Command\n\t\t}',
        why="only registration may have an empty source state; allowing it "
        "elsewhere would let a model be teleported into the lifecycle from "
        "nowhere, bypassing whatever the losing edge required",
    ),
    Mutation(
        name="M31 containment revokes only the detected workload",
        filename="compromise.go",
        old="\tfor _, sibling := range registry.IdentitiesServingVersion(\n\t\trevocation.ModelID, revocation.ModelVersion, revocation.RevokedAt) {\n\t\tif sibling.Identity == c.WorkloadIdentity {\n\t\t\tcontinue\n\t\t}\n\t\tif _, err := registry.Revoke(sibling.Identity, c.Reason, c.EvidenceRef); err != nil {\n\t\t\treturn CompromiseResponse{}, err\n\t\t}\n\t}",
        new="\tfor _, sibling := range []WorkloadIdentity{} {\n\t\tif _, err := registry.Revoke(sibling.Identity, c.Reason, c.EvidenceRef); err != nil {\n\t\t\treturn CompromiseResponse{}, err\n\t\t}\n\t}",
        why="revoking only the detected workload is precise and incomplete; the compromised "
        "thing is the model version, so every workload serving it can still answer with the "
        "compromised artefact",
    ),
    Mutation(
        name="M32 containment widens to the whole model, not the version",
        filename="compromise.go",
        old="\t\trevocation.ModelID, revocation.ModelVersion, revocation.RevokedAt) {\n\t\tif sibling.Identity == c.WorkloadIdentity {",
        new="\t\trevocation.ModelID, \"\", revocation.RevokedAt) {\n\t\tif sibling.Identity == c.WorkloadIdentity {",
        why="widening past the exact model version revokes workloads with no relationship to "
        "the compromise, which destroys availability and makes the containment unreviewable",
    ),
    Mutation(
        name="M33 the response reports the live set rather than the recorded revocations",
        filename="compromise.go",
        old="\tcontained := registry.ContainedIdentitiesForVersion(revocation.ModelID, revocation.ModelVersion)",
        new="\tcontained := []string{c.WorkloadIdentity}",
        why="the reported blast radius must be a function of what happened, not of when the "
        "record was written; derived from the live set, a retry records a smaller "
        "containment than actually occurred",
    ),
    Mutation(
        name="M30 a forged edge out of quarantine is permitted",
        filename="lifecycle.go",
        old='\tfor _, t := range edgesFrom(table, StateQuarantined) {\n\t\tif !t.To.IsTerminal() {',
        new='\tfor _, t := range edgesFrom(table, StateQuarantined) {\n\t\tif false {',
        why="the rule is that no edge leaves quarantine for a non-terminal state. The "
        "check used to name only the QUARANTINED -> EVALUATED pair, so a forged edge to "
        "any other non-terminal state satisfied a comment that promised otherwise",
    ),
    Mutation(
        name="M29 the workload registry takes no lock",
        filename="identity.go",
        old="\tdefer r.mu.Unlock()",
        new="\t_ = r.mu",
        why="Mint checks revocations and then writes identities while Revoke does the "
        "reverse; without the lock a revoke racing a mint can be lost, leaving a live "
        "identity for a workload that was just revoked",
    ),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_tests() -> tuple[bool, str]:
    """Run the model package's tests, returning (passed, output)."""
    proc = subprocess.run(
        ["go", "test", "./model/", "-count=1"],
        cwd=CONTROL_PLANE,
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0, (proc.stdout + proc.stderr)


def apply_mutation(m: Mutation, text: str) -> str | None:
    """Return the mutated text, or None when the anchor is not present."""
    if m.scope is None:
        return text.replace(m.old, m.new, 1) if m.old in text else None
    start = text.find(m.scope)
    if start < 0:
        return None
    begin = start + len(m.scope)
    end = min(len(text), begin + m.window)
    region = text[begin:end]
    if m.old not in region:
        return None
    return text[:begin] + region.replace(m.old, m.new, 1) + text[end:]


def main() -> int:
    if not (PKG / "record.go").is_file():
        print(f"model package not found at {PKG}")
        return 1

    baseline_ok, baseline_out = run_tests()
    if not baseline_ok:
        print("BASELINE FAILS; the mutation results would be meaningless.")
        print(baseline_out[-2000:])
        return 1
    print(f"baseline: model tests PASS\n")

    original = {
        m.filename: (PKG / m.filename).read_bytes()
        for m in MUTATIONS
    }
    digests = {name: sha256(PKG / name) for name in original}

    survived: list[Mutation] = []
    skipped: list[Mutation] = []
    applied = 0
    try:
        for m in MUTATIONS:
            target = PKG / m.filename
            # Every mutation is applied to the pristine tree and restored immediately.
            # Restoring only at the end would let mutations on the same file compound, and a
            # test failure would then no longer be attributable to the mutation it is
            # reported under. A mutation check that cannot say which change it detected is
            # not evidence.
            target.write_bytes(original[m.filename])
            text = target.read_text(encoding="utf-8")
            mutated = apply_mutation(m, text)
            if mutated is None:
                skipped.append(m)
                print(f"SKIP  {m.name}: anchor not found in {m.filename}")
                continue
            target.write_text(mutated, encoding="utf-8", newline="\n")
            applied += 1
            passed, out = run_tests()
            if passed:
                survived.append(m)
                print(f"SURVIVED  {m.name}")
                print(f"          {m.why}")
            else:
                first = ""
                for line in out.splitlines():
                    if "--- FAIL" in line:
                        first = line.strip()
                        break
                print(f"detected  {m.name}")
                if first:
                    print(f"          {first}")
            # Restore before the next mutation so each is measured in isolation.
            target.write_bytes(original[m.filename])
    finally:
        for name, blob in original.items():
            (PKG / name).write_bytes(blob)

    print()
    restored = all(sha256(PKG / name) == digests[name] for name in digests)
    print(f"restored byte-for-byte: {restored}")
    print(f"applied {applied} of {len(MUTATIONS)} mutations")
    print(f"detected {applied - len(survived)}; survived {len(survived)}; skipped {len(skipped)}")

    if skipped:
        print("\nSKIPPED MUTATIONS (an unverified claim, not a pass):")
        for m in skipped:
            print(f"  - {m.name}: {m.why}")
        print("\nA skipped mutation means the rule was neither confirmed nor refuted.")
        return 1
    if survived:
        print("\nSURVIVING MUTATIONS (these rules are written down but not enforced):")
        for m in survived:
            print(f"  - {m.name}: {m.why}")
        return 1
    if not restored:
        print("\nRESTORE FAILED: the working tree does not match the pre-mutation state")
        return 1
    print("\nall mutations applied and detected; every claimed rule is enforced by a failing test")
    return 0


if __name__ == "__main__":
    sys.exit(main())
