-- ============================================================
-- Migration : Audit Triggers
-- Platform  : LaaS (License as a Service)
-- Database  : PostgreSQL 18
-- Run order : 07 — after 06_rls.sql
-- Depends on: 03_app.sql (app tables and v_license_node_locked),
--             04_audit.sql (audit tables),
--             05_functions.sql (audit._insert_log)
-- ============================================================
--
-- PURPOSE
--   Creates trigger functions and attaches triggers to:
--     • app.v_license_node_locked (INSTEAD OF — handles both
--       DML routing and audit logging for node-locked licenses)
--     • app."vendors"  (AFTER INSERT OR UPDATE)
--     • app."sessions" (AFTER INSERT OR UPDATE)
--
--   app."heartbeats" is intentionally excluded — it is an
--   append-only time-series log and is itself the liveness
--   audit trail. Auditing inserts to it would be redundant.
--
-- TRIGGER OWNERSHIP & SECURITY MODEL
--   trg_vendors_audit and trg_sessions_audit are owned by
--   audit_owner and run with invoker security. They only call
--   audit._insert_log (SECURITY DEFINER owned by audit_writer),
--   so audit writes succeed regardless of the calling role.
--
--   trg_v_license_node_locked is split into two functions:
--     • trg_v_license_node_locked_write — SECURITY DEFINER owned
--       by app_writer. Handles INSTEAD OF INSERT and UPDATE.
--       app_writer has SELECT, INSERT, UPDATE on app tables.
--     • trg_v_license_node_locked_delete — SECURITY DEFINER owned
--       by app_deleter. Handles INSTEAD OF DELETE.
--       app_deleter has SELECT, DELETE on app tables.
--   Both call audit._insert_log via app_writer/app_deleter
--   EXECUTE grants defined in 05_functions.sql.
--   SET LOCAL ROLE is intentionally absent from all trigger
--   function bodies — not needed and not safe inside
--   SECURITY DEFINER context.
--
-- IDEMPOTENCY
--   CREATE OR REPLACE FUNCTION : idempotent
--   CREATE OR REPLACE TRIGGER  : idempotent (PostgreSQL 14+)
--
-- ACTION CODE PRECEDENCE FOR MULTI-FIELD UPDATES
--   When a single UPDATE triggers multiple action codes (e.g.
--   both CONFIG_UPDATED and MODIFIED), one audit_logs row is
--   inserted per distinct action code. Each row contains only
--   the diff fields relevant to its action code. This produces
--   the most semantically precise audit trail — a reader can
--   immediately identify which category of change occurred
--   without parsing a mixed diff.
--
-- DIFF FORMAT (metadata JSONB)
--   Previous values only — not before/after pairs.
--   The current value is always queryable from the live table.
--   Sensitive values (password_hash, session_token_hash,
--   activation_code value) are never recorded. Presence of the
--   action code is sufficient to know the change occurred.
--
-- VENDOR ACTOR RESOLUTION
--   All trigger functions read app.vendor_id from the
--   transaction-local context set by app.set_app_context.
--   If app.vendor_id is empty (system-driven transitions such
--   as ZOMBIE/CLEANUP by a scheduled job), the vendor actor
--   junction row is skipped — accurately representing a system
--   action with no human actor.
--
-- TODO (vendor deletion):
--   Vendor DELETED events currently record no vendor actor
--   junction row because the deletion is admin-driven and no
--   vendor context is set. When self-service vendor deletion
--   is implemented, pass the vendor's own id as the actor by
--   reading app.vendor_id from context in the trigger.
-- ============================================================

BEGIN;

-- audit_owner owns the audit schema and all objects within it.
-- All CREATE FUNCTION statements in the audit schema must run
-- under audit_owner so that default privileges fire correctly.
SET LOCAL ROLE "audit_owner";

-- ============================================================
-- Helper: read vendor_id from context
-- ============================================================
-- Inline in each trigger body rather than a separate function
-- to avoid an extra function call per trigger invocation.
-- Pattern used throughout:
--   v_vendor_id := NULLIF(current_setting('app.vendor_id', true), '')::UUID;
-- ============================================================


