-- ============================================================
-- Migration : Roles & Schema Definitions
-- Platform  : LaaS (License as a Service)
-- Database  : PostgreSQL 18
-- Run order : 01 — must execute before all other migrations
-- ============================================================
--
-- PURPOSE
--   Creates all three application schemas and all group roles
--   used across the platform. Schema ownership and default
--   privileges are assigned here so the entire privilege model
--   is coherent before any table is created.
--
-- IDEMPOTENCY
--   Safe to re-run multiple times.
--   • Schemas        : CREATE SCHEMA IF NOT EXISTS
--   • Roles          : DO $$ … EXCEPTION WHEN duplicate_object
--                      THEN RAISE NOTICE (skips silently with log)
--   • ALTER ROLE     : idempotent by definition
--   • GRANT / REVOKE : idempotent — granting a held privilege or
--                      revoking an absent one is a no-op
--   • ALTER DEFAULT PRIVILEGES : idempotent
--
-- TRANSACTION
--   Wrapped in BEGIN / COMMIT — all-or-nothing.
--   CREATE ROLE is transaction-safe in PostgreSQL.
--
-- REQUIRED PERMISSIONS
--   The executing principal must hold ALL of the following:
--   • SUPERUSER   — required for BYPASSRLS attribute and for
--                   ALTER DEFAULT PRIVILEGES across foreign roles
--   • CREATEROLE  — required for CREATE ROLE / ALTER ROLE
--   • CREATE on the target database — required for CREATE SCHEMA
--   Recommended: run as the `postgres` superuser on a fresh
--   instance before any application role is created.
--
-- ROLE DESIGN
--   NOLOGIN   — group roles; cannot be used as login credentials
--               directly. Login users are created separately and
--               granted these group roles.
--   NOINHERIT — privileges are NOT automatically inherited.
--               The session must call SET ROLE (or SET LOCAL ROLE)
--               explicitly to activate a granted group role.
--               This keeps privilege boundaries hard and auditable.
--
-- OBJECT CREATION CONVENTION
--   All objects in the reference / app / audit schemas MUST be
--   created by their respective owner role via SET LOCAL ROLE
--   inside a transaction. The postgres / superuser account must
--   never create objects in application schemas directly.
--   Reason: ALTER DEFAULT PRIVILEGES FOR ROLE <owner> only fires
--   for objects created BY that owner role. Objects created by
--   postgres would inherit no default privileges.
--
-- LICENSE WRITE PATH
--   Direct INSERT/UPDATE/DELETE on app."licenses" and
--   app."node_locked_license_data" is intentionally restricted
--   to app_owner only. All application writes to these tables
--   must go through the subtype views (e.g. app.v_license_node_locked)
--   which have INSTEAD OF triggers that handle both DML routing
--   and audit logging atomically. This ensures a unified diff
--   across the base license table and its extension table is
--   always captured correctly.
--
--   app_writer and app_deleter receive their license write
--   privileges via GRANT on the view in 03_app.sql, not via
--   table-level grants here.
--
-- LOGIN USER ACTIVATION
--   ⚠️  A login user with NOINHERIT has NO table-level privileges
--   until it activates a group role. Two patterns:
--
--   1) Per-transaction (recommended for connection pools):
--        SET LOCAL ROLE app_reader_rls;
--        -- resets automatically at COMMIT / ROLLBACK
--        -- safe on reused pool connections
--
--   2) Per-session (interactive / single-role users):
--        SET ROLE app_reader_rls;
--        RESET ROLE;   -- returns to the login role
--
--   3) Automatic at session start (single-role login users):
--        ALTER ROLE <login_user> SET role TO '<group_role>';
-- ============================================================

BEGIN;

-- ============================================================
-- SCHEMAS
-- ============================================================
-- Created before the owner roles so the schema objects exist
-- for ownership transfer immediately after each role is defined.
-- SET LOCAL ROLE is not used here because the owner roles do
-- not yet exist at this point in the migration.
-- ============================================================

