-- ============================================================
-- Migration : RLS (Row-Level Security) Policies
-- Platform  : LaaS (License as a Service)
-- Database  : PostgreSQL 18
-- Run order : 06 — after 05_functions.sql
-- Depends on: 03_app.sql (app schema tables),
--             05_functions.sql (app.set_app_context)
-- ============================================================
--
-- PURPOSE
--   Implements Row-Level Security (RLS) on all tenant-scoped
--   tables in the app schema. Policies enforce vendor isolation:
--   queries are automatically filtered to the vendor_id stored
--   in the app.vendor_id transaction context variable.
--
-- CONTEXT VARIABLE
--   app.vendor_id — transaction-local UUID context variable.
--   Set via SELECT app.set_app_context(p_vendor_id, p_ip_address, p_user_agent).
--   p_ip_address and p_user_agent default to NULL and may be omitted.
--   Defined in 05_functions.sql.
--   Cast to UUID in all policy conditions.
--
-- POLICY COVERAGE & ENFORCEMENT
--   ✓ app.licenses        — has vendor_id column directly
--   ✓ app.node_locked_license_data — via FK → licenses → vendor_id
--   ✓ app.sessions        — via FK → licenses → vendor_id
--   ✓ app.heartbeats      — via FK → sessions → licenses → vendor_id
--
--   SELECT, INSERT, UPDATE, and DELETE policies all enforce
--   vendor ownership based on app.vendor_id context.
--   INSERT uses WITH CHECK conditions; UPDATE uses both USING
--   and WITH CHECK; DELETE uses USING.
--   For audit schema writes, permissive INSERT policies are
--   used only to unblock default-deny under RLS; structural
--   validation of audit payloads happens in audit functions.
--
-- IDEMPOTENCY
--   Safe to re-run multiple times.
--   • ALTER TABLE ... ENABLE ROW LEVEL SECURITY : idempotent
--   • CREATE POLICY : wrapped in DO $$ … EXCEPTION WHEN
--     duplicate_object THEN RAISE NOTICE
--
-- BYPASS CONSIDERATIONS
--   • Superuser alone bypasses RLS by default.
--   • app_owner does not bypass RLS (normal role, not superuser).
--   • app_reader_bypass role has BYPASSRLS attribute.
--   • Other roles (app_reader_rls, app_writer, app_deleter,
--     audit_writer) are subject to RLS and must have
--     app.vendor_id set for successful queries.
--
-- ISOLATION GUARANTEE
--   A vendor can only see/modify records where vendor_id
--   matches NULLIF(current_setting('app.vendor_id', true), '')::UUID.
--   If app.vendor_id is not set the condition evaluates to
--   vendor_id = NULL which returns zero rows (NULL != any UUID).
-- ============================================================

BEGIN;

-- All DDL in this transaction runs as app_owner.
-- SET LOCAL ROLE is transaction-scoped: it reverts automatically at COMMIT,
-- so no RESET ROLE is needed anywhere below.
SET LOCAL ROLE "app_owner";

-- ============================================================
-- Enable RLS on all tenant-scoped tables
-- ============================================================

ALTER TABLE app."licenses"                  ENABLE ROW LEVEL SECURITY;
ALTER TABLE app."node_locked_license_data"  ENABLE ROW LEVEL SECURITY;
ALTER TABLE app."sessions"                  ENABLE ROW LEVEL SECURITY;
ALTER TABLE app."heartbeats"                ENABLE ROW LEVEL SECURITY;

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
            vendor_id = NULLIF(current_setting('app.vendor_id', true), '')::UUID
        );
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'policy "licenses_select_own" already exists, skipping';
END $$;

DO $$ BEGIN
    CREATE POLICY "licenses_insert_own" ON app."licenses"
        FOR INSERT
        WITH CHECK (
            vendor_id = NULLIF(current_setting('app.vendor_id', true), '')::UUID
        );
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'policy "licenses_insert_own" already exists, skipping';
END $$;

DO $$ BEGIN
    CREATE POLICY "licenses_update_own" ON app."licenses"
        FOR UPDATE
        USING (
            vendor_id = NULLIF(current_setting('app.vendor_id', true), '')::UUID
        )
        WITH CHECK (
            vendor_id = NULLIF(current_setting('app.vendor_id', true), '')::UUID
        );
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'policy "licenses_update_own" already exists, skipping';
END $$;

