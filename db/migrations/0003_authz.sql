-- Authorization: policy bundles, role grants, sessions, and exact-diff approvals.
--
-- Authority. This database is the server-held record of *who holds what* (docs/21
-- section 5). It is not the decision engine: the Go package in services/control-plane/authz
-- decides, and it decides from these rows. The split matters because a decision made from
-- a caller-supplied role is not authorization, and the only way to guarantee the subject
-- state comes from the server is for the server to hold it here and for nothing else to be
-- consulted.
--
-- Every guard below is deliberately redundant with the Go package, for the same reason
-- 0002_audit.sql is: a second writer that does not go through the Go package would
-- otherwise be able to write a grant that no evaluator would ever have produced. A
-- constraint that exists only in application code is a convention, and this domain is
-- specifically about not relying on conventions.
--
-- What is NOT enforced here: nothing in this file decides whether an action is permitted.
-- The exclusions below refuse a policy rule that would contradict the docs/21 section 5
-- matrix, and the evaluator refuses at runtime. Neither is a bypass of the other, and
-- neither can produce an allow on its own. docs/21 and ADR-018 are unchanged by this file.

BEGIN;

-- --- Session classes -----------------------------------------------------------
--
-- The timeout profile of each session class from docs/21 section 3. These are the
-- specification's numbers, carried as rows rather than as constants in Go alone, so the
-- values the database enforces against a session are the values the evaluator uses and
-- both can be compared. The Go package reads its own table; a drift test asserts the two
-- agree, because a timeout that differs between them is a session that is valid in one
-- layer and expired in the other.
CREATE TABLE authz_session_policy (
    session_class       text    NOT NULL,
    idle_timeout_sec    integer NOT NULL,
    absolute_timeout_sec integer NOT NULL,
    -- A zero step-up freshness means this class has no step-up policy, which the evaluator
    -- treats as "no privileged action is available at all" rather than as "no requirement".
    -- Modelling it as zero rather than nullable keeps the arithmetic in one type.
    step_up_freshness_sec integer NOT NULL,

    CONSTRAINT authz_session_policy_pkey PRIMARY KEY (session_class),
    CONSTRAINT authz_session_policy_class_closed CHECK (session_class IN
        ('PRIVILEGED_OPERATOR', 'READ_ONLY_OPERATOR', 'SERVICE_WORKLOAD')),
    CONSTRAINT authz_session_policy_timeouts_positive
        CHECK (idle_timeout_sec > 0 AND absolute_timeout_sec > 0 AND step_up_freshness_sec >= 0),
    -- An absolute timeout shorter than the idle timeout is not a stricter policy, it is an
    -- unreachable one: the session could never be idle for as long as it is allowed to live.
    CONSTRAINT authz_session_policy_ordering
        CHECK (absolute_timeout_sec >= idle_timeout_sec)
);

INSERT INTO authz_session_policy
    (session_class, idle_timeout_sec, absolute_timeout_sec, step_up_freshness_sec)
VALUES
    -- The read-only class carries a longer step-up freshness than the privileged class.
    -- That reads backwards until you notice it applies only to confidential export; the
    -- values are carried through as written rather than "corrected".
    ('PRIVILEGED_OPERATOR',        900,  28800,  300),
    ('READ_ONLY_OPERATOR',         1800,  28800,  900),
    ('SERVICE_WORKLOAD',            900,   3600,    0);

-- --- Role exclusions -----------------------------------------------------------
--
-- The "explicitly excluded" column of docs/21 section 5, as data. Each row says a role
-- may never perform an action, regardless of what any policy bundle says.
--
-- This is the single most important table in the file. Every one of these entries is a
-- control that has been written down once and then forgotten: an OWNER does not bypass
-- risk, a RISK_OPERATOR does not submit orders, a RESEARCHER does not self-approve, an
-- AUDITOR does not mutate. Modelling them as rows rather than as prose in a comment is
-- what lets the trigger below refuse a policy rule that contradicts one. In prose, a rule
-- author would have to notice the prose.
CREATE TABLE authz_role_action_exclusion (
    role    text NOT NULL,
    action  text NOT NULL,

    CONSTRAINT authz_role_action_exclusion_pkey PRIMARY KEY (role, action),
    CONSTRAINT authz_role_action_exclusion_role_closed CHECK (role IN
        ('OWNER', 'TRADING_OPERATOR', 'RISK_OPERATOR', 'RESEARCHER',
         'PLATFORM_OPERATOR', 'AUDITOR', 'SERVICE')),
    CONSTRAINT authz_role_action_exclusion_action_closed CHECK (action IN
        ('AUDIT_VIEW', 'AUDIT_EXPORT', 'AUDIT_DELETE', 'POSITION_VIEW',
         'ORDER_SUBMIT', 'ORDER_CANCEL', 'STRATEGY_PAUSE',
         'RISK_LIMIT_CHANGE', 'HALT_TRADING', 'HALT_CLEAR',
         'ROLE_GRANT', 'LIVE_ACTIVATION', 'BREAK_GLASS_RELEASE', 'RISK_APPROVE'))
);

