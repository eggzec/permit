-- ============================================================
-- Downgrade : Roles & Schema Definitions
-- Platform  : LaaS (License as a Service)
-- Database  : PostgreSQL 18
-- Run order : 01 — LAST in the downgrade sequence
-- Depends on: all other down migrations must complete first
-- ============================================================
--
-- PURPOSE
--   Drops all three application schemas and all group roles
--   created by 01_roles.sql. Restores direct write privileges
--   on license tables that were revoked in 01_roles.sql.
--   Revokes SELECT on app tables granted to audit roles for
--   the RLS policy subquery path.
--
-- IDEMPOTENCY
--   Safe to re-run multiple times.
--   • DROP SCHEMA IF EXISTS — no error if already absent
--   • DROP ROLE  IF EXISTS  — no error if already absent
--
-- TRANSACTION
--   Wrapped in BEGIN / COMMIT — all-or-nothing.
--   NOTE: DROP ROLE cannot succeed while any object in the
--   database is still owned by that role. The schema drops
--   above remove all owned objects first; role drops follow.
--
-- REQUIRED PERMISSIONS
--   • SUPERUSER or CREATEROLE — required to DROP ROLE
--   • Ownership of each schema, or SUPERUSER — required to
--     DROP SCHEMA
--   Recommended: run as a superuser principal.
--
-- DEFAULT PRIVILEGE TEARDOWN
--   PostgreSQL stores ALTER DEFAULT PRIVILEGES entries in
--   pg_default_acl. These entries reference the grantor role
--   (e.g. reference_owner). A role that has entries in
--   pg_default_acl cannot be dropped — PostgreSQL raises:
--     "role X cannot be dropped because some objects depend on it"
--   Schema-scoped default privilege revocations must execute
--   BEFORE the schema is dropped; otherwise the schema reference
--   in IN SCHEMA <s> is invalid.
--   To undo a GRANT of default privileges, issue the matching
--   REVOKE. There is no inverse for the REVOKE EXECUTE ON ALL
--   FUNCTIONS statements in 01_roles.sql — those operated on
--   existing objects at migration time, not on pg_default_acl.
--
-- WARNING
--   This script permanently destroys all application schemas
--   and roles. It cannot be undone without re-running the full
--   up migration sequence. Do not run in production without
--   an explicit approval and a verified backup.
-- ============================================================

BEGIN;

-- ============================================================
-- RESTORE DIRECT LICENSE TABLE WRITE PRIVILEGES
-- ============================================================
-- 01_roles.sql revoked INSERT/UPDATE/DELETE on app."licenses"
-- and app."node_locked_license_data" from app_writer and
-- app_deleter to enforce the view-based write path.
-- Restore them here so the schema is back to a clean state
-- before roles are dropped.
-- ============================================================

DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'app' AND c.relname = 'licenses'
    ) THEN
        GRANT INSERT, UPDATE, DELETE ON app."licenses"
            TO app_writer, app_deleter;
    END IF;
END $$;

DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'app' AND c.relname = 'node_locked_license_data'
    ) THEN
        GRANT INSERT, UPDATE, DELETE ON app."node_locked_license_data"
            TO app_writer, app_deleter;
    END IF;
END $$;

-- ============================================================
-- REVOKE AUDIT ROLE GRANTS ON APP SCHEMA
-- ============================================================
-- 01_roles.sql granted audit_writer and audit_reader SELECT on
-- app."licenses" and app."sessions" so that audit RLS policy
-- subqueries (audit_log_licenses → app.licenses, etc.) can
-- resolve vendor ownership for row-level filtering.
-- Revoke those grants and the accompanying USAGE on the app
-- schema here so the schema is back to a clean state before
-- schemas and roles are dropped.
-- ============================================================

DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'app' AND c.relname = 'licenses'
    ) THEN
        REVOKE SELECT ON app."licenses" FROM audit_writer, audit_reader;
    END IF;
END $$;

DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'app' AND c.relname = 'sessions'
    ) THEN
        REVOKE SELECT ON app."sessions" FROM audit_writer, audit_reader;
    END IF;
END $$;

DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_namespace WHERE nspname = 'app'
    ) THEN
        REVOKE USAGE ON SCHEMA app FROM audit_writer, audit_reader;
    END IF;
END $$;