CREATE SCHEMA IF NOT EXISTS "reference";
CREATE SCHEMA IF NOT EXISTS "app";
CREATE SCHEMA IF NOT EXISTS "audit";

COMMENT ON SCHEMA "reference" IS
    'Static lookup / reference tables for enumerations and constants. '
    'Rows are inserted once at deploy time and treated as immutable. '
    'Isolated into its own schema to enable independent RBAC '
    '(SELECT-only grants to app roles, no write access).';

COMMENT ON SCHEMA "app" IS
    'Core business tables for the LaaS licensing platform. '
    'Contains all mutable business entities: vendors, licenses, '
    'sessions, and heartbeats. Named "app" to distinguish it from '
    'the PostgreSQL built-in "public" schema.';

COMMENT ON SCHEMA "audit" IS
    'Immutable append-only audit trail. Separated from the app schema '
    'to enforce independent access control: audit readers have no '
    'business-table access, and business writers cannot delete audit '
    'records. All tables are INSERT-only; UPDATE and DELETE are blocked '
    'at the trigger layer.';


-- ============================================================
-- GROUP ROLES — reference schema
-- ============================================================
-- reference_owner  : owns all objects in the reference schema
-- reference_reader : SELECT on all reference tables/functions
-- reference_writer : INSERT, UPDATE on reference tables;
--                    USAGE/SELECT on sequences; EXECUTE on functions
-- ============================================================

DO $$ BEGIN
    CREATE ROLE "reference_owner" NOLOGIN NOINHERIT;
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'role reference_owner already exists, skipping';
END $$;
ALTER ROLE "reference_owner" NOLOGIN NOINHERIT NOBYPASSRLS;

DO $$ BEGIN
    CREATE ROLE "reference_reader" NOLOGIN NOINHERIT;
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'role reference_reader already exists, skipping';
END $$;
ALTER ROLE "reference_reader" NOLOGIN NOINHERIT NOBYPASSRLS;

DO $$ BEGIN
    CREATE ROLE "reference_writer" NOLOGIN NOINHERIT;
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'role reference_writer already exists, skipping';
END $$;
ALTER ROLE "reference_writer" NOLOGIN NOINHERIT NOBYPASSRLS;


-- ============================================================
-- GROUP ROLES — audit schema
-- ============================================================
-- audit_owner  : owns all objects in the audit schema
-- audit_writer : INSERT on all audit tables; USAGE/SELECT on
--                sequences; EXECUTE on functions
-- audit_reader : SELECT on all audit tables; EXECUTE on functions
-- ============================================================

DO $$ BEGIN
    CREATE ROLE "audit_owner" NOLOGIN NOINHERIT;
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'role audit_owner already exists, skipping';
END $$;
ALTER ROLE "audit_owner" NOLOGIN NOINHERIT NOBYPASSRLS;

DO $$ BEGIN
    CREATE ROLE "audit_writer" NOLOGIN NOINHERIT;
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'role audit_writer already exists, skipping';
END $$;
ALTER ROLE "audit_writer" NOLOGIN NOINHERIT NOBYPASSRLS;

DO $$ BEGIN
    CREATE ROLE "audit_reader" NOLOGIN NOINHERIT;
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'role audit_reader already exists, skipping';
END $$;
ALTER ROLE "audit_reader" NOLOGIN NOINHERIT NOBYPASSRLS;


-- ============================================================
-- GROUP ROLES — app schema
-- ============================================================
-- app_owner         : owns all objects in the app schema
-- app_reader_rls    : SELECT on app tables/sequences/functions,
--                     subject to RLS policies
-- app_reader_bypass : SELECT with BYPASSRLS — for admin/reporting
--                     roles that must see all rows regardless of
--                     RLS. Grant with care.
-- app_writer        : INSERT, UPDATE on app tables;
--                     USAGE/SELECT on sequences; EXECUTE on functions
-- app_deleter       : SELECT + DELETE on app tables; EXECUTE on
--                     functions. SELECT is required for filtered
--                     DELETE (DELETE … WHERE …); without it only
--                     unfiltered full-table deletes would succeed.
--                     ⚠️  Grant to login users with care — reserve
--                     for explicit soft-delete or cleanup service
--                     accounts only.
-- ============================================================

