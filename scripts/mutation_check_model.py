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
import time
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MODEL_PKG = REPO / "services" / "control-plane" / "model"
AUDIT_PKG = REPO / "services" / "control-plane" / "audit"
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
        # false && canQuarantine rather than a bare false: a bare false leaves
        # canQuarantine unreferenced and the package will not build, which the harness
        # scores as a build failure rather than a detection. The conjunction is still
        # unreachable and removes the check for the same reason.
        new="if false && canQuarantine {\n\t\t\treturn declarationProblem{fmt.Sprintf(",
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
    # M13 is intentionally absent. It was removed in an earlier revision and the reason was
    # not recorded at the time, so this note states the fact rather than reconstructing a
    # story. The gap is left rather than closed by renumbering, because EV-042 and its
    # predecessors cite mutation counts and ids; silently shifting every id after the hole
    # would make those records point at different mutations than the ones they were written
    # about. The cost is that the sequence is not dense, and a reader comparing ids across
    # evidence records has to know the hole is real. Verified as of EV-043: 41 entries,
    # ids M1-M42 with M13 absent, no duplicates.
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
        # registry is kept referenced and err is consumed on purpose. Dropping the call
        # left registry unused and left err declared and unread, so the package would not
        # build and the mutation would be scored as a build failure rather than a
        # detection - which is what the first version of this entry did.
        new="_ = registry\n\trevocation := Revocation{Identity: c.WorkloadIdentity, Reason: c.Reason, EvidenceRef: c.EvidenceRef}\n\tif err := error(nil); err != nil {\n\t\treturn CompromiseResponse{}, err\n\t}",
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
        # Anchored on the whole `if !known` block rather than on a fragment of the message
        # string. An earlier version spliced the injected statement into the middle of a
        # string concatenation, which does not parse, so the mutation was reported as a
        # detection while no test had run.
        #
        # The partition is a literal rather than rec.Owner. rec is the zero Record on this
        # branch, because it was just established to be absent, so rec.Owner is empty and the
        # chain refuses the injected record on validation - which made the mutation a no-op
        # that "survived" for a reason that had nothing to do with the claim it was supposed
        # to be testing. A mutation that changes nothing cannot refute anything.
        old="\tif !known {\n\t\treturn Outcome{}, reject(contracts.CodeConflict, ErrIncompleteRecord,\n\t\t\t\"model %s is not registered; a lifecycle transition for an unregistered model \"+",
        new="\tif !known {\n\t\t_, _ = j.chain.Append([]audit.Record{{AuditID: \"rejected-for-unknown-model\", Partition: \"model-registry\", ActorID: req.ActorID, ActorType: req.ActorType, Action: string(req.Command), TargetType: \"model\", TargetID: req.ModelID.String(), Environment: j.environment, OccurredAt: audit.TimestampFrom(j.clock()), RecordedAt: audit.TimestampFrom(j.clock()), Reason: string(req.Command), Result: audit.ResultRefused}})\n\t\treturn Outcome{}, reject(contracts.CodeConflict, ErrIncompleteRecord,\n\t\t\t\"model %s is not registered; a lifecycle transition for an unregistered model \"+",
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
    # --- The persistence claims (WI-141 durable store) ---------------------------
    #
    # M34 to M38 cover the claims that only became falsifiable once a durable store sat
    # behind the journal. Before that, "the state is written only after the audit chain
    # accepts the record" was true by construction, because a map cannot fail - so no
    # mutation could have tested it. These are the first mutations in this harness whose
    # removal has to break a test that could not previously have existed.
    Mutation(
        name="M34 the durable write happens before the audit append",
        filename="journal.go",
        old="""\tif _, err := j.chain.Append([]audit.Record{record}); err != nil {
\t\treturn Outcome{}, reject(contracts.CodeInternal, ErrIncompleteRecord,
\t\t\t"the audit chain refused the record for this %s, so it was not applied: %v",
\t\t\taction, err)
\t}
""",
        new="",
        why="the ordering is the substance of the journal: a state change may not be "
        "recorded anywhere except after the audit chain has accepted the record describing "
        "it. Removing the append makes the durable write the only record of a transition, "
        "which is precisely the unaudited state change this type exists to prevent",
    ),
    Mutation(
        name="M35 in-memory state advances even though the durable write failed",
        filename="journal.go",
        old="""\t\tif err := persist(ctx, auditID); err != nil {
\t\t\treturn Outcome{}, reject(contracts.CodeInternal, ErrIncompleteRecord,
\t\t\t\t"the audit chain accepted the record for this %s but the durable store "+
\t\t\t\t\t"refused it, so it was not applied and the model's state is unchanged: %v",
\t\t\t\taction, err)
\t\t}
""",
        new="""\t\t_ = persist(ctx, auditID)
""",
        why="a caller told the transition was not applied must find the model where it was. "
        "Swallowing the durable failure and proceeding leaves the in-memory state advanced, "
        "so the caller's retry hits a stale-state refusal and cannot tell 'already done' "
        "from 'half done'",
    ),
    Mutation(
        name="M36 the durable row cites an audit record derived independently",
        filename="journal.go",
        old="\t\t\t\tAuditID:      auditID,\n",
        new="\t\t\t\tAuditID:      \"audit-not-the-chain\",\n",
        why="the store receives the identifier the chain actually used rather than deriving "
        "its own. Deriving it twice is one refactor away from the two copies disagreeing, "
        "and a store row citing a different record than the registry row is exactly the "
        "broken linkage the last_audit_id column exists to prevent",
    ),
    Mutation(
        name="M37 the idempotency entry is written before the state change",
        filename="store_sql.go",
        old="""\t\tif _, err := q.SetModelState(ctx, dbgen.SetModelStateParams{
\t\t\tModelID:      entry.ModelID.String(),
\t\t\tState:        string(entry.To),
\t\t\tLastAuditID:  entry.AuditID,
\t\t\tUpdatedBy:    "journal",
\t\t\tUpdatedAtUtc: entry.At,
\t\t}); err != nil {
\t\t\treturn fmt.Errorf("recording model %s in state %s: %w", entry.ModelID, entry.To, err)
\t\t}
""",
        new="""\t\tif _, err := q.RecordTransitionIdempotency(ctx, dbgen.RecordTransitionIdempotencyParams{
\t\t\tIdempotencyScope:   entry.Scope,
\t\t\tIdempotencyKey:     entry.Key,
\t\t\tRequestFingerprint: string(entry.Fingerprint),
\t\t\tModelID:            entry.ModelID.String(),
\t\t\tFromState:          string(entry.From),
\t\t\tToState:            string(entry.To),
\t\t\tAuditID:            entry.AuditID,
\t\t\tAppliedAtUtc:       entry.At,
\t\t}); err != nil {
\t\t\treturn fmt.Errorf("recording the applied transition in scope %s: %w", entry.Scope, err)
\t\t}
""",
        why="ApplyTransition must issue state-then-ledger in that order. Ledger-first would "
        "record a transition before making it, so a constraint failure on the state write "
        "leaves an idempotency entry claiming one happened, and a retry returns that "
        "fabricated outcome as though it were real",
    ),
    Mutation(
        name="M38 the durable store is never consulted",
        filename="journal.go",
        old="\tif j.store != nil && persist != nil {",
        new="\tif false && persist != nil {",
        why="the negative control. Without it, a suite where every test wires a store would "
        "still pass if the journal stopped consulting it entirely, because nothing would "
        "notice that no write happened",
    ),
    # --- The identity store claims (WI-141 workload durability) -------------------
    #
    # M39 to M42 are the containment-durability claims. They matter more than the count
    # suggests: M39 is the mutation that produces a compromise response which reports
    # containment it never achieved, which is the failure EV-040's blast-radius rule was
    # written to prevent and which no test could have expressed before a store existed to
    # fail.
    Mutation(
        name="M39 a refused durable revocation is applied anyway",
        filename="identity.go",
        old="""\t\tif err := r.store.InsertRevocation(ctx, rev); err != nil {
\t\t\treturn Revocation{}, reject(contracts.CodeInternal, ErrIncompleteRecord,
\t\t\t\t"the durable store refused to record the revocation of %q, so it was not "+
\t\t\t\t\t"revoked and the identity is still live: %v", identity, err)
\t\t}
""",
        new="""\t\t_ = r.store.InsertRevocation(ctx, rev)
""",
        why="the caller of Revoke is the compromise response and its return value is "
        "reported to an investigator as work that was done. Revoking in memory after a "
        "refused durable write produces an incident record naming a revocation that exists "
        "nowhere durable - containment reported and not achieved",
    ),
    Mutation(
        name="M40 the in-memory revocation precedes the durable write",
        filename="identity.go",
        old="""\tif r.store != nil {
\t\tif err := r.store.InsertRevocation(ctx, rev); err != nil {
""",
        new="""\tr.revocations[identity] = rev
\tif r.store != nil {
\t\tif err := r.store.InsertRevocation(ctx, rev); err != nil {
""",
        why="the ordering is the whole point, and this mutation keeps the check while "
        "removing the ordering: the registry now records the revocation before the store "
        "does, so a store failure leaves the registry stricter than the durable record and "
        "a retry cannot repair it",
    ),
    Mutation(
        name="M41 the identity store is never consulted on issuance",
        filename="identity.go",
        old="\tif r.store != nil {\n\t\tif err := r.store.InsertIdentity(ctx, issued); err != nil {",
        new="\tif false && r.store != nil {\n\t\tif err := r.store.InsertIdentity(ctx, issued); err != nil {",
        why="a credential recorded by this process and by no other is authenticated here and "
        "invisible everywhere else. The store check is what stops a workload being live in "
        "one control plane and unknown to the next",
    ),
    Mutation(
        name="M42 the durable record drops the identity when it is revoked",
        filename="identity_store.go",
        # The delete keys on identity.Identity, the parameter this function actually
        # has. The first two versions of this mutation referred to rev.Identity here, which
        # does not exist in InsertIdentity, so the package did not build and the harness
        # reported a detection with no test having run - twice, once before the harness
        # could tell the two apart and once after.
        old="\t// The issued row is kept, not replaced-on-revoke. See the port comment.\n\tm.identities[identity.Identity] = identity",
        new="\tm.identities[identity.Identity] = identity\n\tdelete(m.identities, identity.Identity)",
        why="the registry removes a revoked identity from its live map, and mirroring that in "
        "the store would destroy the evidence the revocation is about. A revocation whose "
        "subject exists nowhere is not reviewable by the operator disputing it",
    ),
)

