-- ============================================================
-- Downgrade : Audit Schema — Immutable Audit Tables
-- Platform  : LaaS (License as a Service)
-- Database  : PostgreSQL 18
-- Reverses  : 04_audit.sql
-- Run order : 04 — fourth in the downgrade sequence
-- Depends on: 07, 06, 05 down migrations must have completed
-- ============================================================
--
-- PURPOSE
--   Drops all audit tables, indexes, and the immutability
--   trigger function created by 04_audit.sql.
--   Must run after 07_audit_triggers_down.sql because audit
--   trigger functions reference audit._insert_log which
--   targets these tables.
--
-- IDEMPOTENCY
--   Safe to re-run multiple times.
--   • DROP TABLE    IF EXISTS — no error if already absent
--   • DROP FUNCTION IF EXISTS — no error if already absent
--
-- TRANSACTION
--   Wrapped in BEGIN / COMMIT — all-or-nothing.
--
-- REQUIRED PERMISSIONS
--   • Ownership of the `audit` schema (audit_owner), OR
--     SUPERUSER / database owner
--
-- CASCADE POLICY
--   CASCADE is omitted from all DROP TABLE statements.
--   Dropping each table automatically removes its associated
--   indexes (no explicit index drops needed). FK constraints
--   pointing TO audit tables from within this schema are
--   removed as each table is dropped in dependency order.
--
-- TRIGGER FUNCTION
--   audit.prevent_audit_update_delete() is dropped explicitly
--   after all tables are removed (triggers referencing it are
--   gone at that point). DROP TABLE does not remove standalone
--   functions — omitting this step leaves an orphaned function.
-- ============================================================

BEGIN;

-- ============================================================
-- Drop audit junction tables first
-- ============================================================
-- Junction tables reference audit."audit_logs" and must be
-- removed before the parent log table. Indexes on these
-- tables are removed automatically by DROP TABLE.
-- ============================================================

DROP TABLE IF EXISTS audit."audit_log_vendor_actors";
DROP TABLE IF EXISTS audit."audit_log_licenses";
DROP TABLE IF EXISTS audit."audit_log_sessions";

-- ============================================================
-- Drop core audit log table
-- ============================================================

DROP TABLE IF EXISTS audit."audit_logs";

-- ============================================================
-- Drop immutability trigger function
-- ============================================================
-- Must be dropped after the tables whose triggers reference
-- it are gone. The function signature must match exactly.
-- ============================================================

DROP FUNCTION IF EXISTS audit.prevent_audit_update_delete();

COMMIT;
