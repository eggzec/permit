-- ============================================================
-- Migration: Schema Definitions
-- PostgreSQL 18
-- Run order: 01_schemas.sql (first)
-- ============================================================
-- Creates all schemas used by the LaaS platform.
-- Must be run before any table creation migrations.
-- ============================================================

CREATE SCHEMA IF NOT EXISTS reference;
CREATE SCHEMA IF NOT EXISTS public;
CREATE SCHEMA IF NOT EXISTS audit;

COMMENT ON SCHEMA reference IS 'Static lookup/reference tables for enumerations and constants. All rows inserted once at deploy time and treated as immutable. Separated to isolate migration risk and enable role-based access control (GRANT SELECT only to app role).';
COMMENT ON SCHEMA public    IS 'Core business tables for the LaaS licensing platform. Contains all mutable business entities with lifecycle state (vendors, licenses, sessions, heartbeats).';
COMMENT ON SCHEMA audit     IS 'Immutable append-only audit trail. Separated from public schema to enforce independent access control: audit readers have no business table access, and business writers cannot delete audit records. All tables are INSERT-only; no UPDATE or DELETE operations permitted.';