# The audit package's claims. These are numbered A1 upward rather than continuing the M
# sequence, because the two sets are run separately and a shared counter across two files
# that are run independently invites the id collisions EV-042 already recorded once. The
# prefix also makes it unambiguous in the output which package a surviving mutation belongs
# to, which matters when both results are pasted into one evidence record.
#
# The claims here are the ones that EV-044 found had never been checked: the guard's
# backlog had exactly one decrement path and no producer, and the operator's escape hatch
# reported success while doing nothing.
AUDIT_MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        name="A1 a refused export still releases the backlog",
        filename="sink.go",
        old='return fmt.Errorf("exporting %d audit record(s) to durable storage: %w", len(records), err)',
        new='_ = e.guard.Exported(len(records))\n\t\treturn fmt.Errorf("exporting %d audit record(s) to durable storage: %w", len(records), err)',
        why="releasing the backlog for records the sink did not store lets the guard resume "
        "while the evidence sits in a process buffer that a crash erases. The backlog must "
        "count what is still owed, and after a refused write the answer is all of it",
    ),
    Mutation(
        name="A2 the exporter releases the backlog before the sink commits",
        filename="sink.go",
        scope="func (e *Exporter) Export(ctx context.Context, records []Record) error {",
        old="\tif err := e.sink.Export(ctx, records); err != nil {",
        new="\tpre := e.guard.Exported(len(records))\n\t_ = pre\n\tif err := e.sink.Export(ctx, records); err != nil {",
        why="releasing before the write commits is the same data loss as A1 on the success "
        "path: a sink that fails after being released leaves the guard's limit no longer "
        "reflecting reality",
    ),
    Mutation(
        name="A3 clear ignores the outstanding backlog",
        filename="guard.go",
        old="if g.haltCause == causeEvidenceBacklog && g.pending > 0 {",
        new="if false {",
        why="clearing with records still unexported is a clear that does not clear. The next "
        "accepted record re-trips the halt, so the operator resumes and is halted again, and "
        "cannot record the fact that they cleared because Accept is what refuses",
    ),
    Mutation(
        name="A4 clear checks the backlog but not the cause",
        filename="guard.go",
        old="if g.haltCause == causeEvidenceBacklog && g.pending > 0 {",
        new="if g.pending > 0 {",
        why="an integrity halt is a different decision from an export backlog. Requiring the "
        "backlog to drain before an operator may clear a chain break conflates two unrelated "
        "preconditions and makes the SEV-1 path un-clearable while an export is paused",
    ),
    Mutation(
        name="A5 a refused clear releases the latch anyway",
        filename="guard.go",
        scope="if g.haltCause == causeEvidenceBacklog && g.pending > 0 {",
        # The refusal itself is left intact; the mutation releases the latch on the way to
        # refusing. Replacing the reject() call outright leaves its continuation lines
        # dangling and the package does not build, which is not a detection.
        old="return reject(contracts.CodeDependencyUnavailable,",
        new="g.halted = false\n\t\treturn reject(contracts.CodeDependencyUnavailable,",
        why="a clear that refuses must leave the guard exactly as it found it. Releasing the "
        "latch while still reporting failure tells the caller the halt is lifted when it is "
        "not, and leaves the guard refusing operations for a reason nobody can see",
    ),
    Mutation(
        # This replaces an earlier entry A6, which claimed the sink aliases the record's
        # hash bytes if the defensive copies in paramsFor are removed. A6 survived, and the
        # reason is that it was not a property at all: paramsFor takes its Record by value,
        # so the language already copies the arrays before any []byte conversion happens.
        # Removing the copy changed nothing observable, and a mutation that changes nothing
        # cannot refute anything - it reports a gap in the code that is not a gap in the
        # guarantee. The copy is kept as a guard against a future pointer signature, and
        # TestParamsForTakesItsRecordByValue pins that signature directly.
        name="A11 the sink writes the batch in reverse order",
        filename="sink.go",
        old="\t\tfor _, r := range records {",
        new="\t\tfor i := len(records) - 1; i >= 0; i-- {\n\t\t\tr := records[i]",
        why="the durable order must be the chain's order. Writing a batch backwards would "
        "leave the stored sequence and the chained sequence disagreeing, which is the one "
        "comparison the integrity verifier exists to make, and it would be invisible until "
        "someone ran that verification against the real table",
    ),
    Mutation(
        name="A7 the sink continues past a failed write",
        filename="sink.go",
        # The whole two-line return is replaced, not just its first line: replacing only
        # the head leaves the argument lines dangling and the package does not build.
        old='return fmt.Errorf("exporting audit record %s (partition %s sequence %d): %w",\n\t\t\t\t\tr.AuditID, r.Partition, r.Sequence, err)',
        new="continue // mutated: skip the record that would not store and carry on",
        why="the caller releases backlog for the whole batch on success. Skipping a record "
        "that would not store and returning success lets the guard resume while the tail of "
        "the batch was never written, which is evidence loss the guard exists to prevent",
    ),
    Mutation(
        name="A8 the exporter accepts a missing sink",
        filename="sink.go",
        scope="func NewExporter(g *Guard, sink Sink) (*Exporter, error) {",
        old="\tif sink == nil {",
        new="\tif false {",
        why="an exporter with no sink writes nothing, so Exported is never called and the "
        "guard re-enters the absorbing state this type was added to end. Failing at "
        "construction is the only point where that is cheap to notice",
    ),
    Mutation(
        name="A9 the exporter accepts a missing guard",
        filename="sink.go",
        scope="func NewExporter(g *Guard, sink Sink) (*Exporter, error) {",
        old="\tif g == nil {",
        new="\tif false {",
        why="without a guard there is no backlog to release, so every Exported call is a nil "
        "dereference at the first export rather than a refusal at construction",
    ),
    Mutation(
        name="A10 the stored schema version is zeroed",
        filename="sink.go",
        old="SchemaVersion: int32(SchemaVersion),",
        new="SchemaVersion: 0,",
        why="a reader verifying a stored record's hash needs the schema version to know which "
        "canonical form produced it. A zero is not a version, and the failure surfaces as an "
        "integrity finding on records that are perfectly intact",
    ),
)



