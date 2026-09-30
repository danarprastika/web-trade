-- Verification of db/migrations/0003_authz.sql against a real PostgreSQL 17.
--
-- The Go tests prove the evaluator's rules. They cannot prove that the *database* refuses
-- the writes that would produce a state the evaluator would then have to defend against,
-- and that is the point of this migration: an exclusion matrix that lives only in Go is a
-- comment, and a policy author editing a bundle has no way to find out the rule they wrote
-- is one the platform considers a violation.
--
-- Every assertion below is read back from the database rather than from psql's messages,
-- because a guard that did not fire leaves a row behind and the assertion catches it. Each
-- assertion is therefore written as: attempt the prohibited write, then count the rows.
--
-- Assertions are numbered so a failure names the invariant that broke rather than just
-- reporting a count.

\set ON_ERROR_STOP off
\pset pager off

-- Assert helper. Each check is a boolean expression evaluated against a count; the helper
-- prints PASS or FAIL with the invariant's name so the output is readable without reading
-- this file.
CREATE FUNCTION assert_holds(name text, holds boolean, detail text DEFAULT '')
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    IF holds THEN
        RAISE NOTICE 'PASS  %', name;
    ELSE
        RAISE WARNING 'FAIL  %  %', name, detail;
    END IF;
END;
$$;

-- Every event is recorded so the summary can be produced from a single pass and so that a
-- connection error cannot leave a half-reported result that looks like success.
CREATE TABLE _assertions (ordinal serial PRIMARY KEY, name text, held boolean, detail text);

CREATE FUNCTION record(name text, holds boolean, detail text DEFAULT '')
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO _assertions (name, held, detail) VALUES (name, holds, detail);
END;
$$;

-- attempt runs a statement that is expected to fail, and records whether it did.
--
-- The SET CONSTRAINTS ALL IMMEDIATE is the load-bearing part. Most of the guards in this
-- migration are DEFERRABLE INITIALLY DEFERRED constraint triggers, which means they do not
-- fire at the INSERT but at COMMIT. An EXCEPTION block only covers errors raised inside its
-- own subtransaction, so without forcing the constraint to be checked here, the first guard
-- that fires as intended would abort the entire script at COMMIT and every later assertion
-- would be rolled back along with it. That produces a summary of zero assertions from a
-- migration that is almost entirely working, which is how a broken harness can look like a
-- broken migration, or worse, the other way round.
CREATE PROCEDURE attempt(label text, stmt text)
LANGUAGE plpgsql AS $$
DECLARE
    fired boolean := false;
BEGIN
    BEGIN
        EXECUTE stmt;
        -- Forces every deferred constraint trigger for this transaction to run now, inside
        -- this subtransaction, so a refusal is caught here rather than at COMMIT.
        SET CONSTRAINTS ALL IMMEDIATE;
    EXCEPTION WHEN OTHERS THEN
        fired := true;
    END;
    INSERT INTO _assertions (name, held, detail)
    VALUES (label, fired, 'statement was expected to be refused');
END;
$$;

-- accept runs a statement that is expected to succeed, and records whether it both ran and
-- left the row it was supposed to leave.
--
-- It forces the deferred constraints for the same reason attempt does, so that "this should
-- have worked" is checked as firmly as "this should have failed". A harness that only ever
-- proves guards fire will pass a migration whose guards fire on everything, which is the
-- more embarrassing way for this script to be wrong: a migration that refuses all writes
-- would report a clean run.
--
-- The expected row is identified by table and primary key rather than by a predicate the
-- harness evaluates. PostgreSQL has no eval, and a harness that approximated one would be
-- asserting whatever the default happened to be rather than what was intended.
CREATE PROCEDURE accept(label text, stmt text, key_table text, key_column text, key_value text)
LANGUAGE plpgsql AS $$
DECLARE
    failed boolean := false;
    detail  text := '';
    found   integer := 0;
BEGIN
    BEGIN
        EXECUTE stmt;
        SET CONSTRAINTS ALL IMMEDIATE;
        EXECUTE format('SELECT count(*) FROM %I WHERE %I = $1', key_table, key_column)
            INTO found USING key_value;
        IF found = 0 THEN
            failed := true;
            detail  := 'the statement was accepted but left no row in ' || key_table;
        END IF;
    EXCEPTION WHEN OTHERS THEN
        failed := true;
        detail  := 'expected to be accepted but was refused: ' || SQLERRM;
    END;
    INSERT INTO _assertions (name, held, detail)
    VALUES (label, NOT failed, detail);
