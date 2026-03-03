-- ============================================================
-- Migration : Audit Schema — Immutable Audit Tables
-- Platform  : LaaS (License as a Service)
-- Database  : PostgreSQL 18
-- Run order : 04 — after 01_roles.sql, 02_reference.sql,
--             03_app.sql
-- Depends on: 01_roles.sql, 02_reference.sql, 03_app.sql
-- ============================================================
--
-- PURPOSE
--   Creates the append-only audit log tables and the trigger
--   infrastructure that enforces immutability at the database
--   layer.
--
-- IDEMPOTENCY
--   Safe to re-run multiple times.
--   • CREATE TABLE          : wrapped in DO $$ … EXCEPTION WHEN
--                             duplicate_table THEN RAISE NOTICE
--   • CREATE INDEX          : wrapped in DO $$ … EXCEPTION WHEN
--                             duplicate_table THEN RAISE NOTICE
--   • CREATE OR REPLACE
--     FUNCTION              : idempotent by definition
--   • CREATE OR REPLACE
--     TRIGGER               : idempotent by definition
--   • COMMENT ON            : outside DO blocks intentionally —
--                             COMMENT ON is idempotent (replaces
--                             the existing comment) and needs no
--                             guard.
--
-- TRANSACTION
--   Wrapped in BEGIN / COMMIT — all-or-nothing.
--
-- REQUIRED PERMISSIONS
--   The executing principal must hold:
--   • Ownership of the `audit` schema (audit_owner), OR
--   • SUPERUSER / database owner
--   Tables and functions are created under SET LOCAL ROLE
--   audit_owner so that ALTER DEFAULT PRIVILEGES FOR ROLE
--   audit_owner fire correctly for all objects created here.
--
-- NOTE
--   SET LOCAL ROLE audit_owner requires 01_roles.sql to have
--   been applied first. Running this file out of order will
--   fail immediately with "role does not exist", which is the
--   intended behaviour — the dependency is enforced at runtime.
--
-- ROLE & PERMISSION MANAGEMENT
--   All roles and GRANT statements are managed exclusively in
--   01_roles.sql. No role creation or privilege grants appear
--   in this file.
--
-- DESIGN — CORE LOG + JUNCTION PATTERN
--   audit."auditLogs" records WHAT happened, from WHERE (IP),
--   via WHAT client (user agent), and WHEN.
--
--   Who acted and which resource was affected are captured in
--   separate junction tables:
--     audit."auditLogVendorActors" — vendor actor
--     audit."auditLogLicenses"     — license resource
--     audit."auditLogSessions"     — session resource
--
--   Decoupling actor and resource into junction tables means new
--   actor types (e.g. auditLogClientActors) and new resource
--   types can be added as new tables in future migrations
--   without altering or migrating existing audit rows.
--
-- IMMUTABILITY ENFORCEMENT
--   Two-layer defence:
--     1) SECURITY DEFINER trigger function raises an exception
--        on any UPDATE or DELETE attempt on any audit table.
--        SECURITY DEFINER ensures the guard fires even when the
--        statement is issued by a superuser.
--     2) CREATE OR REPLACE TRIGGER attaches the guard to every
--        audit table. Re-running this migration replaces the
--        trigger definition in place rather than erroring.
--
-- ON DELETE RESTRICT ON ALL FOREIGN KEYS
--   All FKs in this schema use ON DELETE RESTRICT, including the
--   junction-table → auditLogs references. This is intentional:
--   the immutability trigger prevents deletes from audit tables
--   anyway, but RESTRICT provides an additional database-level
--   guard ensuring junction rows must be addressed before their
--   parent can be removed under any circumstance.
-- ============================================================

BEGIN;

-- Switch to the schema owner so that default privileges defined
-- in 01_roles.sql for audit_owner apply to all objects created
-- in this transaction.
SET LOCAL ROLE audit_owner;

-- ============================================================
-- audit."auditLogs"
-- ============================================================
-- Core audit record. Captures the action, network context, and
-- timestamp. Actor and resource details are in junction tables.
-- ============================================================

