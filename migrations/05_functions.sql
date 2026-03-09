-- ============================================================
-- Migration : Application Functions
-- Platform  : LaaS (License as a Service)
-- Database  : PostgreSQL 18
-- Run order : 05 — after 04_audit.sql, before 06_rls.sql
-- Depends on: 01_roles.sql, 02_reference.sql, 03_app.sql,
--             04_audit.sql
-- ============================================================
--
-- PURPOSE
--   Creates all application utility functions and the
--   explicit-call audit functions used by the application
--   layer for events that have no corresponding row mutation
--   (login, token refresh, heartbeat errors).
--
--   Functions are created before 06_rls.sql so that RLS
--   policies can reference them, and so that audit functions
--   are available before triggers in 07_audit_triggers.sql
--   reference them.
--
-- FUNCTION OWNERSHIP & SECURITY MODEL
--   set_app_context        — owned by app_owner (app schema utility)
--   audit.log_*            — owned by audit_owner; no SECURITY DEFINER (invoker)
--   audit._insert_log      — owned by audit_owner (SECURITY DEFINER runs as
--                            audit_owner; body is INSERT-only and search_path is
--                            fixed, so the broader ownership is safe in practice)
--
--   Because audit.log_* are invoker functions, the calling role's
--   EXECUTE privilege on audit._insert_log is what gates audit writes.
--   app_writer and app_deleter are explicitly granted EXECUTE on
--   _insert_log so their calls through the log_* wrappers succeed.
--
--   Privilege chain:
--     app_writer / app_deleter
--       → EXECUTE on audit.log_* (owned by audit_owner, invoker)
--         → log_* calls audit._insert_log (SECURITY DEFINER)
--           → runs with audit_writer's INSERT privileges on audit.*
--
-- CONTEXT VARIABLES
--   All functions read transaction-local config variables set
--   by set_app_context. This avoids passing ip_address and
--   user_agent as parameters to every audit function call.
--
--   app.vendor_id   — UUID of the authenticated vendor
--   app.ip_address  — client IP address (TEXT, cast to INET)
--   app.user_agent  — HTTP User-Agent header value
--
--   current_setting(..., true) returns NULL rather than raising
--   an error when the variable is not set. All functions handle
--   NULL context gracefully.
--
-- EXPLICIT-CALL FUNCTIONS
--   These functions are called directly by application code for
--   events that have no single corresponding row mutation.
--   Each function has a fixed action code baked in — callers
--   cannot choose arbitrary action codes, preventing misuse and
--   ensuring audit records are always meaningful.
--
--   audit.log_login_success(p_vendor_id UUID)
--   audit.log_login_failed(p_vendor_id UUID DEFAULT NULL)
--   audit.log_token_refreshed(p_vendor_id UUID)
--   audit.log_heartbeat_error(
--       p_session_id UUID,
--       p_license_id UUID,
--       p_error_code TEXT   -- must exist in reference.error_codes
--   )
--
--   EXECUTE is granted to app_writer and app_deleter only.
--   Read-only roles (app_reader_rls, app_reader_bypass) have
--   no business calling audit functions directly.
--
-- IDEMPOTENCY
--   CREATE OR REPLACE FUNCTION is idempotent by definition.
--   GRANT EXECUTE is idempotent.
-- ============================================================

BEGIN;

-- ============================================================
-- app.set_app_context
-- ============================================================
-- Sets transaction-local security context variables used by
-- RLS policies, trigger functions, and audit functions.
-- Must be called after authentication before any application
-- query in the same transaction.
--
-- Parameters:
--   p_vendor_id   — authenticated vendor UUID
--   p_ip_address  — client IP address (stored as TEXT for
--                   simplicity; cast to INET at usage sites)
--   p_user_agent  — HTTP User-Agent header value
--
-- All three variables are set as transaction-local (third arg
-- true to set_config) so they reset automatically at COMMIT
-- or ROLLBACK. Safe for connection pool reuse.
-- ============================================================

SET LOCAL ROLE "app_owner";

CREATE OR REPLACE FUNCTION app.set_app_context(
    p_vendor_id  UUID,
    p_ip_address TEXT DEFAULT NULL,
    p_user_agent TEXT DEFAULT NULL
)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM set_config('app.vendor_id',  COALESCE(p_vendor_id::TEXT, ''), true);
    PERFORM set_config('app.ip_address', COALESCE(p_ip_address, ''), true);
    PERFORM set_config('app.user_agent', COALESCE(p_user_agent, ''), true);
END;
$$;

