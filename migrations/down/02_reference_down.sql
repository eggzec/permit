-- ============================================================
-- Downgrade : Reference Schema — Lookup Tables
-- Platform  : LaaS (License as a Service)
-- Database  : PostgreSQL 18
-- Run order : 02 — sixth in the downgrade sequence
-- Depends on: 04_audit_down.sql and 03_app_down.sql must have
--             completed first so that all FK references to
--             these tables have been removed
-- ============================================================
--
-- PURPOSE
--   Drops all static lookup tables in the `reference` schema
--   created by 02_reference.sql.
--
-- IDEMPOTENCY
--   Safe to re-run multiple times.
--   • DROP TABLE IF EXISTS — no error if already absent
--
-- TRANSACTION
--   Wrapped in BEGIN / COMMIT — all-or-nothing.
--
-- REQUIRED PERMISSIONS
--   • Ownership of the `reference` schema (reference_owner),
--     OR SUPERUSER / database owner
--
-- CASCADE POLICY
--   CASCADE is intentionally omitted from all DROP TABLE
--   statements. If any FK-referencing tables still exist
--   (i.e. 03_app_down.sql or 04_audit_down.sql was not run
--   first), the DROP will fail with a clear FK dependency
--   error rather than silently stripping constraints.
--   This makes misordered execution loud rather than
--   destructively silent.
-- ============================================================

BEGIN;

-- Drop in reverse dependency order: tables referenced last
-- in the up migration are dropped first here, though for
-- reference tables with no inter-table FKs the order is
-- informational only.

DROP TABLE IF EXISTS reference."actions";
DROP TABLE IF EXISTS reference."error_codes";
DROP TABLE IF EXISTS reference."heartbeat_resp_statuses";
DROP TABLE IF EXISTS reference."session_statuses";
DROP TABLE IF EXISTS reference."license_statuses";

COMMIT;