-- ============================================================
-- app."vendors" trigger function
-- ============================================================

CREATE OR REPLACE FUNCTION audit.trg_vendors_audit()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        -- SIGNUP: new vendor account created.
        -- The vendor IS the actor for their own signup.
        PERFORM audit._insert_log(
            p_action_code => 'SIGNUP',
            p_vendor_id   => NEW."id"
        );

    ELSIF TG_OP = 'UPDATE' THEN

        -- DELETED: soft-delete (deleted_at flipped from NULL to non-NULL)
        IF OLD."deleted_at" IS NULL AND NEW."deleted_at" IS NOT NULL THEN
            -- TODO (vendor deletion — self-service):
            -- When self-service deletion is implemented, the vendor
            -- deleting their own account should be recorded as the actor.
            -- In that case replace NULL with NEW."id" as p_vendor_id
            -- since app.vendor_id context will be set to the deleting vendor.
            -- For admin-driven deletion, no vendor actor is recorded.
            PERFORM audit._insert_log(
                p_action_code => 'DELETED',
                p_vendor_id   => NULL
            );
        END IF;

        -- PASSWORD_CHANGED: hash changed (value never recorded)
        IF OLD."password_hash" IS DISTINCT FROM NEW."password_hash" THEN
            PERFORM audit._insert_log(
                p_action_code => 'PASSWORD_CHANGED',
                p_vendor_id   => NEW."id"
            );
        END IF;

    END IF;

    RETURN NULL; -- AFTER trigger; return value ignored
END;
$$;

COMMENT ON FUNCTION audit.trg_vendors_audit() IS
    'AFTER INSERT OR UPDATE trigger on app."vendors". '
    'Emits SIGNUP on insert, DELETED on soft-delete, '
    'PASSWORD_CHANGED on password_hash mutation. '
    'Runs with invoker security and delegates audit writes to '
    'audit._insert_log (SECURITY DEFINER owned by audit_writer).';

-- ============================================================
-- TRIGGER OWNER & SECURITY MODEL
-- ============================================================
-- Creating triggers that span the app ↔ audit schema boundary
-- requires a single role that:
--   a) can CREATE TRIGGER on the target (TRIGGER privilege or ownership)
--   b) has EXECUTE/USAGE for the trigger function and its schema
-- audit_owner satisfies (b) already (owns audit schema, USAGE on app).
-- app_owner (the table/view owner) grants TRIGGER privilege to
-- audit_owner below; this one-time grant lets audit_owner own all
-- trigger DDL without superuser or cross-schema role membership.
--
-- SECURITY MODEL FOR INSTEAD OF TRIGGER FUNCTIONS
-- ============================================================
-- The v_license_node_locked INSTEAD OF trigger functions are
-- SECURITY INVOKER (PostgreSQL default), owned by audit_owner.
-- A SECURITY DEFINER design requiring ownership by app_writer/
-- app_deleter is unnecessary here because:
--   * INSTEAD OF triggers on app.v_license_node_locked can ONLY
--     fire when a role with INSERT/UPDATE/DELETE on that view
--     issues the DML. The view's table-level grants restrict this
--     to app_writer (INSERT/UPDATE) and app_deleter (DELETE).
--   * The trigger body's privilege requirements (INSERT/UPDATE
--     on app tables for the write path; DELETE for the delete
--     path) are already held by the invoking role at call time.
--   * SECURITY INVOKER is strictly less privileged: the function
--     cannot be used to escalate privileges beyond what the
--     invoking role already holds.
-- ============================================================

-- Grant TRIGGER privilege on app-owned objects to audit_owner so
-- all trigger DDL is handled by a single role in one block below.
SET LOCAL ROLE "app_owner";
GRANT TRIGGER ON app."vendors"             TO audit_owner;
GRANT TRIGGER ON app."sessions"            TO audit_owner;
GRANT TRIGGER ON app.v_license_node_locked TO audit_owner;