DO $$ BEGIN
    CREATE TABLE audit."audit_logs" (
        "id"          UUID        PRIMARY KEY DEFAULT uuidv7(),
        "action_code" TEXT        NOT NULL
                                  REFERENCES reference."actions"("code")
                                  ON DELETE RESTRICT,
        "ip_address"  INET,
        "user_agent"  TEXT,
        "created_at"  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
EXCEPTION WHEN duplicate_table THEN
    RAISE NOTICE 'table audit."audit_logs" already exists, skipping';
END $$;

-- COMMENT ON is idempotent and intentionally outside the DO block.
COMMENT ON TABLE  audit."audit_logs"               IS 'Core audit log table. Immutable append-only record of every auditable system event. Captures the action, network context, and timestamp. Actor identity and affected resource are recorded in separate junction tables.';
COMMENT ON COLUMN audit."audit_logs"."id"          IS 'Surrogate primary key (uuidv7, time-ordered). Referenced as FK by all audit junction tables.';
COMMENT ON COLUMN audit."audit_logs"."action_code" IS 'Resource-agnostic action verb (FK → reference."actions"). The specific resource type and ID are captured in the appropriate junction table.';
COMMENT ON COLUMN audit."audit_logs"."ip_address"  IS 'Client IP address at event time (INET type). Supports efficient IP-range queries and subnet filtering for security investigations.';
COMMENT ON COLUMN audit."audit_logs"."user_agent"  IS 'HTTP User-Agent header at event time. Used to identify SDK versions, detect automated scripts, and flag anomalies.';
COMMENT ON COLUMN audit."audit_logs"."created_at"  IS 'Timestamp when the entry was recorded (UTC). Immutable after insertion.';

-- ============================================================
-- audit."audit_log_vendor_actors"
-- ============================================================
-- Junction table: identifies the vendor who performed the
-- action recorded in the parent audit log entry.
-- PK on "audit_log_id" enforces at most one vendor actor per
-- entry. Future actor types (e.g. audit_log_client_actors) are
-- added as separate tables without modifying this one.
-- ============================================================

DO $$ BEGIN
    CREATE TABLE audit."audit_log_vendor_actors" (
        "audit_log_id" UUID NOT NULL PRIMARY KEY
                            REFERENCES audit."audit_logs"("id")
                            ON DELETE RESTRICT,
        "vendor_id"    UUID NOT NULL
                            REFERENCES app."vendors"("id")
                            ON DELETE RESTRICT
    );
EXCEPTION WHEN duplicate_table THEN
    RAISE NOTICE 'table audit."audit_log_vendor_actors" already exists, skipping';
END $$;

COMMENT ON TABLE  audit."audit_log_vendor_actors"                IS 'Junction table linking an audit log entry to the vendor who performed the action. The PK on "audit_log_id" enforces at most one vendor actor per log entry. Additional actor types (e.g. client actors) are added as separate junction tables.';
COMMENT ON COLUMN audit."audit_log_vendor_actors"."audit_log_id" IS 'FK → audit."audit_logs". Also the PK of this table — one vendor actor per log entry.';
COMMENT ON COLUMN audit."audit_log_vendor_actors"."vendor_id"    IS 'Vendor who performed the action (FK → app."vendors"). RESTRICT prevents vendor deletion while the audit trail exists.';

DO $$ BEGIN
    CREATE INDEX "audit_log_vendor_actors_vendor_id_idx"
        ON audit."audit_log_vendor_actors" ("vendor_id");
EXCEPTION WHEN duplicate_table THEN
    RAISE NOTICE 'index "audit_log_vendor_actors_vendor_id_idx" already exists, skipping';
END $$;

-- ============================================================
-- audit."audit_log_licenses"
-- ============================================================
-- Junction table: identifies the license affected by the action.
-- Stores an optional JSON diff of the mutation for change
-- tracking without requiring a separate change-log table.
-- ============================================================

DO $$ BEGIN
    CREATE TABLE audit."audit_log_licenses" (
        "audit_log_id" UUID  NOT NULL PRIMARY KEY
                             REFERENCES audit."audit_logs"("id")
                             ON DELETE RESTRICT,
        "license_id"   UUID  NOT NULL
                             REFERENCES app."licenses"("id")
                             ON DELETE RESTRICT,
        "changes"      JSONB
    );
EXCEPTION WHEN duplicate_table THEN
    RAISE NOTICE 'table audit."audit_log_licenses" already exists, skipping';
END $$;

COMMENT ON TABLE  audit."audit_log_licenses"                IS 'Junction table identifying a license as the resource affected by an audit log entry. Stores an optional mutation diff in "changes".';
COMMENT ON COLUMN audit."audit_log_licenses"."audit_log_id" IS 'FK → audit."audit_logs". Also the PK of this table — one license resource per log entry.';
COMMENT ON COLUMN audit."audit_log_licenses"."license_id"   IS 'License affected by the action (FK → app."licenses"). RESTRICT prevents license deletion while the audit trail exists.';
COMMENT ON COLUMN audit."audit_log_licenses"."changes"      IS 'Optional JSONB diff of license field mutations. Example: {"license_status_code": {"from": "ACTIVE", "to": "REVOKED"}}. NULL for non-mutating (read-only) actions.';

DO $$ BEGIN
    CREATE INDEX "audit_log_licenses_license_id_idx"
        ON audit."audit_log_licenses" ("license_id");
EXCEPTION WHEN duplicate_table THEN
    RAISE NOTICE 'index "audit_log_licenses_license_id_idx" already exists, skipping';
END $$;

-- ============================================================
-- audit."audit_log_sessions"
-- ============================================================
-- Junction table: identifies the session affected by the action.
-- Mirrors the structure of audit_log_licenses for consistency.
-- ============================================================

DO $$ BEGIN
    CREATE TABLE audit."audit_log_sessions" (
        "audit_log_id" UUID  NOT NULL PRIMARY KEY
                             REFERENCES audit."audit_logs"("id")
                             ON DELETE RESTRICT,
        "session_id"   UUID  NOT NULL
                             REFERENCES app."sessions"("id")
                             ON DELETE RESTRICT,
        "changes"      JSONB
    );
EXCEPTION WHEN duplicate_table THEN
    RAISE NOTICE 'table audit."audit_log_sessions" already exists, skipping';
END $$;

COMMENT ON TABLE  audit."audit_log_sessions"                IS 'Junction table identifying a session as the resource affected by an audit log entry. Stores an optional mutation diff in "changes".';
COMMENT ON COLUMN audit."audit_log_sessions"."audit_log_id" IS 'FK → audit."audit_logs". Also the PK of this table — one session resource per log entry.';
COMMENT ON COLUMN audit."audit_log_sessions"."session_id"   IS 'Session affected by the action (FK → app."sessions"). RESTRICT prevents session deletion while the audit trail exists.';
COMMENT ON COLUMN audit."audit_log_sessions"."changes"      IS 'Optional JSONB diff of session field mutations. Example: {"session_status_code": {"from": "ACTIVE", "to": "REVOKED"}}. NULL for non-mutating (read-only) actions.';

DO $$ BEGIN
    CREATE INDEX "audit_log_sessions_session_id_idx"
        ON audit."audit_log_sessions" ("session_id");
EXCEPTION WHEN duplicate_table THEN
    RAISE NOTICE 'index "audit_log_sessions_session_id_idx" already exists, skipping';
END $$;

-- ============================================================
-- IMMUTABILITY GUARDS
-- ============================================================
-- audit.prevent_audit_update_delete()
--   Trigger function that raises an exception on any UPDATE or
--   DELETE attempt against any audit-schema table.
--   SECURITY DEFINER: the function executes with the privileges
--   of its owner (audit_owner) regardless of who calls it,
--   ensuring the guard fires even for superusers.
--   SET search_path TO audit: pins the search path inside the
--   function body to prevent search-path injection attacks.
--
-- Per-table triggers use CREATE OR REPLACE TRIGGER (idempotent).
-- ============================================================

CREATE OR REPLACE FUNCTION audit.prevent_audit_update_delete()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        'Audit tables are immutable (INSERT only). '
        'UPDATE and DELETE are forbidden on %.%',
        TG_TABLE_SCHEMA, TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql
   SECURITY DEFINER
   SET search_path TO audit;

COMMENT ON FUNCTION audit.prevent_audit_update_delete() IS
    'Trigger function that blocks UPDATE/DELETE on all audit schema '
    'tables. SECURITY DEFINER ensures the guard fires even when '
    'invoked by a superuser. Attach to every table in this schema.';

-- Attach immutability trigger to each audit table.
-- CREATE OR REPLACE TRIGGER is idempotent (PostgreSQL 14+).
CREATE OR REPLACE TRIGGER prevent_audit_update_delete_tr
    BEFORE UPDATE OR DELETE ON audit."audit_logs"
    FOR EACH ROW EXECUTE FUNCTION audit.prevent_audit_update_delete();

CREATE OR REPLACE TRIGGER prevent_audit_update_delete_tr
    BEFORE UPDATE OR DELETE ON audit."audit_log_vendor_actors"
    FOR EACH ROW EXECUTE FUNCTION audit.prevent_audit_update_delete();

CREATE OR REPLACE TRIGGER prevent_audit_update_delete_tr
    BEFORE UPDATE OR DELETE ON audit."audit_log_licenses"
    FOR EACH ROW EXECUTE FUNCTION audit.prevent_audit_update_delete();

CREATE OR REPLACE TRIGGER prevent_audit_update_delete_tr
    BEFORE UPDATE OR DELETE ON audit."audit_log_sessions"
    FOR EACH ROW EXECUTE FUNCTION audit.prevent_audit_update_delete();

COMMIT;
