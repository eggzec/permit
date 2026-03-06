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

DROP TRIGGER IF EXISTS vendors_audit_tr              ON app."vendors";
DROP TRIGGER IF EXISTS sessions_audit_tr             ON app."sessions";
DROP TRIGGER IF EXISTS v_license_node_locked_audit_tr ON app.v_license_node_locked;

-- ============================================================
-- Drop trigger functions
-- ============================================================

DROP FUNCTION IF EXISTS audit.trg_vendors_audit();
DROP FUNCTION IF EXISTS audit.trg_sessions_audit();
DROP FUNCTION IF EXISTS audit.trg_v_license_node_locked();

COMMIT;