INSERT INTO authz_role_action_exclusion (role, action) VALUES
    ('OWNER',             'AUDIT_DELETE'),
    ('TRADING_OPERATOR',  'RISK_LIMIT_CHANGE'),
    ('TRADING_OPERATOR',  'ROLE_GRANT'),
    ('TRADING_OPERATOR',  'LIVE_ACTIVATION'),
    ('TRADING_OPERATOR',  'AUDIT_DELETE'),
    ('TRADING_OPERATOR',  'HALT_TRADING'),
    ('TRADING_OPERATOR',  'HALT_CLEAR'),
    ('TRADING_OPERATOR',  'BREAK_GLASS_RELEASE'),
    ('RISK_OPERATOR',     'ORDER_SUBMIT'),
    ('RISK_OPERATOR',     'RISK_LIMIT_CHANGE'),
    ('RISK_OPERATOR',     'ROLE_GRANT'),
    ('RISK_OPERATOR',     'LIVE_ACTIVATION'),
    ('RISK_OPERATOR',     'AUDIT_DELETE'),
    ('RISK_OPERATOR',     'BREAK_GLASS_RELEASE'),
    ('RESEARCHER',        'ORDER_SUBMIT'),
    ('RESEARCHER',        'AUDIT_EXPORT'),
    ('RESEARCHER',        'RISK_LIMIT_CHANGE'),
    ('RESEARCHER',        'HALT_TRADING'),
    ('RESEARCHER',        'HALT_CLEAR'),
    ('RESEARCHER',        'ROLE_GRANT'),
    ('RESEARCHER',        'LIVE_ACTIVATION'),
    ('RESEARCHER',        'AUDIT_DELETE'),
    ('RESEARCHER',        'BREAK_GLASS_RELEASE'),
    ('RESEARCHER',        'STRATEGY_PAUSE'),
    ('PLATFORM_OPERATOR', 'ORDER_SUBMIT'),
    ('PLATFORM_OPERATOR', 'RISK_LIMIT_CHANGE'),
    ('PLATFORM_OPERATOR', 'LIVE_ACTIVATION'),
    ('PLATFORM_OPERATOR', 'AUDIT_DELETE'),
    ('PLATFORM_OPERATOR', 'BREAK_GLASS_RELEASE'),
    ('AUDITOR',           'ORDER_SUBMIT'),
    ('AUDITOR',           'ORDER_CANCEL'),
    ('AUDITOR',           'STRATEGY_PAUSE'),
    ('AUDITOR',           'AUDIT_EXPORT'),
    ('AUDITOR',           'RISK_LIMIT_CHANGE'),
    ('AUDITOR',           'HALT_TRADING'),
    ('AUDITOR',           'HALT_CLEAR'),
    ('AUDITOR',           'ROLE_GRANT'),
    ('AUDITOR',           'LIVE_ACTIVATION'),
    ('AUDITOR',           'BREAK_GLASS_RELEASE'),
    ('AUDITOR',           'AUDIT_DELETE'),
    ('SERVICE',           'ROLE_GRANT'),
    ('SERVICE',           'BREAK_GLASS_RELEASE'),
    ('SERVICE',           'AUDIT_DELETE'),
    ('SERVICE',           'AUDIT_EXPORT'),
    ('SERVICE',           'LIVE_ACTIVATION'),
    ('SERVICE',           'RISK_LIMIT_CHANGE');

