-- ============================================================
-- Downgrade: Reference Schema — Remove Lookup Tables
-- PostgreSQL 18
-- Run order: 02_reference_down.sql (third in downgrade sequence)
-- ============================================================
-- Drops all reference/lookup tables.
-- Run this AFTER removing public and audit schema tables.
-- Run this BEFORE removing schemas.
-- ============================================================

DROP TABLE IF EXISTS reference."licenseStatuses" CASCADE;

DROP TABLE IF EXISTS reference."sessionStatuses" CASCADE;

DROP TABLE IF EXISTS reference."heartbeatRespStatuses" CASCADE;

DROP TABLE IF EXISTS reference."errorCodes" CASCADE;

DROP TABLE IF EXISTS reference."actions" CASCADE;
