-- ============================================================
-- Downgrade: Schema Definitions
-- PostgreSQL 18
-- Run order: 01_schemas_down.sql (last in downgrade sequence)
-- ============================================================
-- Drops all schemas created by the LaaS platform.
-- Run this AFTER removing all tables from all schemas.
-- ============================================================

DROP SCHEMA IF EXISTS audit CASCADE;

DROP SCHEMA IF EXISTS reference CASCADE;