DO $$ BEGIN
    CREATE ROLE "app_owner" NOLOGIN NOINHERIT;
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'role app_owner already exists, skipping';
END $$;
ALTER ROLE "app_owner" NOLOGIN NOINHERIT NOBYPASSRLS;

DO $$ BEGIN
    CREATE ROLE "app_reader_rls" NOLOGIN NOINHERIT;
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'role app_reader_rls already exists, skipping';
END $$;
ALTER ROLE "app_reader_rls" NOLOGIN NOINHERIT NOBYPASSRLS;

DO $$ BEGIN
    -- BYPASSRLS is a role attribute, not a grantable privilege.
    -- The unconditional ALTER ROLE below ensures the attribute is
    -- present even when the role pre-existed without it.
    CREATE ROLE "app_reader_bypass" NOLOGIN NOINHERIT BYPASSRLS;
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'role app_reader_bypass already exists, ensuring BYPASSRLS';
END $$;
-- Idempotent: safe to re-run regardless of whether the role
-- was just created or already existed.
ALTER ROLE "app_reader_bypass" NOLOGIN NOINHERIT BYPASSRLS;

DO $$ BEGIN
    CREATE ROLE "app_writer" NOLOGIN NOINHERIT;
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'role app_writer already exists, skipping';
END $$;
ALTER ROLE "app_writer" NOLOGIN NOINHERIT NOBYPASSRLS;

DO $$ BEGIN
    CREATE ROLE "app_deleter" NOLOGIN NOINHERIT;
EXCEPTION WHEN duplicate_object THEN
    RAISE NOTICE 'role app_deleter already exists, skipping';
END $$;
ALTER ROLE "app_deleter" NOLOGIN NOINHERIT NOBYPASSRLS;


-- ============================================================
-- SCHEMA OWNERSHIP
-- ============================================================
-- Transfer each schema to its owner role immediately after the
-- roles are created. ALTER SCHEMA … OWNER TO is idempotent.
-- ============================================================

ALTER SCHEMA "reference" OWNER TO "reference_owner";
ALTER SCHEMA "app"       OWNER TO "app_owner";
ALTER SCHEMA "audit"     OWNER TO "audit_owner";


-- ============================================================
-- HARDEN PUBLIC SCHEMA & PUBLIC ROLE
-- ============================================================
-- PostgreSQL grants CREATE and USAGE on the "public" schema to
-- the PUBLIC pseudo-role by default. Strip those open defaults
-- and lock all three application schemas away from PUBLIC.
-- REVOKE is idempotent — revoking a privilege that is not held
-- raises only a notice, not an error.
-- ============================================================

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE USAGE  ON SCHEMA public FROM PUBLIC;

REVOKE ALL ON SCHEMA "reference" FROM PUBLIC;
REVOKE ALL ON SCHEMA "app"       FROM PUBLIC;
REVOKE ALL ON SCHEMA "audit"     FROM PUBLIC;

-- Revoke the default EXECUTE-on-all-functions granted to PUBLIC
-- in each application schema.
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA "reference" FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA "app"       FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA "audit"     FROM PUBLIC;

-- Strip the PUBLIC EXECUTE default for functions created IN THE FUTURE
-- by each owner role. Without these, any new function deployed by an
-- owner role would inherit the PostgreSQL default and be executable
-- by PUBLIC until an explicit REVOKE is issued.
ALTER DEFAULT PRIVILEGES FOR ROLE "reference_owner"
    REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE "audit_owner"
    REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE "app_owner"
    REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;


-- ============================================================
-- SCHEMA USAGE GRANTS
-- ============================================================
-- A role must hold USAGE on a schema to resolve object names
-- within it, even when it already holds table-level privileges.
-- GRANT is idempotent.
-- ============================================================