COMMENT ON FUNCTION app.set_app_context(UUID, TEXT, TEXT) IS
    'Sets transaction-local security context: vendor_id (for RLS), '
    'ip_address and user_agent (for audit logging). Must be called '
    'after authentication. All values reset automatically at '
    'COMMIT/ROLLBACK — safe for connection pool reuse.';

GRANT EXECUTE ON FUNCTION app.set_app_context(UUID, TEXT, TEXT)
    TO audit_reader;


-- ============================================================
-- Internal audit helper
-- ============================================================
-- audit._insert_log is a private helper called by all audit
-- functions (both explicit-call and trigger-driven via
-- 07_audit_triggers.sql). It reads ip_address and user_agent
-- from transaction-local config, inserts the core audit_logs
-- row, optionally inserts junction rows.
--
-- Created and owned by audit_owner. SECURITY DEFINER ensures all audit
-- writes execute with audit_owner's schema privileges regardless
-- of the calling role. Body is restricted to INSERT operations;
-- SET search_path prevents search-path injection.
--
-- This function is NOT granted EXECUTE to application roles —
-- it is internal only. Application roles call the typed
-- audit.log_* wrappers which have fixed action codes.
-- ============================================================

-- Switch to audit_owner to create functions in the audit schema.
-- All REVOKE/GRANT on audit._insert_log happen while audit_owner still owns it;
-- ownership is transferred to audit_writer last.
SET LOCAL ROLE "audit_owner";

