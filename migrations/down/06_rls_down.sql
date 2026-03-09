-- ============================================================
-- Downgrade : RLS (Row-Level Security) Policies
-- Platform  : LaaS (License as a Service)
-- Database  : PostgreSQL 18
-- Reverses  : 06_rls.sql
-- Run order : 06 — second in the downgrade sequence
-- ============================================================
--
-- PURPOSE
--   Drops all RLS policies and disables RLS on all
--   tenant-scoped tables in the app schema and all audit
--   tables in the audit schema.
--
-- ORDER MATTERS
--   Policies must be dropped before RLS is disabled so that
--   a subsequent re-enable starts with a clean slate.
--
-- IDEMPOTENCY
--   DROP POLICY IF EXISTS                — no error if absent
--   ALTER TABLE DISABLE ROW LEVEL SECURITY — idempotent
--
-- ============================================================

BEGIN;

-- ============================================================
-- app."licenses" — Drop policies, then disable RLS
-- ============================================================

DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_class
        WHERE relname = 'licenses'
        AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'app')
    ) THEN
        DROP POLICY IF EXISTS "licenses_select_own" ON app."licenses";
        DROP POLICY IF EXISTS "licenses_insert_own" ON app."licenses";
        DROP POLICY IF EXISTS "licenses_update_own" ON app."licenses";
        DROP POLICY IF EXISTS "licenses_delete_own" ON app."licenses";
        ALTER TABLE app."licenses" DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- ============================================================
-- app."node_locked_license_data" — Drop policies, then disable RLS
-- ============================================================

DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_class
        WHERE relname = 'node_locked_license_data'
        AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'app')
    ) THEN
        DROP POLICY IF EXISTS "node_locked_select_own" ON app."node_locked_license_data";
        DROP POLICY IF EXISTS "node_locked_insert_own" ON app."node_locked_license_data";
        DROP POLICY IF EXISTS "node_locked_update_own" ON app."node_locked_license_data";
        DROP POLICY IF EXISTS "node_locked_delete_own" ON app."node_locked_license_data";
        ALTER TABLE app."node_locked_license_data" DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- ============================================================
-- app."sessions" — Drop policies, then disable RLS
-- ============================================================

DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_class
        WHERE relname = 'sessions'
        AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'app')
    ) THEN
        DROP POLICY IF EXISTS "sessions_select_own" ON app."sessions";
        DROP POLICY IF EXISTS "sessions_insert_own" ON app."sessions";
        DROP POLICY IF EXISTS "sessions_update_own" ON app."sessions";
        DROP POLICY IF EXISTS "sessions_delete_own" ON app."sessions";
        ALTER TABLE app."sessions" DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- ============================================================
-- app."heartbeats" — Drop policies, then disable RLS
-- ============================================================


DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_class
        WHERE relname = 'heartbeats'
        AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'app')
    ) THEN
        DROP POLICY IF EXISTS "heartbeats_select_own" ON app."heartbeats";
        DROP POLICY IF EXISTS "heartbeats_insert_own" ON app."heartbeats";
        DROP POLICY IF EXISTS "heartbeats_update_own" ON app."heartbeats";
        DROP POLICY IF EXISTS "heartbeats_delete_own" ON app."heartbeats";
        ALTER TABLE app."heartbeats" DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- ============================================================
-- audit."audit_logs" — Drop policy, then disable RLS
-- ============================================================


DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_class
        WHERE relname = 'audit_logs'
        AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'audit')
    ) THEN
        DROP POLICY IF EXISTS "audit_logs_select_own" ON audit."audit_logs";
        DROP POLICY IF EXISTS "audit_logs_insert_writer" ON audit."audit_logs";
        ALTER TABLE audit."audit_logs" DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- ============================================================
-- audit."audit_log_vendor_actors" — Drop policy, then disable RLS
-- ============================================================


DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_class
        WHERE relname = 'audit_log_vendor_actors'
        AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'audit')
    ) THEN
        DROP POLICY IF EXISTS "audit_log_vendor_actors_select_own" ON audit."audit_log_vendor_actors";
        DROP POLICY IF EXISTS "audit_log_vendor_actors_insert_writer" ON audit."audit_log_vendor_actors";
        ALTER TABLE audit."audit_log_vendor_actors" DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- ============================================================
-- audit."audit_log_licenses" — Drop policy, then disable RLS
-- ============================================================

DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_class
        WHERE relname = 'audit_log_licenses'
        AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'audit')
    ) THEN
        DROP POLICY IF EXISTS "audit_log_licenses_select_own" ON audit."audit_log_licenses";
        DROP POLICY IF EXISTS "audit_log_licenses_insert_writer" ON audit."audit_log_licenses";
        ALTER TABLE audit."audit_log_licenses" DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- ============================================================
-- audit."audit_log_sessions" — Drop policy, then disable RLS
-- ============================================================

DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_class
        WHERE relname = 'audit_log_sessions'
        AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'audit')
    ) THEN
        DROP POLICY IF EXISTS "audit_log_sessions_select_own" ON audit."audit_log_sessions";
        DROP POLICY IF EXISTS "audit_log_sessions_insert_writer" ON audit."audit_log_sessions";
        ALTER TABLE audit."audit_log_sessions" DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

COMMIT;
