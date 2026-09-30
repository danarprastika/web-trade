-- Verification of db/migrations/0004_model_registry.sql against a real PostgreSQL 17.
--
-- The Go tests prove the journal's ordering: that the lifecycle state is written only after
-- the audit chain accepts the record describing it. They cannot prove that the *database*
-- refuses the writes that would produce a state the journal would then have to defend
-- against, and that is the point of this migration. A lifecycle guard that lives only in Go
-- is a comment, and a second writer that does not go through the journal could promote a
-- QUARANTINED model by writing PROMOTED, with nothing in the store refusing it.
--
-- Every assertion is written as: attempt the prohibited write, then count the rows. A guard
-- that did not fire leaves a row behind and the count catches it, so the assertion does not
-- depend on reading an error message.
--
-- Two rules keep this script honest, and both were learned by breaking them:
--
--   1. Every write that is expected to fail is wrapped in a DO block with an exception
--      handler. An unhandled error inside an explicit transaction aborts the whole
--      transaction, every later statement then fails with "current transaction is
--      aborted", and the assertion table rolls back with it - which reports ALL 0 ASSERTIONS
--      PASSED. A verification script that reports success while asserting nothing is worse
--      than one that fails, so the total is asserted at the end rather than assumed.
--
--   2. The handler catches OTHERS rather than a named condition. The assertion is about
--      whether the row is absent, not about which constraint refused it, and naming the
--      condition would make a script that fails for a different reason report a pass.

\set ON_ERROR_STOP off
\pset pager off

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

CREATE TABLE _assertions (ordinal serial PRIMARY KEY, name text, held boolean, detail text);

CREATE FUNCTION record_that(name text, holds boolean, detail text DEFAULT '')
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO _assertions (name, held, detail) VALUES (name, holds, detail);
    PERFORM assert_holds(name, holds, detail);
END;
$$;

