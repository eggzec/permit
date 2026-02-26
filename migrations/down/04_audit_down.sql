-- ============================================================
-- Downgrade: Audit Schema — Remove Immutable Audit Tables
-- PostgreSQL 18
-- Run order: 04_audit_down.sql (first in downgrade sequence)
-- ============================================================
-- Drops all audit tables and related indexes.
-- Run this BEFORE removing public schema tables.
-- ============================================================

DROP INDEX IF EXISTS audit."auditLogVendorActors_vendorId_idx";
DROP TABLE IF EXISTS audit."auditLogVendorActors" CASCADE;

DROP TABLE IF EXISTS audit."auditLogLicenses" CASCADE;

DROP TABLE IF EXISTS audit."auditLogSessions" CASCADE;

DROP TABLE IF EXISTS audit."auditLogs" CASCADE;
