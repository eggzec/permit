-- ============================================================
-- Downgrade : App Schema — Business Tables
-- Platform  : LaaS (License as a Service)
-- Database  : PostgreSQL 18
-- Reverses  : 03_app.sql
-- Run order : 03 — fifth in the downgrade sequence
-- Depends on: 04_audit_down.sql must have completed first so
--             that all audit FK references into this schema
--             have been removed
-- ============================================================
--
-- PURPOSE
--   Drops all business tables, views, partitions, and indexes
--   in the `app` schema created by 03_app.sql.
--
-- ORDER
--   Views must be dropped before their underlying base tables.
--   app.v_license_node_locked references app."licenses" and
--   app."node_locked_license_data" — it is dropped first.
--
--   The INSTEAD OF trigger on the view is dropped in
--   07_audit_triggers_down.sql which runs before this file.
--   By the time this file runs the view has no triggers
--   attached and can be dropped cleanly.
--
-- IDEMPOTENCY
--   Safe to re-run multiple times.
--   • DROP VIEW  IF EXISTS — no error if already absent
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
--   Partition children (heartbeats_2026_q1 …)
--   are automatically dropped when the partitioned parent is dropped
--   in PostgreSQL — no CASCADE required. Omitting CASCADE ensures any
--   unexpected FK dependencies on app."heartbeats" surface as errors
--   rather than silently cascading to unrelated objects.
-- ============================================================

BEGIN;

-- ============================================================
-- Reverses the GRANT SELECT added in 03_app.sql.
-- ============================================================
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'audit_reader') THEN
        IF EXISTS (
            SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'app' AND c.relname = 'licenses'
        ) THEN
            REVOKE SELECT ON app."licenses" FROM audit_reader;
        END IF;
        IF EXISTS (
            SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'app' AND c.relname = 'sessions'
        ) THEN
            REVOKE SELECT ON app."sessions" FROM audit_reader;
        END IF;
    END IF;
END $$;

-- ============================================================
-- Drop view first (references base tables)
-- ============================================================

DROP VIEW IF EXISTS app."v_license_node_locked";

-- ============================================================
-- Drop app."heartbeats" (partitioned)
-- ============================================================
-- PostgreSQL automatically drops all child partitions
-- (heartbeats_2026_q1 … heartbeats_2027_q1, heartbeats_default)
-- and their indexes when the partitioned parent is dropped.
-- CASCADE is intentionally omitted — any unexpected FK
-- dependency would surface as an error rather than silently
-- cascading to unrelated objects.
-- ============================================================

DROP TABLE IF EXISTS app."heartbeats";

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