def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_tests(pkg: str = "model") -> tuple[bool, str]:
    """Run one package's tests, returning (passed, output).

    pkg names the directory under services/control-plane to test. It is a parameter rather
    than a constant so that one harness covers every package that carries claims, and so
    that a second package cannot arrive with its own copy of this machinery - a second copy
    would carry its own restore bug, and the restore bug is the one defect in this harness
    that can silently corrupt the tree.
    """
    proc = subprocess.run(
        ["go", "test", f"./{pkg}/", "-count=1"],
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


def restore(path: Path, blob: bytes) -> None:
    """Write blob back to path, retrying while the file is transiently locked.

    This is the function that must never fail silently. Every mutation leaves the tree in a
    state where a real defect is present, so a restore that gives up on the first I/O error
    hands the next person a repository with an injected bug in it and no marker saying so -
    the exact hazard this harness exists to detect, produced by the harness itself.

    Windows reports a transient sharing violation as OSError errno 22 rather than a lock
    error, and it happens here for mundane reasons: a go process from the run that just
    finished still has the file mapped, or an indexer or virus scanner opened it between the
    test run and the write. The first version of this function did a single write and let the
    error propagate. It failed on the 42nd mutation of a run, the finally block tried the
    same single write, and the tree was left holding mutation 24 - so the next baseline check
    failed for a reason that had nothing to do with the next piece of work.

    Retrying is not sufficient on its own; if the final attempt also fails, the caller must
    be told. So this raises, and the caller's finally block reports the filenames it could
    not restore rather than exiting quietly.
    """
    last: OSError | None = None
    for attempt in range(12):
        try:
            path.write_bytes(blob)
            return
        except OSError as exc:  # noqa: PERF203 - retrying is the point
            last = exc
            time.sleep(0.25 * (attempt + 1))
    raise OSError(
        f"could not restore {path} after 12 attempts over ~23s; the working tree is left "
        f"holding an injected mutation. Repair it by hand from this message. "
        f"Last error: {last}"
    )


def main() -> int:
    # The harness covers one package per run. Selecting it by argument rather than
    # duplicating the driver keeps a single restore path, and the restore path is the part
    # of this tool that must not exist twice.
    target = sys.argv[1] if len(sys.argv) > 1 else "model"
    suites = {
        "model": (MODEL_PKG, MUTATIONS, "record.go"),
        "audit": (AUDIT_PKG, AUDIT_MUTATIONS, "chain.go"),
    }
    if target not in suites:
        print(f"unknown package {target!r}; choose one of {', '.join(sorted(suites))}")
        return 2
    pkg, mutations, sentinel = suites[target]

    if not (pkg / sentinel).is_file():
        print(f"{target} package not found at {pkg}")
        return 1

    baseline_ok, baseline_out = run_tests(target)
    if not baseline_ok:
        print("BASELINE FAILS; the mutation results would be meaningless.")
        print(baseline_out[-2000:])
        return 1
    print(f"baseline: {target} tests PASS\n")

    original = {m.filename: (pkg / m.filename).read_bytes() for m in mutations}
    digests = {name: sha256(pkg / name) for name in original}

    survived: list[Mutation] = []
    skipped: list[Mutation] = []
    unrestored: list[str] = []
    applied = 0
    build_failures = 0
    try:
        for m in mutations:
            file = pkg / m.filename
            # Every mutation is applied to the pristine tree and restored immediately.
            # Restoring only at the end would let mutations on the same file compound, and a
            # test failure would then no longer be attributable to the mutation it is
            # reported under. A mutation check that cannot say which change it detected is
            # not evidence.
            restore(file, original[m.filename])
            text = file.read_text(encoding="utf-8")
            mutated = apply_mutation(m, text)
            if mutated is None:
                skipped.append(m)
                print(f"SKIP  {m.name}: anchor not found in {m.filename}")
                continue
            file.write_text(mutated, encoding="utf-8", newline="\n")
            applied += 1
            passed, out = run_tests(target)
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
                elif "build failed" in out or "undefined:" in out:
                    # A compile failure is not a detection. The harness records this
                    # distinction because a broken build satisfies "the tests did not
                    # pass" while exercising none of them, and a summary that calls both
                    # "detected" claims coverage it never had.
                    build_failures += 1
                    print("          NO TEST RAN - the package failed to build")
            # Restore before the next mutation so each is measured in isolation.
            restore(file, original[m.filename])
    finally:
        # The final sweep is the one that matters. If any file here cannot be restored the
        # tree is left holding an injected defect, so the failure is reported by filename
        # rather than swallowed by an exception escaping a finally block.
        for name, blob in original.items():
            try:
                restore(pkg / name, blob)
            except OSError as exc:
                unrestored.append(f"{name}: {exc}")
        if unrestored:
            print("\nRESTORE FAILED - the tree holds an injected mutation in:")
            for line in unrestored:
                print(f"  - {line}")

    print()
    restored = all(sha256(pkg / name) == digests[name] for name in digests)
    print(f"restored byte-for-byte: {restored}")
    print(f"applied {applied} of {len(mutations)} mutations")
    print(f"detected {applied - len(survived)}; survived {len(survived)}; skipped {len(skipped)}")
    if build_failures:
        # Counted separately, and fatal on their own: a mutation that "detected" only by
        # breaking the build has verified nothing. Reporting it as coverage is the specific
        # error this line exists to prevent.
        print(f"of which {build_failures} were build failures with no test run - NOT detections")

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
    if build_failures:
        print("\nBUILD-FAILURE MUTATIONS (no test ran, so nothing was verified):")
        return 1
    if unrestored:
        return 1
    if not restored:
        print("\nRESTORE FAILED: the working tree does not match the pre-mutation state")
        return 1
    print(f"\nall {target} mutations applied and detected; every claimed rule is enforced "
          f"by a failing test")
    return 0


if __name__ == "__main__":
    sys.exit(main())
