-- ============================================================
-- Migration : RLS (Row-Level Security) Policies
-- Platform  : LaaS (License as a Service)
-- Database  : PostgreSQL 18
-- Run order : 05 — after 01_roles.sql, 02_reference.sql, 03_app.sql, 04_audit.sql
-- Depends on: 03_app.sql (requires app schema tables)
-- ============================================================
--
-- PURPOSE
--   Implements Row-Level Security (RLS) on all tenant-scoped
--   tables in the app schema. Policies enforce vendor isolation:
--   queries are automatically filtered to the vendor_id stored
--   in the app.vendor_id transaction context variable.
--
-- CONTEXT VARIABLE
--   app.vendor_id — transaction-local UUID context variable
--   Set before user queries via SELECT set_app_context(vendor_id).
--   Cast to UUID in all policy conditions.
--
-- POLICY COVERAGE
--   ✓ app.licenses        — has vendor_id column directly
--   ✓ app.node_locked_license_data — via FK → licenses → vendor_id
--   ✓ app.sessions        — via FK → licenses → vendor_id
--   ✓ app.heartbeats      — via FK → sessions → licenses → vendor_id
--
-- IDEMPOTENCY
--   Safe to re-run multiple times.
--   • ALTER TABLE ... ENABLE ROW LEVEL SECURITY : idempotent
--   • CREATE POLICY      : wrapped in DO $$ … EXCEPTION WHEN
--     duplicate_object THEN RAISE NOTICE
--
-- BYPASS CONSIDERATIONS
--   • Superuser and app_owner role bypass RLS by default.
--   • app_reader_bypass role has bypassrls attribute (explicit opt-in).
--   • Other roles (app_reader_rls, app_writer, app_deleter) are
--     subject to RLS and must have app.vendor_id set.
--
-- ISOLATION GUARANTEE
--   A vendor can only see/modify records where vendor_id
--   matches current_setting('app.vendor_id', true)::UUID.
--   If app.vendor_id is not set, the condition evaluates to
--   vendor_id = NULL, which returns zero rows (NULL != any UUID).
--
-- ============================================================

BEGIN;

-- All DDL in this transaction runs as app_owner.
-- SET LOCAL ROLE is transaction-scoped: it reverts automatically at COMMIT,
-- so no RESET ROLE is needed anywhere below.
SET LOCAL ROLE app_owner;

-- ============================================================
-- Helper Function: set_app_context(vendor_id UUID)
-- ============================================================
-- Sets the app.vendor_id session variable. Called by the
-- application after authentication to establish the security
-- context for all subsequent queries in the session.
-- ============================================================

CREATE OR REPLACE FUNCTION app.set_app_context(vendor_id UUID)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM set_config('app.vendor_id', vendor_id::TEXT, true);
END;
$$;

-- ============================================================
-- Enable RLS on all tenant-scoped tables
-- ============================================================

ALTER TABLE app."licenses" ENABLE ROW LEVEL SECURITY;
ALTER TABLE app."node_locked_license_data" ENABLE ROW LEVEL SECURITY;
ALTER TABLE app."sessions" ENABLE ROW LEVEL SECURITY;
ALTER TABLE app."heartbeats" ENABLE ROW LEVEL SECURITY;

-- ============================================================
-- Policies
-- ============================================================

-- ============================================================
-- app."licenses" — Policies
-- ============================================================

DO $$ BEGIN
    CREATE POLICY "licenses_select_own" ON app."licenses"
        FOR SELECT
        USING (
            vendor_id = current_setting('app.vendor_id', true)::UUID
        );
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'policy "licenses_select_own" already exists, skipping';
END $$;

DO $$ BEGIN
    CREATE POLICY "licenses_insert_own" ON app."licenses"
        FOR INSERT
        WITH CHECK (
            vendor_id = current_setting('app.vendor_id', true)::UUID
        );
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'policy "licenses_insert_own" already exists, skipping';
END $$;

DO $$ BEGIN
    CREATE POLICY "licenses_update_own" ON app."licenses"
        FOR UPDATE
        USING (
            vendor_id = current_setting('app.vendor_id', true)::UUID
        )
        WITH CHECK (
            vendor_id = current_setting('app.vendor_id', true)::UUID
        );
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'policy "licenses_update_own" already exists, skipping';
END $$;

DO $$ BEGIN
    CREATE POLICY "licenses_delete_own" ON app."licenses"
        FOR DELETE
        USING (
            vendor_id = current_setting('app.vendor_id', true)::UUID
        );
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'policy "licenses_delete_own" already exists, skipping';
END $$;

-- ============================================================
-- app."node_locked_license_data" — Policies
-- ============================================================

DO $$ BEGIN
    CREATE POLICY "node_locked_select_own" ON app."node_locked_license_data"
        FOR SELECT
        USING (
            "license_id" IN (
                SELECT "id" FROM app."licenses"
                WHERE "vendor_id" = current_setting('app.vendor_id', true)::UUID
            )
        );
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'policy "node_locked_select_own" already exists, skipping';
END $$;

DO $$ BEGIN
    CREATE POLICY "node_locked_insert_own" ON app."node_locked_license_data"
        FOR INSERT
        WITH CHECK (
            "license_id" IN (
                SELECT "id" FROM app."licenses"
                WHERE "vendor_id" = current_setting('app.vendor_id', true)::UUID
            )
        );
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'policy "node_locked_insert_own" already exists, skipping';
END $$;