CREATE OR REPLACE FUNCTION audit._insert_log(
    p_action_code TEXT,
    p_log_id      UUID    DEFAULT uuidv7(),
    p_metadata    JSONB   DEFAULT NULL,
    p_vendor_id   UUID    DEFAULT NULL,
    p_license_id  UUID    DEFAULT NULL,
    p_session_id  UUID    DEFAULT NULL
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO audit, app, reference, pg_temp
AS $$
DECLARE
    v_ip        TEXT;
    v_ua        TEXT;
BEGIN
    -- Read transaction-local context variables.
    -- current_setting(..., true) returns empty string not NULL
    -- when unset, so we normalise empty strings to NULL.
    v_ip := NULLIF(current_setting('app.ip_address', true), '');
    v_ua := NULLIF(current_setting('app.user_agent', true), '');

    -- Safely cast v_ip to INET; if malformed, use NULL
    BEGIN
        v_ip := v_ip::INET;
    EXCEPTION WHEN invalid_text_representation THEN
        v_ip := NULL;
    END;

    INSERT INTO audit."audit_logs" (
        "id",
        "action_code",
        "ip_address",
        "user_agent",
        "metadata"
    ) VALUES (
        p_log_id,
        p_action_code,
        v_ip::INET,
        v_ua,
        p_metadata
    );

    -- Vendor actor junction — skipped if no vendor_id provided.
    -- System-driven events (ZOMBIE, CLEANUP) pass NULL here.
    IF p_vendor_id IS NOT NULL THEN
        INSERT INTO audit."audit_log_vendor_actors" (
            "audit_log_id",
            "vendor_id"
        )
        VALUES (
            p_log_id,
            p_vendor_id
        );
    END IF;

    -- License junction
    IF p_license_id IS NOT NULL THEN
        INSERT INTO audit."audit_log_licenses" (
            "audit_log_id",
            "license_id"
        )
        VALUES (
            p_log_id,
            p_license_id
        );
    END IF;

    -- Session junction
    IF p_session_id IS NOT NULL THEN
        INSERT INTO audit."audit_log_sessions" ("audit_log_id", "session_id")
        VALUES (p_log_id, p_session_id);
    END IF;
END;
$$;

COMMENT ON FUNCTION audit._insert_log(TEXT, UUID, JSONB, UUID, UUID, UUID) IS
    'Internal audit helper. Inserts a core audit_logs row and '
    'optional junction rows. Reads ip_address and user_agent from '
    'transaction-local config set by app.set_app_context. '
    'Owned by audit_owner (SECURITY DEFINER; body restricted to INSERTs, '
    'search_path fixed). app_writer and app_deleter hold EXECUTE to '
    'invoke it through the audit.log_* wrappers.';

REVOKE EXECUTE ON FUNCTION audit._insert_log(TEXT, UUID, JSONB, UUID, UUID, UUID)
    FROM PUBLIC;

GRANT EXECUTE ON FUNCTION audit._insert_log(TEXT, UUID, JSONB, UUID, UUID, UUID)
    TO app_writer, app_deleter;

-- Revoke the default EXECUTE privilege from 01_roles.sql that
-- inadvertently granted readers access to this SECURITY DEFINER function.
-- audit_reader should not be able to execute write functions.
REVOKE EXECUTE ON FUNCTION audit._insert_log(TEXT, UUID, JSONB, UUID, UUID, UUID)
    FROM audit_reader;

-- ============================================================
-- Explicit-call audit functions
-- ============================================================
-- Each function has a fixed action code. Callers supply only
-- the business-specific parameters relevant to that event.
-- All functions delegate to audit._insert_log internally.
--
-- Created and owned by audit_owner. No SECURITY DEFINER — they run
-- as the invoker. The privilege elevation happens inside
-- audit._insert_log (SECURITY DEFINER, owned by audit_owner), not here.
-- ============================================================

-- ------------------------------------------------------------
-- audit.log_login_success
-- ------------------------------------------------------------

CREATE OR REPLACE FUNCTION audit.log_login_success(
    p_vendor_id UUID
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM audit._insert_log(
        p_action_code => 'LOGIN_SUCCESS',
        p_vendor_id   => p_vendor_id
    );
END;
$$;

COMMENT ON FUNCTION audit.log_login_success(UUID) IS
    'Records a successful vendor login. Reads ip_address and '
    'user_agent from transaction-local context.';

-- ------------------------------------------------------------
-- audit.log_login_failed
-- ------------------------------------------------------------
-- p_vendor_id is nullable: pass the vendor UUID when the email
-- was resolvable (wrong password), or NULL when the email did
-- not exist in the system. Both cases are recorded; the
-- vendor_id presence in audit_log_vendor_actors distinguishes
-- them without leaking email existence in API responses.
-- ------------------------------------------------------------

CREATE OR REPLACE FUNCTION audit.log_login_failed(
    p_vendor_id UUID DEFAULT NULL
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM audit._insert_log(
        p_action_code => 'LOGIN_FAILED',
        p_vendor_id   => p_vendor_id
    );
END;
$$;

COMMENT ON FUNCTION audit.log_login_failed(UUID) IS
    'Records a failed vendor login attempt. p_vendor_id is NULL '
    'when the email was not resolvable; non-NULL when the email '
    'existed but credentials were wrong. Never expose which case '
    'occurred in API responses — both return the same error to '
    'the caller.';

-- ------------------------------------------------------------
-- audit.log_token_refreshed
-- ------------------------------------------------------------

CREATE OR REPLACE FUNCTION audit.log_token_refreshed(
    p_vendor_id UUID
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM audit._insert_log(
        p_action_code => 'TOKEN_REFRESHED',
        p_vendor_id   => p_vendor_id
    );
END;
$$;

COMMENT ON FUNCTION audit.log_token_refreshed(UUID) IS
    'Records a successful JWT refresh token exchange.';

-- ------------------------------------------------------------
-- audit.log_heartbeat_error
-- ------------------------------------------------------------
-- p_error_code must exist in reference.error_codes. The value is
-- stored in metadata JSONB with no FK constraint at the DB layer.
-- Application code should validate p_error_code before calling
-- this function to produce a cleaner error message for the caller.
--
-- Both session and license junction rows are recorded:
-- querying "all audit events for license X" returns heartbeat
-- errors without requiring a join through sessions.
-- ------------------------------------------------------------

CREATE OR REPLACE FUNCTION audit.log_heartbeat_error(
    p_session_id UUID,
    p_license_id UUID,
    p_error_code TEXT
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM audit._insert_log(
        p_action_code => 'HEARTBEAT_ERROR',
        p_metadata    => jsonb_build_object('error_code', p_error_code),
        p_session_id  => p_session_id,
        p_license_id  => p_license_id
    );
END;
$$;

COMMENT ON FUNCTION audit.log_heartbeat_error(UUID, UUID, TEXT) IS
    'Records a heartbeat event that produced a non-CONTINUE response. '
    'p_error_code must exist in reference.error_codes. Both session '
    'and license junction rows are populated for efficient querying '
    'by license without joining through sessions.';


-- ============================================================
-- EXECUTE grants on explicit-call functions
-- ============================================================
-- Granted to app_writer and app_deleter only.
-- Read-only roles have no business writing audit records.
-- audit._insert_log is granted separately above (still as
-- superuser, after its ownership transfer to audit_writer).
-- ============================================================

GRANT EXECUTE ON FUNCTION audit.log_login_success(UUID)
    TO app_writer, app_deleter;

GRANT EXECUTE ON FUNCTION audit.log_login_failed(UUID)
    TO app_writer, app_deleter;

GRANT EXECUTE ON FUNCTION audit.log_token_refreshed(UUID)
    TO app_writer, app_deleter;

GRANT EXECUTE ON FUNCTION audit.log_heartbeat_error(UUID, UUID, TEXT)
    TO app_writer, app_deleter;

COMMIT;