SET LOCAL ROLE "audit_owner";

CREATE OR REPLACE TRIGGER vendors_audit_tr
    AFTER INSERT OR UPDATE ON app."vendors"
    FOR EACH ROW EXECUTE FUNCTION audit.trg_vendors_audit();


-- ============================================================
-- app.v_license_node_locked INSTEAD OF trigger functions
-- ============================================================
-- Both functions are SECURITY INVOKER, owned by audit_owner.
-- See the TRIGGER OWNER & SECURITY MODEL block above for the
-- full justification. The invoking role (app_writer for writes,
-- app_deleter for deletes) holds all required DML privileges on
-- the base tables and EXECUTE on audit._insert_log.
-- ============================================================

-- Drop old combined function/trigger if they exist (renamed in this version).
-- DROP IF EXISTS is a no-op when the objects are absent, so this is safe to run
-- regardless of whether a previous version of the migration was applied.
-- audit_owner owns the audit schema and app_owner owns the view; both are in-role
-- for the current transaction context, so cross-schema drops succeed without superuser.
DROP TRIGGER IF EXISTS v_license_node_locked_audit_tr ON app.v_license_node_locked;
DROP FUNCTION IF EXISTS audit.trg_v_license_node_locked();

-- ------------------------------------------------------------
-- WRITE trigger function (INSERT + UPDATE) — owned by audit_owner
-- ------------------------------------------------------------

CREATE OR REPLACE FUNCTION audit.trg_v_license_node_locked_write()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path TO audit, app, reference, pg_temp
AS $$
DECLARE
    v_vendor_id      UUID;
    v_license_id     UUID;
    v_config_diff    JSONB := '{}'::JSONB;
    v_modified_diff  JSONB := '{}'::JSONB;
