-- ============================================================
-- Migration : License Key Updates — Batch Metadata & Key Width
-- Platform  : LaaS (License as a Service)
-- Database  : PostgreSQL 18
-- Run order : 06 — after 05_rls.sql
-- Depends on: 03_app.sql
-- ============================================================
--
-- PURPOSE
--   1. Widens node_locked_license_data.license_key from TEXT to
--      VARCHAR(24) to enforce the 19-char format upper bound.
--   2. Adds optional batch metadata columns (batch_id, campaign,
--      issued_by) to the licenses table.
--
-- IDEMPOTENCY
--   Safe to re-run.  ALTER COLUMN TYPE is a no-op when already
--   the target type; ADD COLUMN uses IF NOT EXISTS.
--
-- TRANSACTION
--   Wrapped in BEGIN / COMMIT — all-or-nothing.
-- ============================================================

BEGIN;

SET LOCAL ROLE app_owner;

-- -------------------------------------------------------
-- 1. Widen license_key to VARCHAR(24)
-- -------------------------------------------------------

-- Preflight: abort if any existing key exceeds the new limit.
DO $$ BEGIN
    IF EXISTS (
        SELECT 1
          FROM app."node_locked_license_data"
         WHERE length("license_key") > 24
    ) THEN
        RAISE EXCEPTION
            'Cannot narrow license_key to VARCHAR(24): '
            'rows with length > 24 exist in '
            'app."node_locked_license_data". '
            'Inspect with: SELECT "license_id", "license_key" '
            'FROM app."node_locked_license_data" '
            'WHERE length("license_key") > 24;';
    END IF;
END $$;

ALTER TABLE app."node_locked_license_data"
    ALTER COLUMN "license_key" TYPE VARCHAR(24);

COMMENT ON COLUMN app."node_locked_license_data"."license_key"
    IS 'Cryptographically random activation key (format XXXX-XXXX-XXXX-XXXX, 19 chars). VARCHAR(24) allows headroom for future format changes.';

-- -------------------------------------------------------
-- 2. Add batch metadata columns to licenses
-- -------------------------------------------------------
ALTER TABLE app."licenses"
    ADD COLUMN IF NOT EXISTS "batch_id"   TEXT,
    ADD COLUMN IF NOT EXISTS "campaign"   TEXT,
    ADD COLUMN IF NOT EXISTS "issued_by"  TEXT;

COMMENT ON COLUMN app."licenses"."batch_id"  IS 'Optional identifier grouping licenses that belong to the same issuance batch.';
COMMENT ON COLUMN app."licenses"."campaign"  IS 'Optional marketing or distribution campaign associated with the license.';
COMMENT ON COLUMN app."licenses"."issued_by" IS 'Optional identifier (user-id, email, or service name) of the entity that triggered license creation.';

COMMIT;