GRANT USAGE ON SCHEMA "reference" TO "reference_reader", "reference_writer";
GRANT USAGE ON SCHEMA "reference" TO "app_owner", "audit_owner";
GRANT USAGE ON SCHEMA "audit"     TO "audit_writer", "audit_reader";
GRANT USAGE ON SCHEMA "app"       TO "app_reader_rls", "app_reader_bypass",
                                     "app_writer", "app_deleter";
GRANT USAGE ON SCHEMA "app"       TO "audit_owner", "audit_writer",
                                     "audit_reader";


-- ============================================================
-- DEFAULT PRIVILEGES
-- ============================================================
-- These settings apply to objects created IN THE FUTURE by each
-- owner role. All application objects must be created via
-- SET LOCAL ROLE <owner> so these defaults fire correctly.
-- ALTER DEFAULT PRIVILEGES is idempotent.
-- ============================================================

-- --- reference schema ---
ALTER DEFAULT PRIVILEGES FOR ROLE "reference_owner" IN SCHEMA "reference"
    GRANT SELECT              ON TABLES    TO "reference_reader";
ALTER DEFAULT PRIVILEGES FOR ROLE "reference_owner" IN SCHEMA "reference"
    GRANT INSERT              ON TABLES    TO "reference_writer";
ALTER DEFAULT PRIVILEGES FOR ROLE "reference_owner" IN SCHEMA "reference"
    GRANT USAGE, SELECT       ON SEQUENCES TO "reference_writer";
ALTER DEFAULT PRIVILEGES FOR ROLE "reference_owner" IN SCHEMA "reference"
    GRANT EXECUTE             ON FUNCTIONS TO "reference_reader", "reference_writer";
ALTER DEFAULT PRIVILEGES FOR ROLE "reference_owner" IN SCHEMA "reference"
    GRANT REFERENCES          ON TABLES    TO "app_owner", "audit_owner";

-- --- audit schema ---
ALTER DEFAULT PRIVILEGES FOR ROLE "audit_owner" IN SCHEMA "audit"
    GRANT INSERT              ON TABLES    TO "audit_writer";
ALTER DEFAULT PRIVILEGES FOR ROLE "audit_owner" IN SCHEMA "audit"
    GRANT SELECT              ON TABLES    TO "audit_reader";
ALTER DEFAULT PRIVILEGES FOR ROLE "audit_owner" IN SCHEMA "audit"
    GRANT USAGE, SELECT       ON SEQUENCES TO "audit_writer";
ALTER DEFAULT PRIVILEGES FOR ROLE "audit_owner" IN SCHEMA "audit"
    GRANT EXECUTE             ON FUNCTIONS TO "audit_writer", "audit_reader";

-- --- app schema ---
ALTER DEFAULT PRIVILEGES FOR ROLE "app_owner" IN SCHEMA "app"
    GRANT SELECT                      ON TABLES    TO "app_reader_rls", "app_reader_bypass";
ALTER DEFAULT PRIVILEGES FOR ROLE "app_owner" IN SCHEMA "app"
    GRANT SELECT, INSERT, UPDATE      ON TABLES    TO "app_writer";
ALTER DEFAULT PRIVILEGES FOR ROLE "app_owner" IN SCHEMA "app"
    GRANT SELECT, DELETE              ON TABLES    TO "app_deleter";
ALTER DEFAULT PRIVILEGES FOR ROLE "app_owner" IN SCHEMA "app"
    GRANT USAGE, SELECT               ON SEQUENCES TO "app_writer";
ALTER DEFAULT PRIVILEGES FOR ROLE "app_owner" IN SCHEMA "app"
    GRANT SELECT                      ON SEQUENCES TO "app_reader_rls", "app_reader_bypass";
ALTER DEFAULT PRIVILEGES FOR ROLE "app_owner" IN SCHEMA "app"
    GRANT EXECUTE                     ON FUNCTIONS TO "app_reader_rls", "app_reader_bypass",
                                                      "app_writer", "app_deleter";
ALTER DEFAULT PRIVILEGES FOR ROLE "app_owner" IN SCHEMA "app"
    GRANT REFERENCES                  ON TABLES    TO "audit_owner";


