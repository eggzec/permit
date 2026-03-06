-- ============================================================
-- Downgrade : Application Functions
-- Platform  : LaaS (License as a Service)
-- Database  : PostgreSQL 18
-- Reverses  : 05_functions.sql
-- Run order : 05 — third in the downgrade sequence
-- Depends on: 07_audit_triggers_down.sql and
--             06_rls_down.sql must have completed first —
--             trigger functions reference audit._insert_log,
--             and RLS policies reference app.set_app_context.
-- ============================================================
--
-- PURPOSE
--   Drops all application utility and audit functions created
--   by 05_functions.sql.
--
-- IDEMPOTENCY
--   DROP FUNCTION IF EXISTS — no error if already absent
-- ============================================================

BEGIN;

-- ============================================================
-- Drop explicit-call audit functions
-- ============================================================
-- Revoke grants first so roles are clean before function drop.
-- REVOKE is idempotent — no error if grant was never made.
-- ============================================================

DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'audit' AND p.proname = 'log_heartbeat_error'
    ) THEN
        REVOKE EXECUTE ON FUNCTION audit.log_heartbeat_error(UUID, UUID, TEXT)
            FROM app_writer, app_deleter;
    END IF;
END $$;

DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'audit' AND p.proname = 'log_token_refreshed'
    ) THEN
        REVOKE EXECUTE ON FUNCTION audit.log_token_refreshed(UUID)
            FROM app_writer, app_deleter;
    END IF;
END $$;

DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'audit' AND p.proname = 'log_login_failed'
    ) THEN
        REVOKE EXECUTE ON FUNCTION audit.log_login_failed(UUID)
            FROM app_writer, app_deleter;
    END IF;
END $$;

DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'audit' AND p.proname = 'log_login_success'
    ) THEN
        REVOKE EXECUTE ON FUNCTION audit.log_login_success(UUID)
            FROM app_writer, app_deleter;
    END IF;
END $$;

DROP FUNCTION IF EXISTS audit.log_heartbeat_error(UUID, UUID, TEXT);
DROP FUNCTION IF EXISTS audit.log_token_refreshed(UUID);
DROP FUNCTION IF EXISTS audit.log_login_failed(UUID);
DROP FUNCTION IF EXISTS audit.log_login_success(UUID);

-- ============================================================
-- Drop internal audit helper
-- ============================================================

DROP FUNCTION IF EXISTS audit._insert_log(TEXT, JSONB, UUID, UUID, UUID);

-- ============================================================
-- Drop app.set_app_context
-- ============================================================

DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'app' AND p.proname = 'set_app_context'
    ) THEN
        REVOKE EXECUTE ON FUNCTION app.set_app_context(UUID, TEXT, TEXT)
            FROM app_reader_rls, app_reader_bypass, app_writer, app_deleter;
    END IF;
END $$;

DROP FUNCTION IF EXISTS app.set_app_context(UUID, TEXT, TEXT);

COMMIT;