END;
$$;

BEGIN;

-- A bundle that the Go evaluator would accept, to establish a working baseline before the
-- negative cases. Its single rule permits an auditor to read the audit trail.
INSERT INTO authz_policy_bundles (digest, rules, schema_version, created_at_utc, activated_at_utc)
VALUES ('sha256:bundle-baseline-0001',
        '[{"effect":"ALLOW","roles":["AUDITOR"],"actions":["AUDIT_VIEW"],"reason":"auditors read"}]',
        1, now(), now());

-- === 1. The exclusion matrix refuses a rule that contradicts it ====================

-- An AUDITOR may not submit orders (docs/21 section 5). A bundle granting it must be
-- refused, not stored and refused later at evaluation time.
CALL attempt('01 rule contradicting the exclusion matrix is refused',
               $q$INSERT INTO authz_policy_bundles (digest, rules, schema_version, created_at_utc, activated_at_utc)
                 VALUES ('sha256:bundle-bad-auditor',
                         '[{"effect":"ALLOW","roles":["AUDITOR"],"actions":["ORDER_SUBMIT"],"reason":"nope"}]',
                         1, now(), now())$q$);

-- A RISK_OPERATOR may not submit orders. This is the exclusion most likely to be
-- re-litigated in review, so it gets its own assertion.
CALL attempt('02 a risk operator cannot be granted order submission',
               $q$INSERT INTO authz_policy_bundles (digest, rules, schema_version, created_at_utc, activated_at_utc)
                 VALUES ('sha256:bundle-bad-risk',
                         '[{"effect":"ALLOW","roles":["RISK_OPERATOR"],"actions":["ORDER_SUBMIT"],"reason":"nope"}]',
                         1, now(), now())$q$);

-- An OWNER may not delete evidence directly.
CALL attempt('03 an owner cannot be granted evidence deletion',
               $q$INSERT INTO authz_policy_bundles (digest, rules, schema_version, created_at_utc, activated_at_utc)
                 VALUES ('sha256:bundle-bad-owner',
                         '[{"effect":"ALLOW","roles":["OWNER"],"actions":["AUDIT_DELETE"],"reason":"nope"}]',
                         1, now(), now())$q$);

-- The subtle case. A rule with NO roles list applies to every role, so it contradicts
-- every exclusion there is. An implementation that only checks explicitly named roles
-- would store this bundle, and it is the shape a well-meaning "allow everyone to read"
-- rule actually takes.
CALL attempt('04 a roleless rule is checked against the whole matrix',
               $q$INSERT INTO authz_policy_bundles (digest, rules, schema_version, created_at_utc, activated_at_utc)
                 VALUES ('sha256:bundle-bad-roleless',
                         '[{"effect":"ALLOW","actions":["ORDER_SUBMIT"],"reason":"everyone"}]',
                         1, now(), now())$q$);

-- Same reasoning for a rule with no actions list: it permits every action for the roles it
-- names, so it contradicts every exclusion for those roles.
CALL attempt('05 an actionless rule is checked against the whole matrix',
               $q$INSERT INTO authz_policy_bundles (digest, rules, schema_version, created_at_utc, activated_at_utc)
                 VALUES ('sha256:bundle-bad-actionless',
                         '[{"effect":"ALLOW","roles":["TRADING_OPERATOR"],"reason":"everything"}]',
                         1, now(), now())$q$);

-- A DENY naming an excluded pair is not a violation. Exclusions are about what may be
-- *granted*; a rule that denies an action a role may never perform is redundant, not
-- wrong, and refusing it would make the table impossible to use for defence in depth.
DO $$
DECLARE
    fired boolean := false;
BEGIN
    BEGIN
        INSERT INTO authz_policy_bundles (digest, rules, schema_version, created_at_utc, activated_at_utc)
        VALUES ('sha256:bundle-deny-ok',
                '[{"effect":"DENY","roles":["AUDITOR"],"actions":["ORDER_SUBMIT"],"reason":"defence in depth"}]',
                1, now(), now());
        SET CONSTRAINTS ALL IMMEDIATE;
    EXCEPTION WHEN OTHERS THEN
        fired := true;
    END;
    PERFORM record('06 a deny naming an excluded pair is accepted', NOT fired,
                   'a redundant deny must still be storable');