-- The exclusion table is append-only. An excluded pair that could be deleted is not an
-- exclusion, and a trigger that consults a table an operator can edit is a trigger that
-- can be edited out from under it.
CREATE FUNCTION authz_refuse_exclusion_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'role exclusions are append-only: % is not permitted', TG_OP
        USING ERRCODE = 'restrict_violation';
    RETURN NULL;
END;
$$;

CREATE TRIGGER authz_role_action_exclusion_no_update
    BEFORE UPDATE OR DELETE ON authz_role_action_exclusion
    FOR EACH ROW EXECUTE FUNCTION authz_refuse_exclusion_mutation();

CREATE TRIGGER authz_role_action_exclusion_no_truncate
    BEFORE TRUNCATE ON authz_role_action_exclusion
    FOR EACH STATEMENT EXECUTE FUNCTION authz_refuse_exclusion_mutation();

-- --- Policy bundles ------------------------------------------------------------
--
-- A bundle is identified by its digest, and every decision records the digest of the
-- bundle that made it (docs/21 section 10). A row here is therefore not "the current
-- policy" but a specific signed artefact: several may be live at once during a rollout,
-- and which one refused a given request is answerable after the fact.
CREATE TABLE authz_policy_bundles (
    digest          text        NOT NULL,
    -- Rules is the ordered rule list, in the canonical form the Go package hashes. It is
    -- jsonb rather than a normalised rule table so the bundle is stored exactly as it was
    -- evaluated; a normalised form would need its own canonicalisation and would then be a
    -- second source of truth for what the bundle said.
    rules           jsonb       NOT NULL,
    schema_version  integer     NOT NULL,
    created_at_utc  timestamptz NOT NULL,
    activated_at_utc timestamptz NOT NULL,
    -- Retired bundles are kept. A decision made last month names a digest, and a digest
    -- that no longer resolves makes that decision unanswerable.
    retired_at_utc  timestamptz,

    CONSTRAINT authz_policy_bundles_pkey PRIMARY KEY (digest),
    CONSTRAINT authz_policy_bundles_digest_present CHECK (length(btrim(digest)) > 0),
    CONSTRAINT authz_policy_bundles_rules_array CHECK (jsonb_typeof(rules) = 'array'),
    CONSTRAINT authz_policy_bundles_rules_present CHECK (jsonb_array_length(rules) > 0),
    CONSTRAINT authz_policy_bundles_schema_version CHECK (schema_version = 1),
    CONSTRAINT authz_policy_bundles_activated_present
        CHECK (activated_at_utc IS NOT NULL)
);

CREATE INDEX authz_policy_bundles_activated_idx
    ON authz_policy_bundles (activated_at_utc DESC);

-- A retired bundle must name when it was retired, and a live one must not.
CREATE FUNCTION authz_check_bundle_retirement() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.retired_at_utc IS NOT NULL AND NEW.retired_at_utc < NEW.activated_at_utc THEN
        RAISE EXCEPTION 'a bundle cannot be retired before it was activated: % < %',
            NEW.retired_at_utc, NEW.activated_at_utc
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER authz_policy_bundles_retirement
    AFTER INSERT ON authz_policy_bundles
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION authz_check_bundle_retirement();

-- A policy rule may not contradict the exclusion matrix, and may never name RISK_APPROVE.
--
-- The RISK_APPROVE case is separate from the matrix and unconditional: the risk boundary in
-- ADR-018 says authorization cannot approve financial risk, so no rule, for any role, in
-- any bundle, may grant it. It appears in the action closed set above so a policy naming
-- it is stored as a recognisable refusal rather than an unrecognised value, and is refused
-- here so it can never become an allow.
--
-- A rule with an empty roles list applies to every role, so it is checked against the whole
-- matrix. That is the case a naive implementation gets wrong: a bundle with no role
-- restriction and an ORDER_SUBMIT rule would slip past a check that only looks at
-- explicitly named roles.
CREATE FUNCTION authz_check_rule_against_exclusions() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    rule          jsonb;
    rule_index    integer;
    rule_roles    text[];
    rule_actions  text[];
    action_name   text;
    role_name     text;
    offender_role text;
    offender_action text;