DO $$ BEGIN
    CREATE POLICY "licenses_delete_own" ON app."licenses"
        FOR DELETE
        USING (
            vendor_id = NULLIF(current_setting('app.vendor_id', true), '')::UUID
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
            EXISTS (
                SELECT 1 FROM app."licenses" l
                WHERE l."id" = "license_id"
                  AND l."vendor_id" = NULLIF(current_setting('app.vendor_id', true), '')::UUID
            )
        );
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'policy "node_locked_select_own" already exists, skipping';
END $$;

DO $$ BEGIN
    CREATE POLICY "node_locked_insert_own" ON app."node_locked_license_data"
        FOR INSERT
        WITH CHECK (
            EXISTS (
                SELECT 1 FROM app."licenses" l
                WHERE l."id" = "license_id"
                  AND l."vendor_id" = NULLIF(current_setting('app.vendor_id', true), '')::UUID
            )
        );
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'policy "node_locked_insert_own" already exists, skipping';
END $$;

DO $$ BEGIN
    CREATE POLICY "node_locked_update_own" ON app."node_locked_license_data"
        FOR UPDATE
        USING (
            EXISTS (
                SELECT 1 FROM app."licenses" l
                WHERE l."id" = "license_id"
                  AND l."vendor_id" = NULLIF(current_setting('app.vendor_id', true), '')::UUID
            )
        )
        WITH CHECK (
            EXISTS (
                SELECT 1 FROM app."licenses" l
                WHERE l."id" = "license_id"
                  AND l."vendor_id" = NULLIF(current_setting('app.vendor_id', true), '')::UUID
            )
        );
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'policy "node_locked_update_own" already exists, skipping';
END $$;

DO $$ BEGIN
    CREATE POLICY "node_locked_delete_own" ON app."node_locked_license_data"
        FOR DELETE
        USING (
            EXISTS (
                SELECT 1 FROM app."licenses" l
                WHERE l."id" = "license_id"
                  AND l."vendor_id" = NULLIF(current_setting('app.vendor_id', true), '')::UUID
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
                  AND l.vendor_id = NULLIF(current_setting('app.vendor_id', true), '')::UUID
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
                  AND "vendor_id" = NULLIF(current_setting('app.vendor_id', true), '')::UUID
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
                  AND "vendor_id" = NULLIF(current_setting('app.vendor_id', true), '')::UUID
            )
        )
        WITH CHECK (
            EXISTS (
                SELECT 1 FROM app."licenses"
                WHERE "id" = app."sessions"."license_id"
                  AND "vendor_id" = NULLIF(current_setting('app.vendor_id', true), '')::UUID
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
                  AND "vendor_id" = NULLIF(current_setting('app.vendor_id', true), '')::UUID
            )
        );
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'policy "sessions_delete_own" already exists, skipping';
END $$;

-- ============================================================
-- app."heartbeats" — Policies
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
                  AND l.vendor_id = NULLIF(current_setting('app.vendor_id', true), '')::UUID
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
                  AND l.vendor_id = NULLIF(current_setting('app.vendor_id', true), '')::UUID
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
                  AND l.vendor_id = NULLIF(current_setting('app.vendor_id', true), '')::UUID
            )
        )
        WITH CHECK (
            EXISTS (
                SELECT 1 FROM app."sessions" s
                JOIN app."licenses" l ON l.id = s.license_id
                WHERE s.id = app."heartbeats"."session_id"
                  AND l.vendor_id = NULLIF(current_setting('app.vendor_id', true), '')::UUID
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
                  AND l.vendor_id = NULLIF(current_setting('app.vendor_id', true), '')::UUID
            )
        );
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'policy "heartbeats_delete_own" already exists, skipping';
END $$;

-- ============================================================
-- Switch to audit_owner for all audit schema DDL.
-- ============================================================
SET LOCAL ROLE "audit_owner";

-- ============================================================
-- Enable RLS on all audit tables
-- ============================================================
-- audit_owner bypasses RLS via ownership -- no FORCE ROW LEVEL
-- SECURITY needed. audit_writer and audit_reader are subject
-- to these policies.
-- ============================================================

ALTER TABLE audit."audit_logs"              ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit."audit_log_vendor_actors" ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit."audit_log_licenses"      ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit."audit_log_sessions"      ENABLE ROW LEVEL SECURITY;