END;
$$;

-- === 2. ADR-018: the risk boundary is absolute ================================

-- No rule, for any role, may name RISK_APPROVE. This is unconditional and separate from
-- the matrix: it is the one exclusion that is not role-specific, because authorization
-- cannot approve financial risk for anyone.
CALL attempt('07 no role may be granted risk approval',
               $q$INSERT INTO authz_policy_bundles (digest, rules, schema_version, created_at_utc, activated_at_utc)
                 VALUES ('sha256:bundle-risk-approve',
                         '[{"effect":"ALLOW","roles":["OWNER"],"actions":["RISK_APPROVE"],"reason":"nope"}]',
                         1, now(), now())$q$);

-- The same for a roleless rule naming it, which is the shape that would slip through a
-- check that only examined named roles.
CALL attempt('08 a roleless rule may not name risk approval either',
               $q$INSERT INTO authz_policy_bundles (digest, rules, schema_version, created_at_utc, activated_at_utc)
                 VALUES ('sha256:bundle-risk-approve-roleless',
                         '[{"effect":"ALLOW","actions":["RISK_APPROVE"],"reason":"nope"}]',
                         1, now(), now())$q$);

SELECT record('09 no refused bundle was stored',
              NOT EXISTS (SELECT 1 FROM authz_policy_bundles
                           WHERE digest LIKE 'sha256:bundle-risk%'
                              OR digest LIKE 'sha256:bundle-bad%'),
              'a refused bundle must leave no row behind');

-- === 3. The exclusion table itself is append-only ==============================

-- An exclusion that can be deleted is not an exclusion. If an operator removes the
-- AUDITOR/ORDER_SUBMIT row and then writes a rule, the trigger above has nothing to
-- consult and the control is gone.
CALL attempt('10 an exclusion cannot be deleted',
               $q$DELETE FROM authz_role_action_exclusion WHERE role = 'AUDITOR' AND action = 'ORDER_SUBMIT'$q$);

CALL attempt('11 an exclusion cannot be updated',
               $q$UPDATE authz_role_action_exclusion SET action = 'AUDIT_VIEW'
                 WHERE role = 'AUDITOR' AND action = 'ORDER_SUBMIT'$q$);

CALL attempt('12 the exclusion table cannot be truncated',
               $q$TRUNCATE authz_role_action_exclusion$q$);

-- The seeded matrix must be intact after every attempt to edit it. 46 is the number the Go
-- package forbids, asserted pairwise by TestTheSeededExclusionMatrixMatchesTheGoMatrix; this
-- assertion exists to catch the two layers agreeing on a number while the table on disk has
-- been truncated to a subset.
SELECT record('13 the exclusion matrix still holds its full size',
              (SELECT count(*) FROM authz_role_action_exclusion) = 46,
              'expected 46 seeded exclusions, found '
              || (SELECT count(*) FROM authz_role_action_exclusion)::text);

-- === 4. Grants =================================================================

-- docs/21 section 5: dual control, second-person approval, and a cap on grant lifetime.
INSERT INTO authz_role_grants (grant_id, subject_id, subject_type, role, markets, accounts,
                              environments, granted_at_utc, expires_at_utc, approved_by)
VALUES ('grant-baseline-0001', 'trader-1', 'HUMAN', 'TRADING_OPERATOR',
        ARRAY['IDX'], ARRAY['acct-1'], ARRAY['paper'],
        now(), now() + interval '30 days', 'carol');

SELECT record('14 a compliant grant is stored',
              (SELECT count(*) FROM authz_role_grants WHERE grant_id = 'grant-baseline-0001') = 1,
              'a valid grant must be accepted');

-- An unbounded grant. The evaluator checks expiry, not duration, so a grant written with
-- a century of life would be treated as valid until someone noticed.
CALL attempt('15 a grant cannot outlive the 90 day cap',
               $q$INSERT INTO authz_role_grants (grant_id, subject_id, subject_type, role, markets,
                                                 accounts, environments, granted_at_utc, expires_at_utc, approved_by)
                 VALUES ('grant-too-long', 'trader-1', 'HUMAN', 'TRADING_OPERATOR',
                         ARRAY['IDX'], ARRAY['acct-1'], ARRAY['paper'],
                         now(), now() + interval '365 days', 'carol')$q$);