BEGIN
    v_vendor_id := NULLIF(current_setting('app.vendor_id', true), '')::UUID;

    -- --------------------------------------------------------
    -- INSERT
    -- --------------------------------------------------------
    IF TG_OP = 'INSERT' THEN

        -- Insert base license row first (FK dependency).
        -- "id", "created_at", and "updated_at" are intentionally
        -- omitted — their DEFAULT expressions on the base table
        -- (uuidv7() and NOW()) fire automatically.
        INSERT INTO app."licenses" (
            "vendor_id",
            "client_id",
            "license_status_code",
            "expires_at",
            "max_grace_secs",
            "metadata",
            "deleted_at"
        ) VALUES (
            NEW."vendor_id",
            NEW."client_id",
            NEW."license_status_code",
            NEW."expires_at",
            NEW."max_grace_secs",
            NEW."metadata",
            NEW."deleted_at"
        )
        RETURNING "id" INTO v_license_id;

        -- Insert extension row.
        -- "max_sessions" is intentionally omitted — its DEFAULT 1
        -- on the base table fires automatically when not supplied.
        INSERT INTO app."node_locked_license_data" (
            "license_id",
            "activation_code",
            "device_fingerprint_hash"
        ) VALUES (
            v_license_id,
            NEW."activation_code",
            NEW."device_fingerprint_hash"
        );

        PERFORM audit._insert_log(
            p_action_code => 'CREATED',
            p_metadata    => '{"license_type": "node_locked"}'::JSONB,
            p_vendor_id   => v_vendor_id,
            p_license_id  => v_license_id
        );

        RETURN NEW;

    -- --------------------------------------------------------
    -- UPDATE
    -- --------------------------------------------------------
    ELSIF TG_OP = 'UPDATE' THEN

        v_license_id := OLD."id";

        UPDATE app."licenses" SET
            "vendor_id"           = NEW."vendor_id",
            "client_id"           = NEW."client_id",
            "license_status_code" = NEW."license_status_code",
            "expires_at"          = NEW."expires_at",
            "max_grace_secs"      = NEW."max_grace_secs",
            "metadata"            = NEW."metadata",
            "updated_at"          = NOW(),
            "deleted_at"          = NEW."deleted_at"
        WHERE "id" = v_license_id;

        UPDATE app."node_locked_license_data" SET
            "activation_code"         = NEW."activation_code",
            "device_fingerprint_hash" = NEW."device_fingerprint_hash",
            "max_sessions"            = NEW."max_sessions"
        WHERE "license_id" = v_license_id;

        -- DELETED: soft-delete takes priority — emit and stop.
        IF OLD."deleted_at" IS NULL AND NEW."deleted_at" IS NOT NULL THEN
            PERFORM audit._insert_log(
                p_action_code => 'DELETED',
                p_vendor_id   => v_vendor_id,
                p_license_id  => v_license_id
            );
            RETURN NEW;
        END IF;

        -- REVOKED: status transition to REVOKED
        IF OLD."license_status_code" IS DISTINCT FROM NEW."license_status_code"
           AND NEW."license_status_code" = 'REVOKED' THEN
            PERFORM audit._insert_log(
                p_action_code => 'REVOKED',
                p_metadata    => jsonb_build_object(
                                     'license_status_code', OLD."license_status_code"
                                 ),
                p_vendor_id   => v_vendor_id,
                p_license_id  => v_license_id
            );
        END IF;

        -- CONFIG_UPDATED: structural policy field changes
        IF OLD."expires_at" IS DISTINCT FROM NEW."expires_at" THEN
            v_config_diff := v_config_diff ||
                jsonb_build_object('expires_at', OLD."expires_at");
        END IF;

        IF OLD."max_grace_secs" IS DISTINCT FROM NEW."max_grace_secs" THEN
            v_config_diff := v_config_diff ||
                jsonb_build_object('max_grace_secs', OLD."max_grace_secs");
        END IF;

        IF OLD."max_sessions" IS DISTINCT FROM NEW."max_sessions" THEN
            v_config_diff := v_config_diff ||
                jsonb_build_object('max_sessions', OLD."max_sessions");
        END IF;

        IF v_config_diff != '{}'::JSONB THEN
            PERFORM audit._insert_log(
                p_action_code => 'CONFIG_UPDATED',
                p_metadata    => v_config_diff,
                p_vendor_id   => v_vendor_id,
                p_license_id  => v_license_id
            );
        END IF;

        -- MODIFIED: identity/credential/metadata field changes
        IF OLD."metadata" IS DISTINCT FROM NEW."metadata" THEN
            v_modified_diff := v_modified_diff ||
                jsonb_build_object('metadata', OLD."metadata");
        END IF;

        IF OLD."device_fingerprint_hash" IS DISTINCT FROM NEW."device_fingerprint_hash" THEN
            v_modified_diff := v_modified_diff ||
                jsonb_build_object('device_fingerprint_hash', OLD."device_fingerprint_hash");
        END IF;

        IF OLD."activation_code" IS DISTINCT FROM NEW."activation_code" THEN
            -- Key value is never recorded — fact of rotation is sufficient.
            v_modified_diff := v_modified_diff ||
                jsonb_build_object('activation_code', 'rotated');
        END IF;

        IF v_modified_diff != '{}'::JSONB THEN
            PERFORM audit._insert_log(
                p_action_code => 'MODIFIED',
                p_metadata    => v_modified_diff,
                p_vendor_id   => v_vendor_id,
                p_license_id  => v_license_id
            );
        END IF;

        RETURN NEW;

    END IF;

    -- Defensive fallback: return NEW for any unexpected TG_OP
    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION audit.trg_v_license_node_locked_write() IS
    'INSTEAD OF INSERT OR UPDATE trigger on app.v_license_node_locked. '
    'SECURITY INVOKER, owned by audit_owner. Fires only when invoked by '
    'app_writer (the only role with INSERT/UPDATE on the view). Routes DML to '
    'app."licenses" and app."node_locked_license_data". '
    'On UPDATE emits one audit row per action code '
    '(DELETED, REVOKED, CONFIG_UPDATED, MODIFIED).';