BEGIN
    FOR rule_index IN 0 .. jsonb_array_length(NEW.rules) - 1 LOOP
        rule := NEW.rules -> rule_index;

        -- ADR-018: the risk boundary is absolute.
        FOR action_name IN
            SELECT jsonb_array_elements_text(
                CASE WHEN jsonb_typeof(rule -> 'actions') = 'array'
                     THEN rule -> 'actions' ELSE '[]'::jsonb END)
        LOOP
            IF action_name = 'RISK_APPROVE' THEN
                RAISE EXCEPTION
                    'rule % of bundle % names RISK_APPROVE; authorization cannot approve financial risk (ADR-018)',
                    rule_index, NEW.digest
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
        END LOOP;

        -- Only an ALLOW can contradict an exclusion.
        --
        -- A DENY naming an excluded pair is redundant rather than wrong: it restates a rule
        -- the platform already enforces. Refusing it would make the matrix impossible to use
        -- for defence in depth, and an operator who cannot write a belt-and-braces rule will
        -- eventually not try. The exclusion is about what may be *granted*, so the check
        -- belongs only on the effect that grants.
        IF coalesce(rule ->> 'effect', '') <> 'ALLOW' THEN
            CONTINUE;
        END IF;

        -- An empty roles list means every role, so the whole matrix applies.
        IF jsonb_typeof(rule -> 'roles') = 'array' AND jsonb_array_length(rule -> 'roles') > 0 THEN
            SELECT array_agg(value) INTO rule_roles
              FROM jsonb_array_elements_text(rule -> 'roles');
        ELSE
            SELECT array_agg(DISTINCT role) INTO rule_roles FROM authz_role_action_exclusion;
        END IF;

        IF jsonb_typeof(rule -> 'actions') = 'array' THEN
            SELECT array_agg(value) INTO rule_actions
              FROM jsonb_array_elements_text(rule -> 'actions');
        ELSE
            -- A rule with no action list applies to every action, so it contradicts every
            -- exclusion there is. Refusing it is correct: a rule that permits everything
            -- for a role is exactly what the exclusion matrix exists to prevent.
            SELECT array_agg(DISTINCT action) INTO rule_actions
              FROM authz_role_action_exclusion;
        END IF;

        SELECT e.role, e.action INTO offender_role, offender_action
          FROM authz_role_action_exclusion e
         WHERE e.role = ANY (rule_roles)
           AND e.action = ANY (rule_actions)
         LIMIT 1;

        IF offender_role IS NOT NULL THEN
            RAISE EXCEPTION
                'rule % of bundle % would let role % perform %s, which docs/21 section 5 excludes outright',
                rule_index, NEW.digest, offender_role, offender_action
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
    END LOOP;

    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER authz_policy_bundles_exclusions
    AFTER INSERT ON authz_policy_bundles
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION authz_check_rule_against_exclusions();

-- --- Permission revision -------------------------------------------------------
--
-- The current revision of the whole grant set. A session records the revision it was built
-- against, and the evaluator refuses a session on an older revision. This is what makes
-- revocation take effect: bumping the revision invalidates every session that has not seen
-- the change, without needing to find and kill them.
CREATE TABLE authz_permission_state (
    state_id            integer     NOT NULL,
    current_revision    integer     NOT NULL,
    updated_at_utc      timestamptz NOT NULL,

    CONSTRAINT authz_permission_state_pkey PRIMARY KEY (state_id),
    -- Exactly one row may exist. A second row would make "the current revision" ambiguous,
    -- and ambiguity here is indistinguishable from a revocation that did not apply.
    CONSTRAINT authz_permission_state_singleton CHECK (state_id = 1),
    CONSTRAINT authz_permission_state_revision_nonnegative CHECK (current_revision >= 0)
);

INSERT INTO authz_permission_state (state_id, current_revision, updated_at_utc)
VALUES (1, 1, now());