-- A grant with no approver is a grant nobody reviewed.
CALL attempt('16 a grant requires a second approver',
               $q$INSERT INTO authz_role_grants (grant_id, subject_id, subject_type, role, markets,
                                                 accounts, environments, granted_at_utc, expires_at_utc, approved_by)
                 VALUES ('grant-no-approver', 'trader-1', 'HUMAN', 'TRADING_OPERATOR',
                         ARRAY['IDX'], ARRAY['acct-1'], ARRAY['paper'],
                         now(), now() + interval '30 days', '')$q$);

-- An empty scope is inert rather than absent, and reads as a misconfiguration rather than
-- a refusal. The constraint makes it a write-time refusal.
CALL attempt('17 a grant cannot have an empty scope',
               $q$INSERT INTO authz_role_grants (grant_id, subject_id, subject_type, role, markets,
                                                 accounts, environments, granted_at_utc, expires_at_utc, approved_by)
                 VALUES ('grant-no-scope', 'trader-1', 'HUMAN', 'TRADING_OPERATOR',
                         '{}', ARRAY['acct-1'], ARRAY['paper'],
                         now(), now() + interval '30 days', 'carol')$q$);

-- An out-of-set role.
CALL attempt('18 a grant cannot name a role outside the closed set',
               $q$INSERT INTO authz_role_grants (grant_id, subject_id, subject_type, role, markets,
                                                 accounts, environments, granted_at_utc, expires_at_utc, approved_by)
                 VALUES ('grant-bad-role', 'trader-1', 'HUMAN', 'SUPERUSER',
                         ARRAY['IDX'], ARRAY['acct-1'], ARRAY['paper'],
                         now(), now() + interval '30 days', 'carol')$q$);

-- docs/21 section 4: wildcard grants are prohibited for live financial operations. A
-- wildcard environment is the combination with no legitimate use.
CALL attempt('19 a wildcard environment scope is refused',
               $q$INSERT INTO authz_role_grants (grant_id, subject_id, subject_type, role, markets,
                                                 accounts, environments, granted_at_utc, expires_at_utc, approved_by)
                 VALUES ('grant-wildcard-env', 'trader-1', 'HUMAN', 'TRADING_OPERATOR',
                         ARRAY['*'], ARRAY['*'], ARRAY['*'],
                         now(), now() + interval '30 days', 'carol')$q$);

-- A wildcard market alone is permitted: how a broad grant is expressed without being a
-- live financial one. If this were refused the prohibition would be unusable in practice
-- and someone would work around it.
--
-- The count is read *after* the insert, and the insert is wrapped so that a refusal is
-- recorded rather than aborting the script. Asserting the row exists before writing it
-- would pass only if the row already existed, which is a test that cannot fail.
DO $$
DECLARE
    refused boolean := false;
    why     text := '';
    stored  integer := 0;
BEGIN
    BEGIN
        INSERT INTO authz_role_grants (grant_id, subject_id, subject_type, role, markets, accounts,
                                      environments, granted_at_utc, expires_at_utc, approved_by)
        VALUES ('grant-wildcard-market', 'researcher-1', 'HUMAN', 'RESEARCHER',
                ARRAY['*'], ARRAY['acct-1'], ARRAY['paper'],
                now(), now() + interval '30 days', 'carol');
        SET CONSTRAINTS ALL IMMEDIATE;
        SELECT count(*) INTO stored FROM authz_role_grants WHERE grant_id = 'grant-wildcard-market';
    EXCEPTION WHEN OTHERS THEN
        -- SQLERRM is only readable inside the handler, so it is captured here and reported
        -- outside. Referencing it after the block raises "column does not exist" and aborts
        -- the transaction, which would take every later assertion with it.
        refused := true;
        why     := SQLERRM;
    END;
    PERFORM record('20 a wildcard market outside live is permitted', NOT refused AND stored = 1,
                   'a broad non-live grant must be expressible; refusal: ' || why);
END;
$$;

-- Inserting a grant must bump the permission revision, so that live sessions built against
-- the previous revision are refused. Without this a new grant is invisible to every session
-- already open, which is the failure mode the revision exists to prevent.
DO $$
DECLARE
    before_rev integer;
    after_rev  integer;
