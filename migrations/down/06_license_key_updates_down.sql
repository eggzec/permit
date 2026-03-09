-- ============================================================
-- Downgrade : License Key Updates
-- Platform  : LaaS (License as a Service)
-- Database  : PostgreSQL 18
-- Run order : 06 — downgrade counterpart of 06_license_key_updates.sql
-- ============================================================
--
-- PURPOSE
--   Reverts the changes from 06_license_key_updates.sql:
--   1. Restores license_key back to TEXT.
--   2. Drops batch metadata columns from licenses.
--
-- IDEMPOTENCY
--   Safe to re-run. DROP COLUMN uses IF EXISTS.
-- ============================================================

BEGIN;

SET LOCAL ROLE app_owner;

-- Restore license_key to TEXT
ALTER TABLE app."node_locked_license_data"
    ALTER COLUMN "license_key" TYPE TEXT;

-- Drop batch metadata columns
ALTER TABLE app."licenses"
    DROP COLUMN IF EXISTS "batch_id",
    DROP COLUMN IF EXISTS "campaign",
    DROP COLUMN IF EXISTS "issued_by";

COMMIT;