-- ============================================================
-- REVOKE DEFAULT PRIVILEGES
-- ============================================================
-- Must execute BEFORE schema drops. Mirrors 01_roles.sql in
-- reverse order (app → audit → reference).
--
-- Each block catches undefined_object (raised when the role or
-- schema referenced no longer exists) and raises a NOTICE so
-- that skips are visible in logs. All other errors propagate
-- normally and abort the transaction.
-- ============================================================

-- --- app schema ---

DO $$ BEGIN
    ALTER DEFAULT PRIVILEGES FOR ROLE app_owner IN SCHEMA app
        REVOKE EXECUTE ON FUNCTIONS
        FROM app_reader_rls, app_reader_bypass, app_writer, app_deleter;
EXCEPTION WHEN undefined_object THEN
    RAISE NOTICE 'role app_owner or schema app not found';
END $$;

DO $$ BEGIN
    ALTER DEFAULT PRIVILEGES FOR ROLE app_owner IN SCHEMA app
        REVOKE SELECT ON SEQUENCES
        FROM app_reader_rls, app_reader_bypass;
EXCEPTION WHEN undefined_object THEN
    RAISE NOTICE 'role app_owner or schema app not found';
END $$;

DO $$ BEGIN
    ALTER DEFAULT PRIVILEGES FOR ROLE app_owner IN SCHEMA app
        REVOKE USAGE, SELECT ON SEQUENCES FROM app_writer;
EXCEPTION WHEN undefined_object THEN
    RAISE NOTICE 'role app_owner or schema app not found';
END $$;

DO $$ BEGIN
    ALTER DEFAULT PRIVILEGES FOR ROLE app_owner IN SCHEMA app
        REVOKE SELECT, DELETE ON TABLES FROM app_deleter;
EXCEPTION WHEN undefined_object THEN
    RAISE NOTICE 'role app_owner or schema app not found';
END $$;

DO $$ BEGIN
    ALTER DEFAULT PRIVILEGES FOR ROLE app_owner IN SCHEMA app
        REVOKE SELECT, INSERT, UPDATE ON TABLES FROM app_writer;
EXCEPTION WHEN undefined_object THEN
    RAISE NOTICE 'role app_owner or schema app not found';
END $$;

DO $$ BEGIN
    ALTER DEFAULT PRIVILEGES FOR ROLE app_owner IN SCHEMA app
        REVOKE SELECT ON TABLES FROM app_reader_rls, app_reader_bypass;
EXCEPTION WHEN undefined_object THEN
    RAISE NOTICE 'role app_owner or schema app not found';
END $$;

-- --- audit schema ---

DO $$ BEGIN
    ALTER DEFAULT PRIVILEGES FOR ROLE audit_owner IN SCHEMA audit
        REVOKE EXECUTE ON FUNCTIONS FROM audit_writer, audit_reader;
EXCEPTION WHEN undefined_object THEN
    RAISE NOTICE 'role audit_owner or schema audit not found';
END $$;

DO $$ BEGIN
    ALTER DEFAULT PRIVILEGES FOR ROLE audit_owner IN SCHEMA audit
        REVOKE USAGE, SELECT ON SEQUENCES FROM audit_writer;
EXCEPTION WHEN undefined_object THEN
    RAISE NOTICE 'role audit_owner or schema audit not found';
END $$;

DO $$ BEGIN
    ALTER DEFAULT PRIVILEGES FOR ROLE audit_owner IN SCHEMA audit
        REVOKE SELECT ON TABLES FROM audit_reader;
EXCEPTION WHEN undefined_object THEN
    RAISE NOTICE 'role audit_owner or schema audit not found';
END $$;

DO $$ BEGIN
    ALTER DEFAULT PRIVILEGES FOR ROLE audit_owner IN SCHEMA audit
        REVOKE INSERT ON TABLES FROM audit_writer;
EXCEPTION WHEN undefined_object THEN
    RAISE NOTICE 'role audit_owner or schema audit not found';
END $$;

-- --- reference schema ---

DO $$ BEGIN
    ALTER DEFAULT PRIVILEGES FOR ROLE reference_owner IN SCHEMA reference
        REVOKE EXECUTE ON FUNCTIONS FROM reference_reader, reference_writer;
EXCEPTION WHEN undefined_object THEN
    RAISE NOTICE 'role reference_owner or schema reference not found';