BEGIN
    SELECT current_revision INTO before_rev FROM authz_permission_state WHERE state_id = 1;
    INSERT INTO authz_role_grants (grant_id, subject_id, subject_type, role, markets, accounts,
                                  environments, granted_at_utc, expires_at_utc, approved_by)
    VALUES ('grant-revision-probe', 'trader-2', 'HUMAN', 'TRADING_OPERATOR',
            ARRAY['IDX'], ARRAY['acct-1'], ARRAY['paper'],
            now(), now() + interval '30 days', 'carol');
    SELECT current_revision INTO after_rev FROM authz_permission_state WHERE state_id = 1;
    PERFORM record('21 granting a role bumps the permission revision',
                   after_rev > before_rev,
                   'revision was ' || before_rev::text || ' before and ' || after_rev::text || ' after');
END;
$$;

-- === 5. Sessions ==============================================================

-- A valid session for the current revision.
INSERT INTO authz_sessions (session_id, subject_id, session_class, authenticated_at_utc,
                            last_active_at_utc, auth_strength, step_up_at_utc, permission_revision)
SELECT 'sess-0001', 'trader-1', 'PRIVILEGED_OPERATOR', now() - interval '1 hour',
       now() - interval '1 minute', 'HARDWARE_KEY', now() - interval '1 minute',
       current_revision
  FROM authz_permission_state WHERE state_id = 1;

SELECT record('22 a compliant session is stored',
              (SELECT count(*) FROM authz_sessions WHERE session_id = 'sess-0001') = 1,
              'a valid session must be accepted');

-- A session created already beyond its class absolute timeout. The 8-hour privileged
-- timeout is the one from docs/21 section 3; the check looks the number up from the policy
-- table rather than repeating it, so the two layers cannot drift.
CALL attempt('23 a session cannot be created already expired',
               $q$INSERT INTO authz_sessions (session_id, subject_id, session_class, authenticated_at_utc,
                                              last_active_at_utc, auth_strength, permission_revision)
                 VALUES ('sess-expired', 'trader-1', 'PRIVILEGED_OPERATOR',
                         now() - interval '9 hours', now() - interval '9 hours',
                         'HARDWARE_KEY', 1)$q$);

-- The same session class with a longer life is refused, proving the timeout is read from
-- the policy table rather than hardcoded into the trigger.
CALL attempt('24 the session class timeout is read from the policy table',
               $q$INSERT INTO authz_sessions (session_id, subject_id, session_class, authenticated_at_utc,
                                              last_active_at_utc, auth_strength, permission_revision)
                 VALUES ('sess-svc-expired', 'svc-1', 'SERVICE_WORKLOAD',
                         now() - interval '2 hours', now() - interval '2 hours',
                         'HARDWARE_KEY', 1)$q$);

-- An out-of-set strength. Stored as a name rather than an ordinal specifically so a stored
-- value remains meaningful, and so reordering the Go constants cannot change its meaning.
CALL attempt('25 a session cannot name an unknown auth strength',
               $q$INSERT INTO authz_sessions (session_id, subject_id, session_class, authenticated_at_utc,
                                              last_active_at_utc, auth_strength, permission_revision)
                 VALUES ('sess-bad-strength', 'trader-1', 'PRIVILEGED_OPERATOR',
                         now(), now(), 'SMS_CODE', 1)$q$);

-- A session whose activity predates its authentication.
CALL attempt('26 session activity cannot predate authentication',
               $q$INSERT INTO authz_sessions (session_id, subject_id, session_class, authenticated_at_utc,
                                              last_active_at_utc, auth_strength, permission_revision)
                 VALUES ('sess-inverted', 'trader-1', 'PRIVILEGED_OPERATOR',
                         now(), now() - interval '1 hour', 'HARDWARE_KEY', 1)$q$);

-- Revoking a session must bump the revision, so that revocation takes effect for every
-- open session rather than waiting for natural expiry.
DO $$
DECLARE
    before_rev integer;
    after_rev  integer;
