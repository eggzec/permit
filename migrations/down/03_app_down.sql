-- ============================================================
-- Downgrade : App Schema — Business Tables
-- Platform  : LaaS (License as a Service)
-- Database  : PostgreSQL 18
-- Run order : 03 — second in the downgrade sequence
-- Depends on: 04_audit_down.sql must have completed first so
--             that all audit FK references into this schema
--             have been removed
-- ============================================================
--
-- PURPOSE
--   Drops all business tables in the `app` schema created by
--   03_app.sql, including all heartbeat partitions, indexes,
--   and the extension table.
--
-- IDEMPOTENCY
--   Safe to re-run multiple times.
--   • DROP TABLE IF EXISTS — no error if already absent
--
-- TRANSACTION
--   Wrapped in BEGIN / COMMIT — all-or-nothing.
--
-- REQUIRED PERMISSIONS
--   • Ownership of the `app` schema (app_owner), OR
--     SUPERUSER / database owner
--
-- PARTITION STRATEGY
--   Dropping the partitioned parent table (app."heartbeats")
--   with CASCADE automatically removes all child partitions
--   (heartbeats_2026_q1 … heartbeats_2027_q1, heartbeats_default)
--   and their associated indexes in a single operation.
--   Individual partition drops are not required and are
--   intentionally omitted — enumerating them would require
--   the down migration to be updated every time a new
--   partition is added.
--
-- CASCADE POLICY
--   CASCADE is used only on app."heartbeats" to remove child
--   partitions. All other DROP TABLE statements omit CASCADE
--   so that any unexpected FK dependencies surface as errors
--   rather than silently cascading.
-- ============================================================

BEGIN;

-- ============================================================
-- Drop app."heartbeats" (partitioned)
-- ============================================================
-- CASCADE removes all quarterly partitions and the default
-- partition automatically. Indexes on the parent and all
-- child partitions are also removed by CASCADE.
-- ============================================================

DROP TABLE IF EXISTS app."heartbeats" CASCADE;

-- ============================================================
-- Drop remaining business tables
-- ============================================================
-- Dropped in reverse FK dependency order so that referencing
-- tables are removed before the tables they reference.
-- No CASCADE — misordered execution will surface as an error.
-- ============================================================

DROP TABLE IF EXISTS app."node_locked_license_data";
DROP TABLE IF EXISTS app."sessions";
DROP TABLE IF EXISTS app."licenses";
DROP TABLE IF EXISTS app."vendors";

COMMIT;