-- --- Role grants ---------------------------------------------------------------
CREATE TABLE authz_role_grants (
    grant_id        text        NOT NULL,
    subject_id      text        NOT NULL,
    subject_type    text        NOT NULL,
    role            text        NOT NULL,
    -- Scope is the resource boundary, as three arrays. docs/21 section 4 prohibits a
    -- wildcard for live financial operations, so the wildcard is representable here only
    -- so that the check below can refuse it where it matters; a grant with no entries in a
    -- dimension admits nothing in that dimension, which is the safe direction for a field
    -- that fails to load.
    markets         text[]      NOT NULL DEFAULT '{}',
    accounts        text[]      NOT NULL DEFAULT '{}',
    environments    text[]      NOT NULL DEFAULT '{}',
    granted_at_utc  timestamptz NOT NULL,
    expires_at_utc  timestamptz NOT NULL,
    approved_by     text        NOT NULL,
    revoked_at_utc  timestamptz,
    revoked_by      text,

    CONSTRAINT authz_role_grants_pkey PRIMARY KEY (grant_id),
    CONSTRAINT authz_role_grants_subject_present CHECK (length(btrim(subject_id)) > 0),
    CONSTRAINT authz_role_grants_approver_present CHECK (length(btrim(approved_by)) > 0),
    CONSTRAINT authz_role_grants_role_closed CHECK (role IN
        ('OWNER', 'TRADING_OPERATOR', 'RISK_OPERATOR', 'RESEARCHER',
         'PLATFORM_OPERATOR', 'AUDITOR', 'SERVICE')),
    CONSTRAINT authz_role_grants_actor_type_closed CHECK (subject_type IN
        ('HUMAN', 'SERVICE', 'AGENT', 'STRATEGY', 'SYSTEM', 'BREAK_GLASS')),
    -- A grant that has already expired at the moment it is made is not a grant.
    CONSTRAINT authz_role_grants_expiry_after_grant
        CHECK (expires_at_utc > granted_at_utc),
    -- docs/21 section 5 caps a privileged grant at 90 days unless re-approved. The cap is
    -- enforced here so a grant cannot be written with an unbounded lifetime and relied on
    -- the evaluator to notice; the evaluator checks expiry, not duration.
    CONSTRAINT authz_role_grants_max_age
        CHECK (expires_at_utc <= granted_at_utc + interval '90 days'),
    -- A revoked grant must say who revoked it, and an unrevoked one must not claim to.
    CONSTRAINT authz_role_grants_revocation_complete CHECK (
        (revoked_at_utc IS NULL AND revoked_by IS NULL)
        OR (revoked_at_utc IS NOT NULL AND length(btrim(revoked_by)) > 0)
    ),
    -- Every scope dimension must be populated. An empty array would make the grant inert
    -- rather than absent, which reads as a misconfiguration rather than a refusal.
    CONSTRAINT authz_role_grants_scope_present CHECK (
        cardinality(markets) > 0 AND cardinality(accounts) > 0 AND cardinality(environments) > 0
    )
);

CREATE INDEX authz_role_grants_subject_idx
    ON authz_role_grants (subject_id) WHERE revoked_at_utc IS NULL;

-- Revoking a grant must bump the permission revision, or every live session keeps its
-- access until it happens to expire. The revision bump is the mechanism that makes a
-- revocation effective immediately, and leaving it to the application is how a revocation
-- silently fails to apply.
CREATE FUNCTION authz_bump_revision_on_grant_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    UPDATE authz_permission_state
       SET current_revision = current_revision + 1,
           updated_at_utc = now()
     WHERE state_id = 1;
    RETURN NULL;
END;
$$;

CREATE TRIGGER authz_role_grants_revision_bump
    AFTER INSERT OR UPDATE OF revoked_at_utc ON authz_role_grants
    FOR EACH ROW EXECUTE FUNCTION authz_bump_revision_on_grant_change();

-- The wildcard prohibition for live financial operations, enforced at write time.
--
-- docs/21 section 4 prohibits a wildcard grant for a live financial operation. A grant is
-- a permission to act, and the actions it can be used for are determined by policy, so the
-- database cannot know which action a wildcard grant will be spent on. What it can do is
-- refuse the combination that has no legitimate use: a wildcard that includes the live
-- environment. A wildcard scoped to paper and shadow is how a broad grant is expressed
-- without being a live financial one.
CREATE FUNCTION authz_check_wildcard_scope() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF '*' = ANY (NEW.environments) THEN
        RAISE EXCEPTION
            'grant % uses a wildcard environment; docs/21 section 4 prohibits wildcard grants for live financial operations',
            NEW.grant_id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER authz_role_grants_wildcard
    AFTER INSERT ON authz_role_grants
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION authz_check_wildcard_scope();

