-- ============================================================
-- Downgrade: Public Schema — Remove Business Tables
-- PostgreSQL 18
-- Run order: 03_public_down.sql (second in downgrade sequence)
-- ============================================================
-- Drops all business tables, partitions, and indexes.
-- Run this AFTER removing audit schema tables.
-- Run this BEFORE removing reference schema tables.
-- ============================================================

-- Drop heartbeats partitions first (before dropping parent table)
DROP TABLE IF EXISTS "heartbeats_2027_q1" CASCADE;
DROP TABLE IF EXISTS "heartbeats_2026_q4" CASCADE;
DROP TABLE IF EXISTS "heartbeats_2026_q3" CASCADE;
DROP TABLE IF EXISTS "heartbeats_2026_q2" CASCADE;
DROP TABLE IF EXISTS "heartbeats_2026_q1" CASCADE;

-- Drop parent partitioned table (will cascade to any remaining child partitions)
DROP TABLE IF EXISTS "heartbeats" CASCADE;

-- Drop remaining business tables
DROP TABLE IF EXISTS "nodeLockedLicenseData" CASCADE;

DROP TABLE IF EXISTS "sessions" CASCADE;

DROP TABLE IF EXISTS "licenses" CASCADE;

DROP TABLE IF EXISTS "vendors" CASCADE;
