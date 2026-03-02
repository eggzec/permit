-- ============================================================
-- Downgrade : Roles & Schema Definitions
-- Platform  : LaaS (License as a Service)
-- Database  : PostgreSQL 18
-- Run order : 01 — LAST in the downgrade sequence
-- Depends on: 02_reference_down.sql, 03_app_down.sql,
--             04_audit_down.sql must have completed first
-- ============================================================
--
-- PURPOSE
--   Drops all three application schemas and all 11 group roles
--   created by 01_roles.sql.
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
--   Recommended: run as the `postgres` superuser.
--
-- WARNING
--   This script permanently destroys all application schemas
--   and roles. It cannot be undone without re-running the full
--   up migration sequence. Do not run in production without
--   an explicit approval and a verified backup.
-- ============================================================

BEGIN;

-- ============================================================
-- DROP SCHEMAS
-- ============================================================
-- Schemas must be empty before DROP SCHEMA (no CASCADE).
-- All tables and functions must have been removed by the
-- preceding down migrations (04 → 03 → 02) before this file
-- is run. If any objects remain, these statements will fail
-- with a "schema is not empty" error — the intended behaviour.
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

-- --- app schema roles ---
DROP ROLE IF EXISTS app_deleter;
DROP ROLE IF EXISTS app_writer;
DROP ROLE IF EXISTS app_reader_bypass;
DROP ROLE IF EXISTS app_reader_rls;
DROP ROLE IF EXISTS app_owner;

-- --- audit schema roles ---
DROP ROLE IF EXISTS audit_reader;
DROP ROLE IF EXISTS audit_writer;
DROP ROLE IF EXISTS audit_owner;

-- --- reference schema roles ---
DROP ROLE IF EXISTS reference_writer;
DROP ROLE IF EXISTS reference_reader;
DROP ROLE IF EXISTS reference_owner;

COMMIT;