-- --- Sessions ------------------------------------------------------------------
--
-- Sessions are server-held state. Nothing in this table is read from a token the caller
-- presented, which is what makes the evaluation server-side: a caller cannot extend its own
-- session, restate its own auth strength, or claim a revision it was never granted.
CREATE TABLE authz_sessions (
    session_id           text        NOT NULL,
    subject_id           text        NOT NULL,
    session_class        text        NOT NULL,
    authenticated_at_utc timestamptz NOT NULL,
    last_active_at_utc   timestamptz NOT NULL,
    -- Stored as the canonical name rather than the Go ordinal so the value is meaningful
    -- to anyone reading the table, and so reordering the Go constants cannot silently
    -- change what a stored integer means.
    auth_strength        text        NOT NULL,
    step_up_at_utc       timestamptz,
    permission_revision  integer     NOT NULL,
    revoked_at_utc       timestamptz,
    revoked_reason       text,

    CONSTRAINT authz_sessions_pkey PRIMARY KEY (session_id),
    CONSTRAINT authz_sessions_subject_present CHECK (length(btrim(subject_id)) > 0),
    CONSTRAINT authz_sessions_class_closed CHECK (session_class IN
        ('PRIVILEGED_OPERATOR', 'READ_ONLY_OPERATOR', 'SERVICE_WORKLOAD')),
    -- The canonical strength names. WEBAUTHN and HARDWARE_KEY are the phishing-resistant
    -- factors docs/21 section 2 requires for privileged roles; the constraint does not
    -- forbid a weaker factor on an ordinary session, because read-only work legitimately
    -- uses one, and the evaluator applies the strength requirement per action.
    CONSTRAINT authz_sessions_strength_closed CHECK (auth_strength IN
        ('NONE', 'PASSWORD', 'TOTP', 'WEBAUTHN', 'HARDWARE_KEY')),
    CONSTRAINT authz_sessions_revision_nonnegative CHECK (permission_revision >= 0),
    CONSTRAINT authz_sessions_activity_after_auth
        CHECK (last_active_at_utc >= authenticated_at_utc),
    CONSTRAINT authz_sessions_revocation_complete CHECK (
        (revoked_at_utc IS NULL AND revoked_reason IS NULL)
        OR (revoked_at_utc IS NOT NULL AND length(btrim(revoked_reason)) > 0)
    )
);

CREATE INDEX authz_sessions_subject_idx ON authz_sessions (subject_id);

-- A session may not outlive the absolute timeout of its class, whatever the caller says.
--
-- The class timeout is looked up rather than repeated, so the number the database enforces
-- and the number the evaluator applies come from the same row. A session written with an
-- authenticated_at older than the class allows is refused here, which means a bug that
-- admitted one would fail at the storage layer even if the evaluator were not consulted.
CREATE FUNCTION authz_check_session_age() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    max_age interval;
BEGIN
    SELECT absolute_timeout_sec * interval '1 second' INTO max_age
      FROM authz_session_policy
     WHERE session_class = NEW.session_class;

    -- A session cannot be created already expired relative to its own class profile. The
    -- comparison is against now() because an "age" is only meaningful relative to a moment.
    IF max_age IS NOT NULL AND NEW.authenticated_at_utc < now() - max_age THEN
        RAISE EXCEPTION
            'session % was authenticated at % which is beyond the % absolute timeout of class %',
            NEW.session_id, NEW.authenticated_at_utc, max_age, NEW.session_class
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER authz_sessions_age
    AFTER INSERT ON authz_sessions
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION authz_check_session_age();

-- A revocation must be visible to every session, so it bumps the revision for the same
-- reason a grant change does.
CREATE FUNCTION authz_bump_revision_on_session_revocation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.revoked_at_utc IS NOT NULL AND OLD.revoked_at_utc IS NULL THEN
        UPDATE authz_permission_state
           SET current_revision = current_revision + 1,
               updated_at_utc = now()
         WHERE state_id = 1;
    END IF;
    RETURN NULL;
END;
$$;

CREATE TRIGGER authz_sessions_revocation_revision_bump
    AFTER UPDATE OF revoked_at_utc ON authz_sessions
    FOR EACH ROW EXECUTE FUNCTION authz_bump_revision_on_session_revocation();