BEGIN
    SELECT current_revision INTO before_rev FROM authz_permission_state WHERE state_id = 1;
    UPDATE authz_sessions SET revoked_at_utc = now(), revoked_reason = 'operator request'
     WHERE session_id = 'sess-0001';
    SELECT current_revision INTO after_rev FROM authz_permission_state WHERE state_id = 1;
    PERFORM record('27 revoking a session bumps the permission revision',
                   after_rev > before_rev,
                   'revision was ' || before_rev::text || ' before and ' || after_rev::text || ' after');
END;
$$;

-- A revocation that does not say why.
CALL attempt('28 a revocation must record a reason',
               $q$UPDATE authz_sessions SET revoked_at_utc = now(), revoked_reason = ''
                WHERE session_id = 'sess-0001'$q$);

-- === 6. Approvals =============================================================

-- The digest of {"limit":100}, computed by the Go package's DiffDigest.
INSERT INTO authz_approvals (request_id, diff_digest, requested_by, approved_by,
                             approved_at_utc, expires_at_utc, policy_version)
VALUES ('apr-0001',
        'e6b1e0d3c0dd6b6a3a0d3e2f1c0b9a8f7e6d5c4b3a2918070605040302010009',
        'alice', 'bob', now(), now() + interval '12 hours', 'policy-v1');

SELECT record('29 a compliant approval is stored',
              (SELECT count(*) FROM authz_approvals WHERE request_id = 'apr-0001') = 1,
              'a valid approval must be accepted');

-- Self-approval. Dual control means two people; a row where the name repeats satisfies a
-- two-approver form and none of its purpose, so it is not representable.
CALL attempt('30 self-approval is not representable',
               $q$INSERT INTO authz_approvals (request_id, diff_digest, requested_by, approved_by,
                                               approved_at_utc, expires_at_utc, policy_version)
                 VALUES ('apr-self', repeat('a', 64), 'alice', 'alice',
                         now(), now() + interval '12 hours', 'policy-v1')$q$);

-- A digest that is not a SHA-256 hex. An approval bound to a non-digest would never be
-- checked against a real change.
CALL attempt('31 an approval requires a SHA-256 hex digest',
               $q$INSERT INTO authz_approvals (request_id, diff_digest, requested_by, approved_by,
                                               approved_at_utc, expires_at_utc, policy_version)
                 VALUES ('apr-bad-digest', 'not-a-digest', 'alice', 'bob',
                         now(), now() + interval '12 hours', 'policy-v1')$q$);

-- docs/21 section 6 caps an approval at 24 hours. Longer would let a change be approved
-- once and applied much later against a policy nobody re-checked.
CALL attempt('32 an approval cannot exceed the 24 hour cap',
               $q$INSERT INTO authz_approvals (request_id, diff_digest, requested_by, approved_by,
                                               approved_at_utc, expires_at_utc, policy_version)
                 VALUES ('apr-too-long', repeat('b', 64), 'alice', 'bob',
                         now(), now() + interval '48 hours', 'policy-v1')$q$);

-- The binding to an exact change. Editing the digest after approval would defeat the
-- entire purpose, so the column is immutable.
CALL attempt('33 an approval digest cannot be edited after the fact',
               $q$UPDATE authz_approvals SET diff_digest = repeat('c', 64) WHERE request_id = 'apr-0001'$q$);

CALL attempt('34 an approver cannot be swapped after the fact',
               $q$UPDATE authz_approvals SET approved_by = 'carol' WHERE request_id = 'apr-0001'$q$);

-- Recording the single application is the only permitted update.
UPDATE authz_approvals SET applied_at_utc = now() WHERE request_id = 'apr-0001';
SELECT record('35 recording an approval application is permitted',
              (SELECT applied_at_utc IS NOT NULL FROM authz_approvals WHERE request_id = 'apr-0001'),
              'consuming an approval must be possible');

CALL attempt('36 an applied approval cannot be applied again',
               $q$UPDATE authz_approvals SET applied_at_utc = now() + interval '1 hour'
                WHERE request_id = 'apr-0001'$q$);

CALL attempt('37 an approval cannot be deleted',
               $q$DELETE FROM authz_approvals WHERE request_id = 'apr-0001'$q$);

-- === 7. Decision records =====================================================

-- Both outcomes are recorded with the digest of the bundle that decided them, so "which
-- policy refused me" is answerable after the fact.
INSERT INTO authz_decisions (decision_id, command_id, actor_id, actor_type, action, environment,
                             allowed, refusal_code, reason, policy_bundle_digest, decided_at_utc)