END $$;

DO $$ BEGIN
    ALTER DEFAULT PRIVILEGES FOR ROLE reference_owner IN SCHEMA reference
        REVOKE USAGE, SELECT ON SEQUENCES FROM reference_writer;
EXCEPTION WHEN undefined_object THEN
    RAISE NOTICE 'role reference_owner or schema reference not found';
END $$;

DO $$ BEGIN
    ALTER DEFAULT PRIVILEGES FOR ROLE reference_owner IN SCHEMA reference
        REVOKE SELECT, INSERT ON TABLES FROM reference_writer;
EXCEPTION WHEN undefined_object THEN
    RAISE NOTICE 'role reference_owner or schema reference not found';
END $$;

DO $$ BEGIN
    ALTER DEFAULT PRIVILEGES FOR ROLE reference_owner IN SCHEMA reference
        REVOKE SELECT ON TABLES FROM reference_reader;
EXCEPTION WHEN undefined_object THEN
    RAISE NOTICE 'role reference_owner or schema reference not found';
END $$;

-- --- Global default privileges (undo REVOKE EXECUTE from 01_roles.sql lines 270-274) ---

DO $$ BEGIN
    ALTER DEFAULT PRIVILEGES FOR ROLE reference_owner
        GRANT EXECUTE ON FUNCTIONS TO PUBLIC;
EXCEPTION WHEN undefined_object THEN
    RAISE NOTICE 'role reference_owner not found';
END $$;

DO $$ BEGIN
    ALTER DEFAULT PRIVILEGES FOR ROLE audit_owner
        GRANT EXECUTE ON FUNCTIONS TO PUBLIC;
EXCEPTION WHEN undefined_object THEN
    RAISE NOTICE 'role audit_owner not found';
END $$;

DO $$ BEGIN
    ALTER DEFAULT PRIVILEGES FOR ROLE app_owner
        GRANT EXECUTE ON FUNCTIONS TO PUBLIC;
EXCEPTION WHEN undefined_object THEN
    RAISE NOTICE 'role app_owner not found';
END $$;

-- ============================================================
-- DROP SCHEMAS
-- ============================================================
-- Schemas must be empty before DROP SCHEMA (no CASCADE).
-- All tables and functions must have been removed by the
-- preceding down migrations (07 → 06 → 05 → 04 → 03 → 02)
-- before this file is run. If any objects remain, these
-- statements will fail with a "schema is not empty" error —
-- the intended behaviour.
--
-- NOTE: The built-in `public` schema is intentionally omitted.
-- 01_roles.sql never created it — it only hardened it with
-- REVOKE. Dropping `public` would destroy PostgreSQL built-in
-- infrastructure and any extensions installed there.
-- ============================================================

DROP SCHEMA IF EXISTS audit;
DROP SCHEMA IF EXISTS app;
DROP SCHEMA IF EXISTS reference;

-- ============================================================
-- DROP GROUP ROLES
-- ============================================================
-- Roles are dropped after schemas so that all owned objects
-- have already been removed. A role that still owns objects
-- cannot be dropped.
-- ============================================================

-- --- app schema roles (created last, dropped first) ---
DROP ROLE IF EXISTS app_deleter;
DROP ROLE IF EXISTS app_writer;
DROP ROLE IF EXISTS app_reader_bypass;
DROP ROLE IF EXISTS app_reader_rls;
DROP ROLE IF EXISTS app_owner;

-- --- audit schema roles ---
DROP ROLE IF EXISTS audit_reader;
DROP ROLE IF EXISTS audit_writer;
DROP ROLE IF EXISTS audit_owner;

-- --- reference schema roles (created first, dropped last) ---
DROP ROLE IF EXISTS reference_writer;
DROP ROLE IF EXISTS reference_reader;
DROP ROLE IF EXISTS reference_owner;

-- ============================================================
-- RESTORE DEFAULT PUBLIC SCHEMA PRIVILEGES
-- ============================================================
-- 01_roles.sql hardened the built-in `public` schema by
-- revoking the open defaults PostgreSQL ships with. A down
-- migration must restore the environment to its prior state.
-- GRANT is idempotent — no guard needed.
-- ============================================================

GRANT CREATE ON SCHEMA public TO PUBLIC;
GRANT USAGE  ON SCHEMA public TO PUBLIC;

COMMIT;
