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
--   audit_owner and use SECURITY DEFINER. They only call
--   audit._insert_log, which is itself SECURITY DEFINER owned
--   by audit_writer — so audit writes succeed regardless of
--   the role that initiated the DML. No direct audit table
--   privileges are required by these functions.
--
--   trg_v_license_node_locked is owned by app_owner because
--   it must perform DML on app."licenses" and
--   app."node_locked_license_data" directly. app_owner owns
--   those tables and needs no role switch to write to them.
--   Audit writes still succeed because audit._insert_log is
--   SECURITY DEFINER (owned by audit_writer) — app_owner only
--   needs EXECUTE on that function, not any direct privilege
--   on audit schema tables. That EXECUTE grant is issued in
--   05_functions.sql.
--   SET LOCAL ROLE is intentionally absent from all trigger
--   function bodies — it is not needed and cannot work safely
--   inside a SECURITY DEFINER context.
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
--   license_key value) are never recorded. Presence of the
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
-- trg_v_license_node_locked switches to app_owner below before
-- its CREATE FUNCTION, then returns to audit_owner afterward.
SET LOCAL ROLE audit_owner;

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
SECURITY DEFINER
SET search_path TO audit, app, reference, pg_temp
AS $$
DECLARE
    v_vendor_id UUID;
BEGIN
    v_vendor_id := NULLIF(current_setting('app.vendor_id', true), '')::UUID;

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
    'SECURITY DEFINER — runs as audit_owner.';

CREATE OR REPLACE TRIGGER vendors_audit_tr
    AFTER INSERT OR UPDATE ON app."vendors"
    FOR EACH ROW EXECUTE FUNCTION audit.trg_vendors_audit();


-- ============================================================
-- app.v_license_node_locked INSTEAD OF trigger function
-- ============================================================
-- Handles three responsibilities atomically:
--   1. Routes INSERT/UPDATE/DELETE to the base tables
--      (app."licenses" and app."node_locked_license_data")
--   2. Emits unified audit entries covering both tables
--   3. Enforces correct insert/delete ordering (base first
--      on insert, extension first on delete) to satisfy FKs
--
-- On INSERT:
--   Inserts app."licenses" row first, then
--   app."node_locked_license_data" row.
--   Emits one CREATED audit entry with
--   metadata {"license_type": "node_locked"}.
--
-- On UPDATE:
--   Updates each base table independently.
--   Detects changed fields across BOTH tables from OLD/NEW.
--   Groups changed fields by action code and emits one audit
--   entry per distinct action code (CONFIG_UPDATED, MODIFIED,
--   REVOKED, DELETED). Each entry contains only the previous
--   values of fields relevant to that action code.
--
-- On DELETE:
--   Deletes app."node_locked_license_data" first, then
--   app."licenses".
--   Emits one DELETED audit entry.
--
-- Base table DML runs directly under app_owner, which owns
-- app."licenses" and app."node_locked_license_data" outright —
-- no role switch is needed.
-- audit._insert_log is SECURITY DEFINER owned by audit_writer,
-- so audit writes succeed when called by app_owner provided
-- EXECUTE on audit._insert_log has been granted to app_owner
-- (see 05_functions.sql).
-- ============================================================

-- This function must be owned by app_owner (not audit_owner)
-- because it performs DML directly on app schema base tables.
-- audit._insert_log calls work because that function is
-- SECURITY DEFINER owned by audit_writer.
SET LOCAL ROLE app_owner;

