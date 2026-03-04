-- ============================================================
-- Down Migration : RLS (Row-Level Security) Policies
-- Platform  : LaaS (License as a Service)
-- Database  : PostgreSQL 18
-- Reverses  : 05_rls.sql
-- ============================================================
--
-- PURPOSE
--   Drops all RLS policies, revokes the EXECUTE grant on
--   app.set_app_context, drops the helper function, and
--   disables RLS on all tenant-scoped tables.
--
-- ORDER MATTERS
--   Policies must be dropped before RLS is disabled so that
--   a subsequent re-enable starts with a clean slate.
--
-- ============================================================

BEGIN;

-- ============================================================
-- app."licenses" — Drop policies, then disable RLS
-- ============================================================

DROP POLICY IF EXISTS "licenses_select_own" ON app."licenses";
DROP POLICY IF EXISTS "licenses_insert_own" ON app."licenses";
DROP POLICY IF EXISTS "licenses_update_own" ON app."licenses";
DROP POLICY IF EXISTS "licenses_delete_own" ON app."licenses";

DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_class
        WHERE relname = 'licenses'
        AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'app')
    ) THEN
        ALTER TABLE app."licenses" DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- ============================================================
-- app."node_locked_license_data" — Drop policies, then disable RLS
-- ============================================================

DROP POLICY IF EXISTS "node_locked_select_own" ON app."node_locked_license_data";
DROP POLICY IF EXISTS "node_locked_insert_own" ON app."node_locked_license_data";
DROP POLICY IF EXISTS "node_locked_update_own" ON app."node_locked_license_data";
DROP POLICY IF EXISTS "node_locked_delete_own" ON app."node_locked_license_data";

DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_class
        WHERE relname = 'node_locked_license_data'
        AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'app')
    ) THEN
        ALTER TABLE app."node_locked_license_data" DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- ============================================================
-- app."sessions" — Drop policies, then disable RLS
-- ============================================================

DROP POLICY IF EXISTS "sessions_select_own" ON app."sessions";
DROP POLICY IF EXISTS "sessions_insert_own" ON app."sessions";
DROP POLICY IF EXISTS "sessions_update_own" ON app."sessions";
DROP POLICY IF EXISTS "sessions_delete_own" ON app."sessions";

DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_class
        WHERE relname = 'sessions'
        AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'app')
    ) THEN
        ALTER TABLE app."sessions" DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- ============================================================
-- app."heartbeats" — Drop policies, then disable RLS
-- ============================================================

DROP POLICY IF EXISTS "heartbeats_select_own" ON app."heartbeats";
DROP POLICY IF EXISTS "heartbeats_insert_own" ON app."heartbeats";
DROP POLICY IF EXISTS "heartbeats_update_own" ON app."heartbeats";
DROP POLICY IF EXISTS "heartbeats_delete_own" ON app."heartbeats";

DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_class
        WHERE relname = 'heartbeats'
        AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'app')
    ) THEN
        ALTER TABLE app."heartbeats" DISABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- ============================================================
-- Revoke execute grant and drop helper function
-- ============================================================

DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'app' AND p.proname = 'set_app_context'
    ) THEN
        REVOKE EXECUTE ON FUNCTION app.set_app_context(UUID)
            FROM PUBLIC, app_reader_rls, app_reader_bypass, app_writer, app_deleter;
    END IF;
END $$;

DROP FUNCTION IF EXISTS app.set_app_context(UUID);

COMMIT;