-- Attempt a statement that is expected to be refused. The refusal is not inspected, only the
-- absence of the row afterwards, which is what the assertions count.
CREATE FUNCTION attempt(stmt text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    EXECUTE stmt;
EXCEPTION WHEN OTHERS THEN
    NULL;
END;
$$;

-- Attempt a statement that is expected to succeed. If it is refused the fixture is missing
-- and the assertions counting on it fail loudly rather than passing on an empty set.
CREATE FUNCTION attempt_ok(stmt text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    EXECUTE stmt;
EXCEPTION WHEN OTHERS THEN
    RAISE EXCEPTION 'a fixture that must be accepted was refused: % -- %', stmt, SQLERRM;
END;
$$;

CREATE FUNCTION _model_id(n integer) RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT 'mdl_0000000000000000000000000000' || n;
$$;

-- A complete eleven-field model record as an INSERT statement. Any field a test needs to vary
-- is a parameter, so a test meaning to vary one field cannot accidentally vary another.
CREATE FUNCTION _insert_model(mid text, ver text, owner text, author text, lim text,
                              st text, audit_id text DEFAULT 'audit-seed',
                              dataset text DEFAULT NULL, rollback text DEFAULT NULL)
RETURNS text LANGUAGE sql AS $$
    SELECT format(
        'INSERT INTO model_registry (model_id, version, owner, author, '
        'training_dataset_fingerprint, code_revision, feature_specification, '
        'evaluation_results, limitations, deployment_scope, monitoring_policy, '
        'rollback_artifact, state, registered_at_utc, last_audit_id, updated_by, updated_at_utc) '
        'VALUES (%L, %L, %L, %L, %L, %L, %L, %L, %L, %L, %L, %L, %L, now(), %L, %L, now())',
        mid, ver, owner, author,
        coalesce(dataset, lpad('1', 64, '0')), 'rev-0001', 'features/momentum_v4.yaml',
        lpad('2', 64, '0'), lim, 'BTCUSDT spot, shadow only', 'policy/drift_v2.yaml',
        coalesce(rollback, lpad('3', 64, '0')), st, audit_id, 'control-plane-01');
$$;

CREATE FUNCTION _insert_identity(ident text, mid text, ver text, sc text,
                                 lifetime text DEFAULT '1 hour')
RETURNS text LANGUAGE sql AS $$
    SELECT format(
        'INSERT INTO workload_identities (identity, model_id, model_version, scope, '
        'issued_at_utc, expires_at_utc) VALUES (%L, %L, %L, %L, now(), now() + %L::interval)',
        ident, mid, ver, sc, lifetime);
$$;

CREATE FUNCTION _insert_revocation(ident text, mid text, ver text, reason text, evidence text)
RETURNS text LANGUAGE sql AS $$
    SELECT format(
        'INSERT INTO workload_revocations (identity, model_id, model_version, revoked_at_utc, '
        'reason, evidence_ref, revoked_by) VALUES (%L, %L, %L, now(), %L, %L, %L)',
        ident, mid, ver, reason, evidence, 'responder-01');
$$;

CREATE FUNCTION _insert_idem(scope text, key text, fingerprint text, mid text,
                             from_st text, to_st text, audit_id text)
RETURNS text LANGUAGE sql AS $$
    SELECT format(
        'INSERT INTO model_transition_idempotency (idempotency_scope, idempotency_key, '
        'request_fingerprint, model_id, from_state, to_state, audit_id, applied_at_utc) '
        'VALUES (%L, %L, %L, %L, %L, %L, %L, now())',
        scope, key, fingerprint, mid, from_st, to_st, audit_id);
$$;

-- Change a model\'s state, optionally changing other columns at the same time.
CREATE FUNCTION _set_state(mid text, st text, audit_id text DEFAULT 'audit-transition')
RETURNS text LANGUAGE sql AS $$
    SELECT format('UPDATE model_registry SET state = %L, last_audit_id = %L WHERE model_id = %L',
                  st, audit_id, mid);
$$;

BEGIN;

-- === 1. The positive control ==================================================
-- A well-formed record is accepted. Without this, every refusal below would be consistent
-- with the table simply refusing everything, which is not a property anyone wants.
SELECT attempt_ok(_insert_model(_model_id(1), '3.2.1', 'owner-hquinn', 'author-pipeline-07',
                                'Degrades above 3x average volatility.', 'REGISTERED'));
SELECT attempt_ok(_insert_model(_model_id(2), '3.2.1', 'owner-hquinn', 'author-pipeline-08',
                                'Degrades on gaps.', 'MONITORED'));
SELECT attempt_ok(_insert_model(_model_id(3), '3.2.1', 'owner-dlamini', 'author-pipeline-09',
                                'Untested beyond 4x volatility.', 'REGISTERED'));
SELECT record_that('01 a well-formed record is accepted',
       (SELECT count(*) FROM model_registry) = 3);

-- === 2. The eleven required fields ============================================
-- One assertion per field, because a single "required fields" assertion would name only the
-- first field that failed.
SELECT attempt_ok(_insert_model(_model_id(10), '3.2.1', 'owner-hquinn', 'author-pipeline-07',
                                'none', 'REGISTERED'));
SELECT attempt(format('UPDATE model_registry SET limitations = %L WHERE model_id = %L',
                       '', _model_id(10)));
SELECT record_that('02 a model with no recorded limitations is refused',
       (SELECT count(*) FROM model_registry WHERE limitations = '') = 0);

SELECT attempt_ok(_insert_model(_model_id(11), '3.2.1', 'owner-hquinn', 'author-pipeline-07',
                                'none', 'REGISTERED'));
SELECT attempt(format('UPDATE model_registry SET training_dataset_fingerprint = %L WHERE model_id = %L',
                       '', _model_id(11)));
SELECT record_that('03 a model with no training dataset fingerprint is refused',
       (SELECT count(*) FROM model_registry WHERE training_dataset_fingerprint = '') = 0);

SELECT attempt_ok(_insert_model(_model_id(12), '3.2.1', 'owner-hquinn', 'author-pipeline-07',
                                'none', 'REGISTERED'));
SELECT attempt(format('UPDATE model_registry SET rollback_artifact = %L WHERE model_id = %L',
                       '', _model_id(12)));
SELECT record_that('04 a model with no rollback artifact is refused',
       (SELECT count(*) FROM model_registry WHERE rollback_artifact = '') = 0);

SELECT attempt_ok(_insert_model(_model_id(13), '3.2.1', 'owner-hquinn', 'author-pipeline-07',
                                'none', 'REGISTERED'));
SELECT attempt(format('UPDATE model_registry SET deployment_scope = %L WHERE model_id = %L',
                       '', _model_id(13)));
SELECT record_that('05 a model with no deployment scope is refused',
       (SELECT count(*) FROM model_registry WHERE deployment_scope = '') = 0);

SELECT attempt_ok(_insert_model(_model_id(14), '3.2.1', 'owner-hquinn', 'author-pipeline-07',
                                'none', 'REGISTERED'));
SELECT attempt(format('UPDATE model_registry SET monitoring_policy = %L WHERE model_id = %L',
                       '', _model_id(14)));
SELECT record_that('06 a model with no monitoring policy is refused',
       (SELECT count(*) FROM model_registry WHERE monitoring_policy = '') = 0);

-- The digest shape is what makes a fingerprint a pointer to content rather than a string that
-- looks like one. An uppercase or truncated digest would never compare equal to a computed one,
-- which would break the cross-language agreement the research worker depends on.
SELECT attempt(_insert_model(_model_id(15), '3.2.1', 'owner-hquinn', 'author-pipeline-07',
                           'none', 'REGISTERED', 'audit-seed', 'NOTAHASH', lpad('3', 64, '0')));
SELECT record_that('07 a malformed training dataset fingerprint is refused',
       (SELECT count(*) FROM model_registry WHERE training_dataset_fingerprint = 'NOTAHASH') = 0);

SELECT attempt(_insert_model(_model_id(16), '3.2.1', 'owner-hquinn', 'author-pipeline-07',
                           'none', 'REGISTERED', 'audit-seed', lpad('1', 64, '0'), 'SHORT'));
SELECT record_that('08 a malformed rollback artifact digest is refused',
       (SELECT count(*) FROM model_registry WHERE rollback_artifact = 'SHORT') = 0);

-- === 3. Owner and author must differ =========================================
-- The first mechanical form of docs/07\'s bar on self-approval. If they are the same identity
-- there is no pair of people to approve and refuse, whatever the Go package decides later.
SELECT attempt_ok(_insert_model(_model_id(17), '3.2.1', 'owner-same', 'author-pipeline-11',
                                'none', 'REGISTERED'));
SELECT attempt(format('UPDATE model_registry SET owner = %L WHERE model_id = %L',
                       'author-pipeline-11', _model_id(17)));
SELECT record_that('09 a model whose owner equals its author is refused',
       (SELECT count(*) FROM model_registry
        WHERE model_id = _model_id(17) AND owner = author) = 0);

-- === 4. The identifier and the state set are canonical =========================
SELECT attempt(format(
    'INSERT INTO model_registry (model_id, version, owner, author, '
    'training_dataset_fingerprint, code_revision, feature_specification, evaluation_results, '
    'limitations, deployment_scope, monitoring_policy, rollback_artifact, state, '
    'registered_at_utc, last_audit_id, updated_by, updated_at_utc) VALUES '
    '(''not-a-model'', ''3.2.1'', ''owner-a'', ''author-b'', %L, ''rev'', ''feat'', %L, ''lim'', '
    '''scope'', ''pol'', %L, ''REGISTERED'', now(), ''audit-x'', ''cp'', now())',
    lpad('1', 64, '0'), lpad('2', 64, '0'), lpad('3', 64, '0')));
SELECT record_that('10 a model identifier without the mdl_ prefix is refused',
       (SELECT count(*) FROM model_registry WHERE model_id NOT LIKE 'mdl\_%') = 0);

SELECT attempt(format(
    'INSERT INTO model_registry (model_id, version, owner, author, '
    'training_dataset_fingerprint, code_revision, feature_specification, evaluation_results, '
    'limitations, deployment_scope, monitoring_policy, rollback_artifact, state, '
    'registered_at_utc, last_audit_id, updated_by, updated_at_utc) VALUES '
    '(%L, ''3.2.1'', ''owner-a'', ''author-b'', %L, ''rev'', ''feat'', %L, ''lim'', '
    '''scope'', ''pol'', %L, ''DRAFT'', now(), ''audit-x'', ''cp'', now())',
    _model_id(18), lpad('1', 64, '0'), lpad('2', 64, '0'), lpad('3', 64, '0')));
SELECT record_that('11 an out-of-set lifecycle state is refused',
       (SELECT count(*) FROM model_registry
        WHERE state NOT IN ('REGISTERED','EVALUATED','VALIDATED','APPROVED','PAPER',
                            'SHADOW','PROMOTED','MONITORED','RETIRED','QUARANTINED')) = 0);

-- === 5. Lifecycle adjacency ===================================================
-- The forwards path.
SELECT attempt_ok(_set_state(_model_id(1), 'EVALUATED'));
SELECT record_that('12 a declared forward transition is accepted',
       (SELECT state FROM model_registry WHERE model_id = _model_id(1)) = 'EVALUATED');

SELECT attempt(_set_state(_model_id(1), 'APPROVED'));
SELECT record_that('13 a transition skipping a state is refused',
       (SELECT state FROM model_registry WHERE model_id = _model_id(1)) = 'EVALUATED');

-- A state change must cite the audit record that caused it, or the registry holds a state
-- whose origin is not in the audit chain. That is the same defect as an unaudited change.
SELECT attempt_ok(_insert_model(_model_id(19), '3.2.1', 'owner-hquinn', 'author-pipeline-07',
                                'none', 'REGISTERED'));
SELECT attempt(format('UPDATE model_registry SET state = %L, last_audit_id = %L WHERE model_id = %L',
                      'EVALUATED', '', _model_id(19)));
SELECT record_that('14 a state change citing no audit record is refused',
       (SELECT state FROM model_registry WHERE model_id = _model_id(19)) = 'REGISTERED');

-- Re-writing the same state is not a transition and is permitted: a journal recording the audit
-- record for a retry must still be able to store the row.
SELECT attempt_ok(format('UPDATE model_registry SET updated_by = %L WHERE model_id = %L',
                         'control-plane-01', _model_id(19)));
SELECT record_that('15 re-writing the same state is permitted',
       (SELECT updated_by FROM model_registry WHERE model_id = _model_id(19)) = 'control-plane-01');

-- Every non-terminal state must be able to reach quarantine. This is the range-over-the-N check:
-- asserting each state's quarantine edge individually would be a list of examples, and a
-- fourteenth state added later would be covered by none of them.
SELECT attempt_ok(_insert_model(_model_id(20), '3.2.1', 'owner-hquinn', 'author-pipeline-07',
                                'none', 'REGISTERED'));
SELECT attempt_ok(_set_state(_model_id(20), 'EVALUATED'));
SELECT attempt_ok(_set_state(_model_id(20), 'VALIDATED'));
SELECT attempt_ok(_set_state(_model_id(20), 'APPROVED'));
SELECT attempt_ok(_set_state(_model_id(20), 'PAPER'));
SELECT attempt_ok(_set_state(_model_id(20), 'SHADOW'));
SELECT attempt_ok(_set_state(_model_id(20), 'PROMOTED'));
SELECT attempt_ok(_set_state(_model_id(20), 'MONITORED'));
SELECT attempt_ok(_set_state(_model_id(20), 'QUARANTINED'));
SELECT record_that('16 quarantine is reachable from every non-terminal state',
       (SELECT state FROM model_registry WHERE model_id = _model_id(20)) = 'QUARANTINED');

-- === 6. The compromise boundary ===============================================
-- The failure docs/25 section 6 is written against: a compromised model reaching PROMOTED.
SELECT attempt(_set_state(_model_id(20), 'PROMOTED'));
SELECT record_that('17 a quarantined model cannot be promoted',
       (SELECT state FROM model_registry WHERE model_id = _model_id(20)) = 'QUARANTINED');

SELECT attempt(_set_state(_model_id(20), 'MONITORED'));
SELECT record_that('18 a quarantined model cannot resume in MONITORED',
       (SELECT state FROM model_registry WHERE model_id = _model_id(20)) = 'QUARANTINED');

-- A cleared compromise routes through RETIRED and re-enters as a new version. That is the only
-- edge out of quarantine, and the reason is that in-place resumption is indistinguishable from
-- never having been quarantined.
SELECT attempt_ok(_set_state(_model_id(20), 'RETIRED'));
SELECT record_that('19 a quarantined model may only be retired',
       (SELECT state FROM model_registry WHERE model_id = _model_id(20)) = 'RETIRED');

SELECT attempt(_set_state(_model_id(20), 'PROMOTED'));
SELECT record_that('20 a retired model cannot be promoted',
       (SELECT state FROM model_registry WHERE model_id = _model_id(20)) = 'RETIRED');

-- Retired is terminal outright, so a retrospective quarantine is refused too: a model retired
-- years ago cannot have its terminal state rewritten by a later compromise of some other
-- model that shared a lineage.
SELECT attempt_ok(_insert_model(_model_id(21), '3.2.1', 'owner-hquinn', 'author-pipeline-07',
                                'none', 'RETIRED'));
SELECT attempt(_set_state(_model_id(21), 'QUARANTINED'));
SELECT record_that('21 a retired model cannot be quarantined after the fact',
       (SELECT state FROM model_registry WHERE model_id = _model_id(21)) = 'RETIRED');

-- === 7. The model record is immutable in place ================================
-- Two rows with the same primary key describing different models would make the record digest
-- identify something other than what it was computed for.
SELECT attempt_ok(_insert_model(_model_id(22), '3.2.1', 'owner-hquinn', 'author-pipeline-07',
                                'none', 'REGISTERED'));
SELECT attempt(format('UPDATE model_registry SET version = %L WHERE model_id = %L',
                      '9.9.9', _model_id(22)));
SELECT record_that('22 editing a model version in place is refused',
       (SELECT version FROM model_registry WHERE model_id = _model_id(22)) = '3.2.1');

SELECT attempt(format('UPDATE model_registry SET owner = %L WHERE model_id = %L',
                      'owner-someone-else', _model_id(22)));
SELECT record_that('23 reassigning a model owner in place is refused',
       (SELECT owner FROM model_registry WHERE model_id = _model_id(22)) = 'owner-hquinn');

SELECT attempt(format('UPDATE model_registry SET training_dataset_fingerprint = %L WHERE model_id = %L',
                      lpad('9', 64, '0'), _model_id(22)));
SELECT record_that('24 retraining a model in place is refused',
       (SELECT training_dataset_fingerprint FROM model_registry WHERE model_id = _model_id(22))
           = lpad('1', 64, '0'));

SELECT attempt(format('UPDATE model_registry SET limitations = %L WHERE model_id = %L',
                      'now it looks fine', _model_id(22)));
SELECT record_that('25 rewriting a model limitations statement in place is refused',
       (SELECT limitations FROM model_registry WHERE model_id = _model_id(22)) = 'none');

-- A re-registration cannot replace a record, because the primary key is model_id alone.
SELECT attempt(format(
    'INSERT INTO model_registry (model_id, version, owner, author, '
    'training_dataset_fingerprint, code_revision, feature_specification, evaluation_results, '
    'limitations, deployment_scope, monitoring_policy, rollback_artifact, state, '
    'registered_at_utc, last_audit_id, updated_by, updated_at_utc) '
    'SELECT model_id, %L, owner, author, training_dataset_fingerprint, code_revision, '
    'feature_specification, evaluation_results, limitations, deployment_scope, '
    'monitoring_policy, rollback_artifact, %L, now(), %L, %L, now() '
    'FROM model_registry WHERE model_id = %L',
    '4.0.0', 'REGISTERED', 'audit-y', 'cp', _model_id(22)));
SELECT record_that('26 re-registering a model id is refused',
       (SELECT count(*) FROM model_registry WHERE model_id = _model_id(22)
          AND version = '4.0.0') = 0);

-- === 8. Workload identities ===================================================
SELECT attempt_ok(_insert_identity('svc-serve-01', _model_id(1), '3.2.1', 'SERVE_INFERENCE'));
SELECT record_that('27 a well-formed workload identity is accepted',
       (SELECT count(*) FROM workload_identities) = 1);

SELECT attempt(_insert_identity('svc-serve-02', _model_id(1), '3.2.1', 'OMNISCIENT'));
SELECT record_that('28 a scope outside the closed set is refused',
       (SELECT count(*) FROM workload_identities WHERE identity = 'svc-serve-02') = 0);

-- Short-lived is enforced as a bound, not described. A caller cannot mint a long-lived identity
-- by writing a far-future expiry, which is the property that makes revocation meaningful.
SELECT attempt(_insert_identity('svc-long-lived', _model_id(1), '3.2.1', 'SERVE_INFERENCE',
                               '90 days'));
SELECT record_that('29 an identity whose lifetime exceeds the bound is refused',
       (SELECT count(*) FROM workload_identities WHERE identity = 'svc-long-lived') = 0);

SELECT attempt(_insert_identity('svc-expired', _model_id(1), '3.2.1', 'SERVE_INFERENCE',
                               '-1 hour'));
SELECT record_that('30 an identity that expired before it was issued is refused',
       (SELECT count(*) FROM workload_identities WHERE identity = 'svc-expired') = 0);

-- The exact-version binding is what makes a revocation precise, and containment widens by
-- model and version, so the store has to be able to answer that query.
SELECT attempt_ok(_insert_identity('svc-serve-02', _model_id(1), '3.2.1', 'SERVE_INFERENCE'));
SELECT attempt_ok(_insert_identity('svc-serve-03', _model_id(1), '3.2.2', 'SERVE_INFERENCE'));
SELECT attempt_ok(_insert_identity('svc-other-model', _model_id(3), '3.2.1', 'SERVE_INFERENCE'));
SELECT record_that('31 identities serving one exact model version can be enumerated',
       (SELECT count(*) FROM workload_identities
         WHERE model_id = _model_id(1) AND model_version = '3.2.1') = 2);

-- === 9. Revocations are the durable part ======================================
SELECT attempt_ok(_insert_revocation('svc-research-07', _model_id(1), '3.2.1',
                                     'egress to an undeclared address', 'incident-1/evidence'));
SELECT record_that('32 a revocation with a reason and evidence is accepted',
       (SELECT count(*) FROM workload_revocations) = 1);

-- An unattributed revocation is not auditable, and revocation is the action that gets
-- disputed. Separate assertions because they are separate fields a responder could omit.
SELECT attempt(_insert_revocation('svc-no-reason', _model_id(1), '3.2.1', '', 'incident-1/evidence'));
SELECT record_that('33 a revocation with no reason is refused',
       (SELECT count(*) FROM workload_revocations WHERE identity = 'svc-no-reason') = 0);

SELECT attempt(_insert_revocation('svc-no-evidence', _model_id(1), '3.2.1',
                                  'suspected compromise', ''));
SELECT record_that('34 a revocation citing no forensic evidence is refused',
       (SELECT count(*) FROM workload_revocations WHERE identity = 'svc-no-evidence') = 0);

-- These three are what the whole migration is for. A revocation is permanent and a revoked
-- identity name is never re-issued, so a workload that was shut down stays shut down across a
-- restart. EV-040 recorded that a revocation living only in the process that issued it is not
-- revocation; this is the part of that gap a schema can close on its own.
SELECT attempt(format('DELETE FROM workload_revocations WHERE identity = %L', 'svc-research-07'));
SELECT record_that('35 a revocation cannot be deleted',
       (SELECT count(*) FROM workload_revocations WHERE identity = 'svc-research-07') = 1);

SELECT attempt(format('UPDATE workload_revocations SET reason = %L WHERE identity = %L',
                      'corrected', 'svc-research-07'));
SELECT record_that('36 a revocation cannot be edited',
       (SELECT reason FROM workload_revocations WHERE identity = 'svc-research-07')
           = 'egress to an undeclared address');

-- Without this, a workload could be shut down and then mint a fresh identity under the same
-- name, which defeats containment while every record of the shutdown stays intact and true.
SELECT attempt(_insert_identity('svc-research-07', _model_id(1), '3.2.1', 'PRODUCE_ARTIFACTS'));
SELECT record_that('37 a revoked identity name cannot be re-issued',
       (SELECT count(*) FROM workload_identities WHERE identity = 'svc-research-07') = 0);

-- The revocation records which version it covered, so an investigation can ask what was taken
-- down without reconstructing it from worker logs.
SELECT record_that('38 a revocation records the model version it covered',
       (SELECT model_version FROM workload_revocations WHERE identity = 'svc-research-07')
           = '3.2.1');

-- === 10. The idempotency ledger ===============================================
SELECT attempt_ok(_insert_idem('model/lifecycle/evaluation', 'idempotency-key-0001',
                               lpad('4', 64, '0'), _model_id(1), 'REGISTERED', 'EVALUATED',
                               'audit-abc'));
SELECT record_that('39 a recorded transition is accepted',
       (SELECT count(*) FROM model_transition_idempotency) = 1);

-- A key of a few characters is refused because a transition applied without a usable key is a
-- transition that can be retried into a second application.
SELECT attempt(_insert_idem('model/lifecycle/evaluation', 'k1', lpad('5', 64, '0'),
                            _model_id(1), 'REGISTERED', 'EVALUATED', 'audit-def'));
SELECT record_that('40 a transition keyed by too short an idempotency key is refused',
       (SELECT count(*) FROM model_transition_idempotency WHERE idempotency_key = 'k1') = 0);

-- The same scope and key carrying a different request is a conflict, not a retry. The primary
-- key makes that structural rather than a comparison somebody has to remember to run.
SELECT attempt(_insert_idem('model/lifecycle/evaluation', 'idempotency-key-0001',
                            lpad('6', 64, '0'), _model_id(1), 'REGISTERED', 'QUARANTINED',
                            'audit-ghi'));
SELECT record_that('41 a reused idempotency key with a different fingerprint is refused',
       (SELECT request_fingerprint FROM model_transition_idempotency
         WHERE idempotency_scope = 'model/lifecycle/evaluation'
           AND idempotency_key = 'idempotency-key-0001') = lpad('4', 64, '0'));

-- The same key in a different scope is not a conflict. The ledger namespaces by scope precisely
-- so a caller numbering their requests by hand is not serialised against itself.
SELECT attempt_ok(_insert_idem('model/lifecycle/validation', 'idempotency-key-0001',
                               lpad('7', 64, '0'), _model_id(1), 'EVALUATED', 'VALIDATED',
                               'audit-jkl'));
SELECT record_that('42 the same key in another scope is not a conflict',
       (SELECT count(*) FROM model_transition_idempotency
         WHERE idempotency_key = 'idempotency-key-0001') = 2);

SELECT attempt(format('UPDATE model_transition_idempotency SET request_fingerprint = %L '
                      'WHERE idempotency_key = %L', lpad('8', 64, '0'), 'idempotency-key-0001'));
SELECT record_that('43 an applied transition cannot be amended',
       (SELECT count(*) FROM model_transition_idempotency
         WHERE request_fingerprint = lpad('8', 64, '0')) = 0);

SELECT attempt(format('DELETE FROM model_transition_idempotency WHERE idempotency_key = %L',
                      'idempotency-key-0001'));
SELECT record_that('44 an applied transition cannot be deleted',
       (SELECT count(*) FROM model_transition_idempotency) = 2);

-- === 11. The script asserted something ========================================
-- The failure this guards against is the one that produced ALL 0 ASSERTIONS PASSED: an
-- unhandled error aborts the transaction, the assertion table rolls back with it, and a
-- verification that asserted nothing is indistinguishable from one that passed everything.
SELECT record_that('45 the verification asserted a non-zero number of invariants',
       (SELECT count(*) FROM _assertions) >= 44);

COMMIT;

-- === Summary ==================================================================
--
-- The counts are read back from the recorded assertions rather than from RAISE output, so a
-- connection failure part-way through cannot produce a summary that looks complete.
SELECT count(*) FILTER (WHERE held) AS passed,
       count(*) FILTER (WHERE NOT held) AS failed,
       count(*) AS total
  FROM _assertions;

-- The verdict is emitted as a query result, not as a NOTICE or WARNING, because the harness
-- reads psql's stdout and PostgreSQL sends those to stderr.
SELECT CASE WHEN failed = 0 THEN 'ALL ' || total || ' ASSERTIONS PASSED'
            ELSE failed || ' OF ' || total || ' ASSERTIONS FAILED' END
  FROM (SELECT count(*) FILTER (WHERE NOT held) AS failed,
               count(*) AS total
          FROM _assertions) a;

-- List any failure by name, so a broken migration is diagnosable from the output alone.
SELECT name, detail FROM _assertions WHERE NOT held ORDER BY ordinal;