CREATE OR REPLACE FUNCTION audit.trg_v_license_node_locked()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
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
        -- (uuidv7() and NOW()) fire automatically. Duplicating
        -- that logic here would risk drifting out of sync with the
        -- table definition.
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
            "license_key",
            "device_fingerprint_hash"
        ) VALUES (
            v_license_id,
            NEW."license_key",
            NEW."device_fingerprint_hash"
        );

        -- Emit single CREATED entry covering both tables
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

        -- Update base license row
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

        -- Update extension row
        UPDATE app."node_locked_license_data" SET
            "license_key"             = NEW."license_key",
            "device_fingerprint_hash" = NEW."device_fingerprint_hash",
            "max_sessions"            = NEW."max_sessions"
        WHERE "license_id" = v_license_id;

        -- ----------------------------------------------------
        -- DELETED: soft-delete takes priority — emit and stop.
        -- A deletion event is not combined with other diffs.
        -- ----------------------------------------------------
        IF OLD."deleted_at" IS NULL AND NEW."deleted_at" IS NOT NULL THEN
            PERFORM audit._insert_log(
                p_action_code => 'DELETED',
                p_vendor_id   => v_vendor_id,
                p_license_id  => v_license_id
            );
            RETURN NEW;
        END IF;

        -- ----------------------------------------------------
        -- REVOKED: status transition to REVOKED
        -- ----------------------------------------------------
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

        -- ----------------------------------------------------
        -- CONFIG_UPDATED: structural policy field changes
        -- Accumulate all changed config fields into one diff.
        -- ----------------------------------------------------
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

        -- ----------------------------------------------------
        -- MODIFIED: identity/credential/metadata field changes
        -- Accumulate into one diff, one audit row.
        -- ----------------------------------------------------
        IF OLD."metadata" IS DISTINCT FROM NEW."metadata" THEN
            v_modified_diff := v_modified_diff ||
                jsonb_build_object('metadata', OLD."metadata");
        END IF;

        IF OLD."device_fingerprint_hash" IS DISTINCT FROM NEW."device_fingerprint_hash" THEN
            -- Record the previous hash for session hijacking pattern analysis.
            -- The hash is not PII — it is a hash of device identifiers
            -- computed in the application layer.
            v_modified_diff := v_modified_diff ||
                jsonb_build_object('device_fingerprint_hash', OLD."device_fingerprint_hash");
        END IF;

        IF OLD."license_key" IS DISTINCT FROM NEW."license_key" THEN
            -- Key value is never recorded — fact of rotation is sufficient.
            v_modified_diff := v_modified_diff ||
                jsonb_build_object('license_key', 'rotated');
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

    -- --------------------------------------------------------
    -- DELETE
    -- --------------------------------------------------------
    ELSIF TG_OP = 'DELETE' THEN

        v_license_id := OLD."id";

        -- Delete extension row first (FK requires this order)
        DELETE FROM app."node_locked_license_data"
        WHERE "license_id" = v_license_id;

        DELETE FROM app."licenses"
        WHERE "id" = v_license_id;

        PERFORM audit._insert_log(
            p_action_code => 'DELETED',
            p_vendor_id   => v_vendor_id,
            p_license_id  => v_license_id
        );

        RETURN OLD;

    END IF;
END;
$$;

COMMENT ON FUNCTION audit.trg_v_license_node_locked() IS
    'INSTEAD OF trigger on app.v_license_node_locked. '
    'Routes INSERT/UPDATE/DELETE to app."licenses" and '
    'app."node_locked_license_data" base tables. Owned by '
    'app_owner, which has direct access to those tables. '
    'Audit writes succeed via audit._insert_log, which is '
    'SECURITY DEFINER owned by audit_writer. '
    'On UPDATE, one audit row is emitted per distinct action '
    'code (CONFIG_UPDATED, MODIFIED, REVOKED, DELETED). '
    'No SET LOCAL ROLE inside function body — not needed and '
    'not safe inside a SECURITY DEFINER context.';

CREATE OR REPLACE TRIGGER v_license_node_locked_audit_tr
    INSTEAD OF INSERT OR UPDATE OR DELETE
    ON app.v_license_node_locked
    FOR EACH ROW EXECUTE FUNCTION audit.trg_v_license_node_locked();


-- Switch back to audit_owner for the remaining trigger functions,
-- which only call audit._insert_log and belong in the audit schema.
SET LOCAL ROLE audit_owner;

-- ============================================================
-- app."sessions" trigger function
-- ============================================================

CREATE OR REPLACE FUNCTION audit.trg_sessions_audit()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO audit, app, reference, pg_temp
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
    'distinct action code per UPDATE. '
    'SECURITY DEFINER — runs as audit_owner.';

CREATE OR REPLACE TRIGGER sessions_audit_tr
    AFTER INSERT OR UPDATE ON app."sessions"
    FOR EACH ROW EXECUTE FUNCTION audit.trg_sessions_audit();

COMMIT;