DO $$ BEGIN
    CREATE POLICY "node_locked_update_own" ON app."node_locked_license_data"
        FOR UPDATE
        USING (
            "license_id" IN (
                SELECT "id" FROM app."licenses"
                WHERE "vendor_id" = current_setting('app.vendor_id', true)::UUID
            )
        )
        WITH CHECK (
            "license_id" IN (
                SELECT "id" FROM app."licenses"
                WHERE "vendor_id" = current_setting('app.vendor_id', true)::UUID
            )
        );
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'policy "node_locked_update_own" already exists, skipping';
END $$;

DO $$ BEGIN
    CREATE POLICY "node_locked_delete_own" ON app."node_locked_license_data"
        FOR DELETE
        USING (
            "license_id" IN (
                SELECT "id" FROM app."licenses"
                WHERE "vendor_id" = current_setting('app.vendor_id', true)::UUID
            )
        );
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'policy "node_locked_delete_own" already exists, skipping';
END $$;

-- ============================================================
-- app."sessions" — Policies
-- ============================================================

DO $$ BEGIN
    CREATE POLICY "sessions_select_own" ON app."sessions"
        FOR SELECT
        USING (
            EXISTS (
                SELECT 1
                FROM app."licenses" l
                WHERE l.id = app."sessions".license_id
                  AND l.vendor_id = current_setting('app.vendor_id', true)::UUID
            )
        );
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'policy "sessions_select_own" already exists, skipping';
END $$;

DO $$ BEGIN
    CREATE POLICY "sessions_insert_own" ON app."sessions"
        FOR INSERT
        WITH CHECK (
            EXISTS (
                SELECT 1 FROM app."licenses"
                WHERE "id" = app."sessions"."license_id"
                  AND "vendor_id" = current_setting('app.vendor_id', true)::UUID
            )
        );
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'policy "sessions_insert_own" already exists, skipping';
END $$;

DO $$ BEGIN
    CREATE POLICY "sessions_update_own" ON app."sessions"
        FOR UPDATE
        USING (
            EXISTS (
                SELECT 1 FROM app."licenses"
                WHERE "id" = app."sessions"."license_id"
                  AND "vendor_id" = current_setting('app.vendor_id', true)::UUID
            )
        )
        WITH CHECK (
            EXISTS (
                SELECT 1 FROM app."licenses"
                WHERE "id" = app."sessions"."license_id"
                  AND "vendor_id" = current_setting('app.vendor_id', true)::UUID
            )
        );
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'policy "sessions_update_own" already exists, skipping';
END $$;

DO $$ BEGIN
    CREATE POLICY "sessions_delete_own" ON app."sessions"
        FOR DELETE
        USING (
            EXISTS (
                SELECT 1 FROM app."licenses"
                WHERE "id" = app."sessions"."license_id"
                  AND "vendor_id" = current_setting('app.vendor_id', true)::UUID
            )
        );
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'policy "sessions_delete_own" already exists, skipping';
END $$;

-- ============================================================
-- app."heartbeats" — Policies
-- ============================================================
-- Partitioned table: RLS is enforced at the parent level and
-- automatically applied to all partitions.
-- ============================================================

DO $$ BEGIN
    CREATE POLICY "heartbeats_select_own" ON app."heartbeats"
        FOR SELECT
        USING (
            EXISTS (
                SELECT 1
                FROM app."sessions" s
                JOIN app."licenses" l ON l.id = s.license_id
                WHERE s.id = app."heartbeats".session_id
                  AND l.vendor_id = current_setting('app.vendor_id', true)::UUID
            )
        );
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'policy "heartbeats_select_own" already exists, skipping';
END $$;

DO $$ BEGIN
    CREATE POLICY "heartbeats_insert_own" ON app."heartbeats"
        FOR INSERT
        WITH CHECK (
            EXISTS (
                SELECT 1 FROM app."sessions" s
                JOIN app."licenses" l ON l.id = s.license_id
                WHERE s.id = app."heartbeats"."session_id"
                  AND l.vendor_id = current_setting('app.vendor_id', true)::UUID
            )
        );
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'policy "heartbeats_insert_own" already exists, skipping';
END $$;

DO $$ BEGIN
    CREATE POLICY "heartbeats_update_own" ON app."heartbeats"
        FOR UPDATE
        USING (
            EXISTS (
                SELECT 1 FROM app."sessions" s
                JOIN app."licenses" l ON l.id = s.license_id
                WHERE s.id = app."heartbeats"."session_id"
                  AND l.vendor_id = current_setting('app.vendor_id', true)::UUID
            )
        )
        WITH CHECK (
            EXISTS (
                SELECT 1 FROM app."sessions" s
                JOIN app."licenses" l ON l.id = s.license_id
                WHERE s.id = app."heartbeats"."session_id"
                  AND l.vendor_id = current_setting('app.vendor_id', true)::UUID
            )
        );
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'policy "heartbeats_update_own" already exists, skipping';
END $$;

DO $$ BEGIN
    CREATE POLICY "heartbeats_delete_own" ON app."heartbeats"
        FOR DELETE
        USING (
            EXISTS (
                SELECT 1 FROM app."sessions" s
                JOIN app."licenses" l ON l.id = s.license_id
                WHERE s.id = app."heartbeats"."session_id"
                  AND l.vendor_id = current_setting('app.vendor_id', true)::UUID
            )
        );
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'policy "heartbeats_delete_own" already exists, skipping';
END $$;

COMMIT;