-- ============================================================
-- BACKFILL GRANTS FOR EXISTING OBJECTS
-- ============================================================
-- Default privileges only cover objects created AFTER this
-- migration runs. These grants backfill any objects that already
-- exist at migration time. Safe to re-run.
-- ============================================================

-- --- reference ---
GRANT SELECT                  ON ALL TABLES    IN SCHEMA "reference" TO "reference_reader";
GRANT INSERT                  ON ALL TABLES    IN SCHEMA "reference" TO "reference_writer";
GRANT USAGE, SELECT           ON ALL SEQUENCES IN SCHEMA "reference" TO "reference_writer";
GRANT EXECUTE                 ON ALL FUNCTIONS IN SCHEMA "reference" TO "reference_reader", "reference_writer";
GRANT REFERENCES              ON ALL TABLES    IN SCHEMA "reference" TO "app_owner", "audit_owner";

-- --- audit ---
GRANT INSERT                  ON ALL TABLES    IN SCHEMA "audit" TO "audit_writer";
GRANT SELECT                  ON ALL TABLES    IN SCHEMA "audit" TO "audit_reader";
GRANT USAGE, SELECT           ON ALL SEQUENCES IN SCHEMA "audit" TO "audit_writer";
GRANT EXECUTE                 ON ALL FUNCTIONS IN SCHEMA "audit" TO "audit_writer", "audit_reader";

-- --- app ---
GRANT SELECT                  ON ALL TABLES    IN SCHEMA "app" TO "app_reader_rls", "app_reader_bypass";
GRANT SELECT, INSERT, UPDATE  ON ALL TABLES    IN SCHEMA "app" TO "app_writer";
GRANT SELECT, DELETE          ON ALL TABLES    IN SCHEMA "app" TO "app_deleter";
GRANT USAGE, SELECT           ON ALL SEQUENCES IN SCHEMA "app" TO "app_writer";
GRANT SELECT                  ON ALL SEQUENCES IN SCHEMA "app" TO "app_reader_rls", "app_reader_bypass";
GRANT EXECUTE                 ON ALL FUNCTIONS IN SCHEMA "app" TO "app_reader_rls", "app_reader_bypass",
                                                                  "app_writer", "app_deleter";
-- Only owner roles can CREATE views (they own the schema).
-- Writers do not receive CREATE privilege.
--
-- SECURITY INVOKER (PostgreSQL default):
--   View runs as the calling role. RLS and table grants apply
--   normally. Suitable for most application views.
--
-- SECURITY DEFINER:
--   View runs as the view owner. Useful for controlled
--   cross-privilege exposure (e.g. exposing a filtered audit
--   summary to audit_reader without granting direct table access).
--   Always combine with security_barrier = true to prevent
--   WHERE-clause predicate-pushdown leaks.
--
-- Creation pattern (inside a transaction):
--   SET LOCAL ROLE audit_owner;
--   CREATE VIEW audit."auditSummary"
--       WITH (security_barrier = true)
--       AS SELECT …;
--   GRANT SELECT ON audit."auditSummary" TO audit_reader;
-- ============================================================


-- ============================================================
-- EXAMPLE: CREATING AND GRANTING TO A LOGIN USER
-- ============================================================
-- Uncomment and adapt. Do not store plaintext passwords in
-- migration files — pass credentials via a secrets manager or
-- psql variable (psql -v pwd=… and use :'pwd').
-- ============================================================

-- CREATE ROLE app_user
--     LOGIN
--     NOINHERIT
--     PASSWORD :'app_user_password'
--     CONNECTION LIMIT 10;

-- Typical backend service account:
--   GRANT reference_reader TO app_user;
--   GRANT audit_writer     TO app_user;
--   GRANT app_reader_rls   TO app_user;
--   GRANT app_writer       TO app_user;

-- Admin / reporting account:
--   GRANT reference_reader  TO admin_user;
--   GRANT audit_reader      TO admin_user;
--   GRANT app_reader_bypass TO admin_user;

COMMIT;