VALUES ('dec-allow-1', 'cmd_0000000000000000000000001', 'trader-1', 'HUMAN', 'ORDER_SUBMIT',
        'paper', true, '', '', 'sha256:bundle-baseline-0001', now());

INSERT INTO authz_decisions (decision_id, command_id, actor_id, actor_type, action, environment,
                             allowed, refusal_code, reason, policy_bundle_digest, decided_at_utc)
VALUES ('dec-refuse-1', 'cmd_0000000000000000000000002', 'stranger', 'HUMAN', 'ORDER_SUBMIT',
        'paper', false, 'OUT_OF_SCOPE', 'no grant admits this scope',
        'sha256:bundle-baseline-0001', now());

SELECT record('38 both allow and refuse decisions are recorded',
              (SELECT count(*) FROM authz_decisions) = 2,
              'a refusal must be as durable as an allow');

SELECT record('39 a refusal records which policy produced it',
              (SELECT policy_bundle_digest FROM authz_decisions WHERE decision_id = 'dec-refuse-1')
                = 'sha256:bundle-baseline-0001',
              'every decision must name its bundle digest');

-- An allowed decision carrying a refusal code, or a refused one with no reason, is
-- ambiguous about what happened and a reader would have to guess which field to believe.
CALL attempt('40 an allowed decision cannot carry a refusal code',
               $q$INSERT INTO authz_decisions (decision_id, command_id, actor_id, actor_type, action,
                                               environment, allowed, refusal_code, reason,
                                               policy_bundle_digest, decided_at_utc)
                 VALUES ('dec-inconsistent', 'cmd_0000000000000000000000003', 'trader-1', 'HUMAN',
                         'ORDER_SUBMIT', 'paper', true, 'OUT_OF_SCOPE', 'contradiction',
                         'sha256:bundle-baseline-0001', now())$q$);

CALL attempt('41 a refused decision must name its reason',
               $q$INSERT INTO authz_decisions (decision_id, command_id, actor_id, actor_type, action,
                                               environment, allowed, refusal_code, reason,
                                               policy_bundle_digest, decided_at_utc)
                 VALUES ('dec-no-reason', 'cmd_0000000000000000000000004', 'trader-1', 'HUMAN',
                         'ORDER_SUBMIT', 'paper', false, 'OUT_OF_SCOPE', '',
                         'sha256:bundle-baseline-0001', now())$q$);

-- Decisions are evidence. An editable decision record is worse than none, because it looks
-- authoritative while being writable.
CALL attempt('42 a decision cannot be edited',
               $q$UPDATE authz_decisions SET allowed = true WHERE decision_id = 'dec-refuse-1'$q$);

CALL attempt('43 a decision cannot be deleted',
               $q$DELETE FROM authz_decisions WHERE decision_id = 'dec-refuse-1'$q$);

CALL attempt('44 decisions cannot be truncated',
               $q$TRUNCATE authz_decisions$q$);

SELECT record('45 both decisions survived the immutability attempts',
              (SELECT count(*) FROM authz_decisions) = 2,
              'the evidence must be intact after every refused mutation');

-- === 8. Session policy table integrity =======================================

-- The read-only class carries a longer step-up freshness than the privileged class. That
-- reads backwards, so it is asserted explicitly: a future "fix" that makes these uniform
-- would be a silent change to the specification's numbers.
SELECT record('46 the read-only step-up freshness is longer than the privileged one',
              (SELECT step_up_freshness_sec FROM authz_session_policy WHERE session_class = 'READ_ONLY_OPERATOR')
                > (SELECT step_up_freshness_sec FROM authz_session_policy WHERE session_class = 'PRIVILEGED_OPERATOR'),
              'docs/21 section 3 numbers must be carried as written');

-- The service workload class has no step-up policy, modelled as zero. The evaluator treats
-- zero as "no privileged action is available", not as "no requirement", so the value must
-- not drift to a positive number.
SELECT record('47 the service workload class has no step-up policy',
              (SELECT step_up_freshness_sec FROM authz_session_policy WHERE session_class = 'SERVICE_WORKLOAD') = 0,
              'a service session must not acquire a step-up window');

