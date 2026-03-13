-- ============================================================
-- Downgrade : Audit Triggers
-- Platform  : LaaS (License as a Service)
-- Database  : PostgreSQL 18
-- Reverses  : 07_audit_triggers.sql
-- Run order : 07 — FIRST in the downgrade sequence
-- ============================================================
--
-- PURPOSE
--   Drops all trigger functions and triggers created by
--   07_audit_triggers.sql.
--
-- ORDER
--   Triggers are dropped before their trigger functions.
--   DROP TRIGGER requires specifying the table it is attached to.
--   DROP FUNCTION drops the trigger function itself.
--   The INSTEAD OF trigger on the view is dropped before the
--   view itself is dropped (in 03_app_down.sql).
--
-- IDEMPOTENCY
--   DROP TRIGGER IF EXISTS   — no error if already absent
--   DROP FUNCTION IF EXISTS  — no error if already absent
-- ============================================================

BEGIN;

-- ============================================================
-- Drop triggers first (before their functions)
-- ============================================================
-- All trigger drops are guarded against missing tables/views
-- to remain idempotent if objects have been dropped elsewhere.

DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'app' AND c.relname = 'vendors'
    ) THEN
        DROP TRIGGER IF EXISTS vendors_audit_tr ON app.vendors;
    END IF;
END $$;

DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'app' AND c.relname = 'sessions'
    ) THEN
        DROP TRIGGER IF EXISTS sessions_audit_tr ON app.sessions;
    END IF;
END $$;

DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'app' AND c.relname = 'v_license_node_locked'
    ) THEN
        DROP TRIGGER IF EXISTS v_license_node_locked_write_tr  ON app.v_license_node_locked;
        DROP TRIGGER IF EXISTS v_license_node_locked_delete_tr ON app.v_license_node_locked;
    END IF;
END $$;

-- ============================================================
-- Drop trigger functions
-- ============================================================

DROP FUNCTION IF EXISTS audit.trg_vendors_audit();
DROP FUNCTION IF EXISTS audit.trg_sessions_audit();
DROP FUNCTION IF EXISTS audit.trg_v_license_node_locked_write();
DROP FUNCTION IF EXISTS audit.trg_v_license_node_locked_delete();

COMMIT;