-- All ACL changes must happen while audit_owner still owns the function.
REVOKE EXECUTE ON FUNCTION audit.trg_v_license_node_locked_write()
    FROM PUBLIC;

-- Revoke default EXECUTE from audit_reader — trigger functions should not
-- be directly executable by read roles; triggers fire via the trigger mechanism.
REVOKE EXECUTE ON FUNCTION audit.trg_v_license_node_locked_write()
    FROM audit_reader;

-- ------------------------------------------------------------
-- DELETE trigger function — owned by audit_owner
-- ------------------------------------------------------------

CREATE OR REPLACE FUNCTION audit.trg_v_license_node_locked_delete()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path TO audit, app, reference, pg_temp
AS $$
DECLARE
    v_vendor_id  UUID;
    v_license_id UUID;
BEGIN
    v_vendor_id  := NULLIF(current_setting('app.vendor_id', true), '')::UUID;
    v_license_id := OLD."id";

    -- Emit audit entry BEFORE deleting rows.
    -- p_license_id is intentionally omitted: inserting into audit_log_licenses
    -- while the license still exists (FK satisfied) would then prevent the
    -- subsequent DELETE on app."licenses" due to the ON DELETE RESTRICT FK.
    -- audit_log_vendor_actors still records who performed the deletion.
    PERFORM audit._insert_log(
        p_action_code => 'DELETED',
        p_vendor_id   => v_vendor_id
    );

    -- Delete extension row first (FK requires this order)
    DELETE FROM app."node_locked_license_data"
    WHERE "license_id" = v_license_id;

    DELETE FROM app."licenses"
    WHERE "id" = v_license_id;

    RETURN OLD;
END;
$$;

COMMENT ON FUNCTION audit.trg_v_license_node_locked_delete() IS
    'INSTEAD OF DELETE trigger on app.v_license_node_locked. '
    'SECURITY INVOKER, owned by audit_owner. Fires only when invoked by '
    'app_deleter (the only role with DELETE on the view). '
    'Emits DELETED audit entry without license_id to avoid FK conflicts; '
    'audit_log_vendor_actors still records the actor. '
    'Then deletes extension row and base license row in FK-safe order.';

-- All ACL changes must happen while audit_owner still owns the function.
REVOKE EXECUTE ON FUNCTION audit.trg_v_license_node_locked_delete()
    FROM PUBLIC;

-- Revoke default EXECUTE from audit_reader — trigger functions should not
-- be directly executable by read roles; triggers fire via the trigger mechanism.
REVOKE EXECUTE ON FUNCTION audit.trg_v_license_node_locked_delete()
    FROM audit_reader;

-- audit_owner has TRIGGER privilege on app.v_license_node_locked (granted above).
-- Creates INSTEAD OF triggers referencing its own functions in the same schema.
CREATE OR REPLACE TRIGGER v_license_node_locked_write_tr
    INSTEAD OF INSERT OR UPDATE
    ON app.v_license_node_locked
    FOR EACH ROW EXECUTE FUNCTION audit.trg_v_license_node_locked_write();

CREATE OR REPLACE TRIGGER v_license_node_locked_delete_tr
    INSTEAD OF DELETE
    ON app.v_license_node_locked
    FOR EACH ROW EXECUTE FUNCTION audit.trg_v_license_node_locked_delete();

-- ============================================================
-- app."sessions" trigger function
-- ============================================================

CREATE OR REPLACE FUNCTION audit.trg_sessions_audit()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_vendor_id     UUID;
    v_modified_diff JSONB := '{}'::JSONB;