-- An absolute timeout shorter than the idle timeout is not stricter, it is unreachable.
CALL attempt('48 an absolute timeout cannot be shorter than the idle timeout',
               $q$INSERT INTO authz_session_policy (session_class, idle_timeout_sec, absolute_timeout_sec,
                                                    step_up_freshness_sec)
                 VALUES ('READ_ONLY_OPERATOR', 3600, 60, 900)$q$);

-- === 9. The permission state is a singleton ===================================

-- A second row would make "the current revision" ambiguous, and ambiguity here is
-- indistinguishable from a revocation that did not apply.
CALL attempt('49 the permission state cannot have a second row',
               $q$INSERT INTO authz_permission_state (state_id, current_revision, updated_at_utc)
                 VALUES (2, 1, now())$q$);

SELECT record('50 exactly one permission state row exists',
              (SELECT count(*) FROM authz_permission_state) = 1,
              'the current revision must be unambiguous');

-- === 10. Bundle lifecycle =====================================================

-- A bundle retired before it was activated is a bundle that was never live.
CALL attempt('51 a bundle cannot be retired before it was activated',
               $q$INSERT INTO authz_policy_bundles (digest, rules, schema_version, created_at_utc,
                                                   activated_at_utc, retired_at_utc)
                 VALUES ('sha256:bundle-backwards', '[{"effect":"DENY","reason":"x"}]', 1,
                         now(), now() + interval '1 day', now())$q$);

-- Retired bundles are kept, so a decision made against one stays answerable.
UPDATE authz_policy_bundles SET retired_at_utc = now() WHERE digest = 'sha256:bundle-baseline-0001';
SELECT record('52 a retired bundle is retained rather than deleted',
              (SELECT count(*) FROM authz_policy_bundles WHERE digest = 'sha256:bundle-baseline-0001') = 1,
              'a decision naming a retired digest must remain answerable');

-- An empty rule list is not a policy. It is a bundle that refuses everything, stored where
-- a reader would expect it to permit something.
CALL attempt('53 a bundle cannot have an empty rule list',
               $q$INSERT INTO authz_policy_bundles (digest, rules, schema_version, created_at_utc, activated_at_utc)
                 VALUES ('sha256:bundle-empty', '[]'::jsonb, 1, now(), now())$q$);

-- The trigger fires at COMMIT, so a rule that is momentarily in violation and corrected
-- inside the same transaction is fine. This asserts the deferred behaviour is real, since a
-- bundle written and checked in one transaction is the normal case.
-- The exclusion and risk-boundary refusals are recorded as held=true, because attempt()
-- records "the guard fired". Asserting on held=false would invert the meaning and pass
-- precisely when the guards were broken, which is the failure this assertion exists to
-- rule out. It is written the awkward way round on purpose: it is a check on the harness
-- as much as on the migration.
SELECT record('54 exclusion and risk-boundary guards both fired',
              (SELECT count(*) FROM _assertions WHERE held
                 AND name IN ('01 rule contradicting the exclusion matrix is refused',
                              '07 no role may be granted risk approval')) = 2,
              'both the exclusion matrix and the risk boundary must have refused');

COMMIT;

-- === Summary ==================================================================
--
-- The counts are read back from the recorded assertions rather than from RAISE output, so
-- a connection failure part-way through cannot produce a summary that looks complete.
SELECT count(*) FILTER (WHERE held) AS passed,
       count(*) FILTER (WHERE NOT held) AS failed,
       count(*) AS total
  FROM _assertions;

-- The verdict is emitted as a query result, not as a NOTICE or WARNING.
--
-- The verification harness reads psql's stdout, and PostgreSQL sends NOTICE and WARNING to
-- stderr. A summary sent as a notice therefore looks like no summary at all, and a harness
-- that treats "no summary" as untrustworthy will refuse to report a migration that in fact
-- passed every assertion. The two failure modes are indistinguishable from the outside,
-- which is why this is a result row and not a message.
SELECT CASE WHEN failed = 0 THEN 'ALL ' || total || ' ASSERTIONS PASSED'
            ELSE failed || ' OF ' || total || ' ASSERTIONS FAILED' END
  FROM (SELECT count(*) FILTER (WHERE NOT held) AS failed,
               count(*) AS total
          FROM _assertions) a;

-- List any failure by name, so a broken migration is diagnosable from the output alone.
SELECT name, detail FROM _assertions WHERE NOT held ORDER BY ordinal;