-- ============================================================
-- Audit schema INSERT policies
-- ============================================================
-- WITH CHECK (true) scoped to audit_writer only.
-- These are not tenant-isolation policies — they exist solely
-- to allow audit_writer to INSERT when RLS is active (PostgreSQL
-- default-deny blocks all non-owner inserts without a permissive
-- policy). The structural integrity of audit rows is enforced
-- inside audit._insert_log, not here.
-- ============================================================
DO $$ BEGIN
    CREATE POLICY "audit_logs_insert_writer" ON audit."audit_logs"
        FOR INSERT
        TO audit_writer
        WITH CHECK (true);
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'policy "audit_logs_insert_writer" already exists, skipping';
END $$;

DO $$ BEGIN
    CREATE POLICY "audit_log_vendor_actors_insert_writer"
        ON audit."audit_log_vendor_actors"
        FOR INSERT
        TO audit_writer
        WITH CHECK (true);
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'policy "audit_log_vendor_actors_insert_writer" already exists, skipping';
END $$;

DO $$ BEGIN
    CREATE POLICY "audit_log_licenses_insert_writer"
        ON audit."audit_log_licenses"
        FOR INSERT
        TO audit_writer
        WITH CHECK (true);
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'policy "audit_log_licenses_insert_writer" already exists, skipping';
END $$;

DO $$ BEGIN
    CREATE POLICY "audit_log_sessions_insert_writer"
        ON audit."audit_log_sessions"
        FOR INSERT
        TO audit_writer
        WITH CHECK (true);
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'policy "audit_log_sessions_insert_writer" already exists, skipping';
END $$;

-- ============================================================
-- audit."audit_logs" -- Policy
-- ============================================================
-- A log entry is visible only if the authenticated vendor
-- appears as an actor in audit_log_vendor_actors. System-driven
-- events with no actor row are invisible to audit_writer and
-- audit_reader; only audit_owner can see them.
-- ============================================================

DO $$ BEGIN
    CREATE POLICY "audit_logs_select_own" ON audit."audit_logs"
        FOR SELECT
        USING (
            EXISTS (
                SELECT 1 FROM audit."audit_log_vendor_actors"
                WHERE audit_log_id = audit."audit_logs".id
                  AND vendor_id = NULLIF(current_setting('app.vendor_id', true), '')::UUID
            )
        );
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'policy "audit_logs_select_own" already exists, skipping';
END $$;

-- ============================================================
-- audit."audit_log_vendor_actors" -- Policy
-- ============================================================
-- Directly carries vendor_id -- simple equality check.
-- ============================================================

DO $$ BEGIN
    CREATE POLICY "audit_log_vendor_actors_select_own" ON audit."audit_log_vendor_actors"
        FOR SELECT
        USING (
            vendor_id = NULLIF(current_setting('app.vendor_id', true), '')::UUID
        );
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'policy "audit_log_vendor_actors_select_own" already exists, skipping';
END $$;

-- ============================================================
-- audit."audit_log_licenses" -- Policy
-- ============================================================
-- Delegates isolation to app."licenses" RLS. PostgreSQL applies
-- RLS on app."licenses" even inside this subquery, so no
-- explicit vendor_id check is needed here.
-- ============================================================

DO $$ BEGIN
    CREATE POLICY "audit_log_licenses_select_own" ON audit."audit_log_licenses"
        FOR SELECT
        USING (
            EXISTS (
                SELECT 1 FROM app."licenses"
                WHERE app."licenses".id = audit."audit_log_licenses".license_id
            )
        );
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'policy "audit_log_licenses_select_own" already exists, skipping';
END $$;

-- ============================================================
-- audit."audit_log_sessions" -- Policy
-- ============================================================
-- Delegates isolation to app."sessions" RLS. The join chain
-- sessions -> licenses -> vendor_id is enforced automatically
-- by the existing app schema RLS policies.
-- ============================================================

DO $$ BEGIN
    CREATE POLICY "audit_log_sessions_select_own" ON audit."audit_log_sessions"
        FOR SELECT
        USING (
            EXISTS (
                SELECT 1 FROM app."sessions"
                WHERE app."sessions".id = audit."audit_log_sessions".session_id
            )
        );
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'policy "audit_log_sessions_select_own" already exists, skipping';
END $$;

COMMIT;