BEGIN
    v_vendor_id := NULLIF(current_setting('app.vendor_id', true), '')::UUID;

    IF TG_OP = 'INSERT' THEN
        -- ACTIVATED: new session via license activation
        PERFORM audit._insert_log(
            p_action_code => 'ACTIVATED',
            p_vendor_id   => v_vendor_id,
            p_session_id  => NEW."id"
        );

    ELSIF TG_OP = 'UPDATE' THEN

        -- CLEANED: transition to CLEANUP status (system-driven).
        -- No vendor actor — cleanup job has no vendor context.
        IF OLD."session_status_code" IS DISTINCT FROM NEW."session_status_code"
           AND NEW."session_status_code" = 'CLEANUP' THEN
            PERFORM audit._insert_log(
                p_action_code => 'CLEANED',
                p_vendor_id   => NULL,
                p_session_id  => NEW."id"
            );
            -- CLEANED is emitted independently. Other field changes
            -- in the same UPDATE are still evaluated below.
        END IF;

        -- REVOKED: explicit status transition to REVOKED
        IF OLD."session_status_code" IS DISTINCT FROM NEW."session_status_code"
           AND NEW."session_status_code" = 'REVOKED' THEN
            PERFORM audit._insert_log(
                p_action_code => 'REVOKED',
                p_metadata    => jsonb_build_object(
                                     'session_status_code', OLD."session_status_code"
                                 ),
                p_vendor_id   => v_vendor_id,
                p_session_id  => NEW."id"
            );
        END IF;

        -- MODIFIED: accumulate other meaningful field changes.

        -- Status transitions other than REVOKED and CLEANUP
        IF OLD."session_status_code" IS DISTINCT FROM NEW."session_status_code"
           AND NEW."session_status_code" NOT IN ('REVOKED', 'CLEANUP') THEN
            v_modified_diff := v_modified_diff ||
                jsonb_build_object('session_status_code', OLD."session_status_code");
        END IF;

        -- Device fingerprint change — records previous hash for
        -- session hijacking pattern analysis.
        IF OLD."device_fingerprint_hash" IS DISTINCT FROM NEW."device_fingerprint_hash" THEN
            v_modified_diff := v_modified_diff ||
                jsonb_build_object('device_fingerprint_hash', OLD."device_fingerprint_hash");
        END IF;

        IF v_modified_diff != '{}'::JSONB THEN
            PERFORM audit._insert_log(
                p_action_code => 'MODIFIED',
                p_metadata    => v_modified_diff,
                p_vendor_id   => v_vendor_id,
                p_session_id  => NEW."id"
            );
        END IF;

        -- TOKEN_ROTATED: session token hash changed.
        -- Emitted as a separate entry — security-significant event
        -- distinct from status transitions. Value never recorded.
        IF OLD."session_token_hash" IS DISTINCT FROM NEW."session_token_hash" THEN
            PERFORM audit._insert_log(
                p_action_code => 'TOKEN_ROTATED',
                p_vendor_id   => v_vendor_id,
                p_session_id  => NEW."id"
            );
        END IF;

    END IF;

    RETURN NULL; -- AFTER trigger; return value ignored
END;
$$;

COMMENT ON FUNCTION audit.trg_sessions_audit() IS
    'AFTER INSERT OR UPDATE trigger on app."sessions". '
    'Emits ACTIVATED on insert. On update emits: CLEANED for '
    'CLEANUP transitions (no vendor actor), REVOKED for REVOKED '
    'transitions, MODIFIED for other status/fingerprint changes, '
    'TOKEN_ROTATED for token hash changes. One audit row per '
    'distinct action code per UPDATE. Runs with invoker security '
    'and delegates audit writes to audit._insert_log '
    '(SECURITY DEFINER owned by audit_writer).';

-- app_owner owns app.sessions; audit_owner holds USAGE on the audit schema (01_roles.sql),
-- so it can create triggers on app tables that reference audit schema functions.
-- TRIGGER privilege on app."sessions" was granted above to audit_owner.
CREATE OR REPLACE TRIGGER sessions_audit_tr
    AFTER INSERT OR UPDATE ON app."sessions"
    FOR EACH ROW EXECUTE FUNCTION audit.trg_sessions_audit();

COMMIT;
