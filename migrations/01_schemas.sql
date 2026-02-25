-- ============================================================
-- Migration: Schema Definitions
-- PostgreSQL 18
-- Run order: 01_schemas.sql (first)
-- ============================================================
-- Creates all schemas used by the LaaS platform.
-- Must be run before any table creation migrations.
-- ============================================================

CREATE SCHEMA IF NOT EXISTS reference;
COMMENT ON SCHEMA reference IS 'Static lookup/reference tables for enumerations and constants. Rows are inserted once at deploy time and treated as immutable by application code and FK constraints. Separated to isolate migration risk and allow tighter access control (GRANT SELECT only to app role).';

COMMENT ON SCHEMA public IS 'Core business tables for the LaaS licensing platform. Contains all entities with mutable lifecycle state (vendors, licenses, sessions, heartbeats, licenseVersions).';

CREATE SCHEMA IF NOT EXISTS audit;
COMMENT ON SCHEMA audit IS 'Immutable append-only audit tables. Separated from the public business schema to allow independent access control (audit readers should not have write access to business tables, and business writers should not be able to delete audit records). All tables in this schema are append-only; no UPDATE or DELETE operations are permitted by application roles.';