-- --- Approvals -----------------------------------------------------------------
--
-- An approval binds a second person to an exact change (docs/21 section 6). The binding is
-- to the diff digest, so editing the change after approval produces a different digest and
-- the approval stops applying. Storing the digest rather than the diff is deliberate: the
-- approver must have been shown the exact bytes, and storing the bytes would create a second
-- copy of a change that the change-tracking system already owns.
CREATE TABLE authz_approvals (
    request_id        text        NOT NULL,
    diff_digest       text        NOT NULL,
    requested_by      text        NOT NULL,
    approved_by       text        NOT NULL,
    approved_at_utc   timestamptz NOT NULL,
    expires_at_utc    timestamptz NOT NULL,
    policy_version    text        NOT NULL,
    applied_at_utc    timestamptz,

    CONSTRAINT authz_approvals_pkey PRIMARY KEY (request_id),
    CONSTRAINT authz_approvals_requester_present CHECK (length(btrim(requested_by)) > 0),
    CONSTRAINT authz_approvals_approver_present CHECK (length(btrim(approved_by)) > 0),
    -- Dual control means two people. A row where the same name appears twice satisfies a
    -- two-approver form and none of its purpose, so it is not representable.
    CONSTRAINT authz_approvals_distinct_people CHECK (requested_by <> approved_by),
    -- The digest is a 64-character SHA-256 hex. Anything else is not a digest of anything,
    -- and an approval bound to a non-digest would never be checked against a real change.
    CONSTRAINT authz_approvals_digest_is_sha256
        CHECK (diff_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT authz_approvals_expiry_after_approval
        CHECK (expires_at_utc > approved_at_utc),
    -- docs/21 section 6 caps an approval at 24 hours. Enforced at write so an approval
    -- cannot be created with a longer life and relied on the evaluator to notice.
    CONSTRAINT authz_approvals_max_ttl
        CHECK (expires_at_utc <= approved_at_utc + interval '24 hours'),
    -- An approval is applied at most once. A second application would be the same approval
    -- authorising two changes, which is the thing an approval bound to a diff prevents.
    CONSTRAINT authz_approvals_applied_once
        CHECK (applied_at_utc IS NULL OR applied_at_utc >= approved_at_utc)
);

-- An approval is consumed, not edited. Changing the digest or either name after the fact
-- would defeat the two properties the row exists to provide, so the only permitted update
-- is recording the single application.
CREATE FUNCTION authz_check_approval_immutability() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.diff_digest IS DISTINCT FROM OLD.diff_digest
       OR NEW.requested_by IS DISTINCT FROM OLD.requested_by
       OR NEW.approved_by IS DISTINCT FROM OLD.approved_by
       OR NEW.approved_at_utc IS DISTINCT FROM OLD.approved_at_utc
       OR NEW.expires_at_utc IS DISTINCT FROM OLD.expires_at_utc THEN
        RAISE EXCEPTION
            'approval % is bound to an exact change and two people; only its application time may be recorded',
            OLD.request_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    -- An approval already applied cannot be applied again.
    IF OLD.applied_at_utc IS NOT NULL AND NEW.applied_at_utc IS DISTINCT FROM OLD.applied_at_utc THEN
        RAISE EXCEPTION 'approval % has already been applied', OLD.request_id
            USING ERRCODE = 'restrict_violation';
    END IF;

    -- NEW, not NULL. This is a BEFORE trigger, so returning NULL tells PostgreSQL to skip
    -- the update silently rather than to refuse it. Returning NULL here made recording an
    -- approval's application a no-op that raised nothing: the update reported success, the
    -- column stayed NULL, and the row remained re-appliable forever. A guard that silently
    -- discards the write it was meant to permit is worse than one that refuses it, because
    -- the caller believes the approval was consumed.
    RETURN NEW;
END;
$$;

CREATE TRIGGER authz_approvals_immutable
    BEFORE UPDATE ON authz_approvals
    FOR EACH ROW EXECUTE FUNCTION authz_check_approval_immutability();

CREATE TRIGGER authz_approvals_no_delete
    BEFORE DELETE ON authz_approvals
    FOR EACH ROW EXECUTE FUNCTION authz_refuse_exclusion_mutation();

-- --- Decision records ----------------------------------------------------------
--
-- Every decision, allow or refuse, is recorded with the bundle digest that produced it
-- (docs/21 section 10). A refusal is recorded as well as an allow: "which policy refused me"
-- is the first question anyone asks, and it is unanswerable unless the refusal was kept.
CREATE TABLE authz_decisions (
    decision_id         text        NOT NULL,
    command_id          text        NOT NULL,
    actor_id            text        NOT NULL,
    actor_type          text        NOT NULL,
    action              text        NOT NULL,
    environment         text        NOT NULL,
    allowed             boolean     NOT NULL,
    refusal_code        text        NOT NULL DEFAULT '',
    reason              text        NOT NULL DEFAULT '',
    policy_bundle_digest text       NOT NULL,
    decided_at_utc      timestamptz NOT NULL,

    CONSTRAINT authz_decisions_pkey PRIMARY KEY (decision_id),
    CONSTRAINT authz_decisions_command_present CHECK (length(btrim(command_id)) > 0),
    CONSTRAINT authz_decisions_actor_present CHECK (length(btrim(actor_id)) > 0),
    CONSTRAINT authz_decisions_policy_digest_present
        CHECK (length(btrim(policy_bundle_digest)) > 0),
    -- A decision states one outcome. An allowed decision cannot carry a refusal code, and a
    -- refused one cannot lack a reason: either shape would make the row ambiguous about
    -- what happened, and a reader would have to guess which field to believe.
    CONSTRAINT authz_decisions_outcome_consistent CHECK (
        (allowed AND refusal_code = '' AND reason = '')
        OR (NOT allowed AND length(btrim(refusal_code)) > 0 AND length(btrim(reason)) > 0)
    ),
    CONSTRAINT authz_decisions_actor_type_closed CHECK (actor_type IN
        ('HUMAN', 'SERVICE', 'AGENT', 'STRATEGY', 'SYSTEM', 'BREAK_GLASS'))
);

CREATE INDEX authz_decisions_command_idx ON authz_decisions (command_id);
CREATE INDEX authz_decisions_actor_idx ON authz_decisions (actor_id, decided_at_utc DESC);

-- Decisions are evidence, so they are not deletable or editable. The audit chain in
-- 0002_audit.sql is the tamper-evident record; this table is the queryable index of which
-- authorization decision applied to which command, and an editable index of an immutable
-- fact is worse than none.
CREATE TRIGGER authz_decisions_no_mutation
    BEFORE UPDATE OR DELETE ON authz_decisions
    FOR EACH ROW EXECUTE FUNCTION authz_refuse_exclusion_mutation();

CREATE TRIGGER authz_decisions_no_truncate
    BEFORE TRUNCATE ON authz_decisions
    FOR EACH STATEMENT EXECUTE FUNCTION authz_refuse_exclusion_mutation();

COMMIT;

-- migrate:down
-- The reverse of the migration above.
--
-- Same ordering rule as the audit down body: tables first, then the functions their triggers
-- referenced, then nothing left behind in the namespace.
--
-- authz_decisions holds the append-only authorization decision record. Reverting it is a
-- deliberate schema rollback performed by an operator with the runner, and it discards the
-- decision history along with it. That is a real cost and the reason this down body is
-- exercised in rehearsal rather than in production: docs/09 lists migration rehearsal as a
-- release gate precisely so that the cost of a rollback is known before it is chosen.
BEGIN;

DROP TABLE IF EXISTS authz_decisions CASCADE;
DROP TABLE IF EXISTS authz_approvals CASCADE;
DROP TABLE IF EXISTS authz_sessions CASCADE;
DROP TABLE IF EXISTS authz_role_grants CASCADE;
DROP TABLE IF EXISTS authz_permission_state CASCADE;
DROP TABLE IF EXISTS authz_policy_bundles CASCADE;
DROP TABLE IF EXISTS authz_role_action_exclusion CASCADE;
DROP TABLE IF EXISTS authz_session_policy CASCADE;

DROP FUNCTION IF EXISTS authz_bump_revision_on_session_revocation() CASCADE;
DROP FUNCTION IF EXISTS authz_check_session_age() CASCADE;
DROP FUNCTION IF EXISTS authz_check_wildcard_scope() CASCADE;
DROP FUNCTION IF EXISTS authz_bump_revision_on_grant_change() CASCADE;
DROP FUNCTION IF EXISTS authz_check_rule_against_exclusions() CASCADE;
DROP FUNCTION IF EXISTS authz_check_bundle_retirement() CASCADE;
DROP FUNCTION IF EXISTS authz_check_approval_immutability() CASCADE;
DROP FUNCTION IF EXISTS authz_refuse_exclusion_mutation() CASCADE;

COMMIT;
