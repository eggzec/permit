-- ============================================================
-- Migration: Public Schema — Business Tables
-- PostgreSQL 18
-- Run order: 03_public.sql
-- Depends on: 01_schemas.sql, 02_reference.sql
-- ============================================================
-- UUID strategy: uuidv7() is a native function in PostgreSQL 18
-- (pg_catalog.uuidv7). It generates time-ordered UUIDs (v7),
-- improving B-tree index locality compared to random UUIDv4.
-- The DEFAULT on each surrogate id column ensures the database
-- generates the value when the application omits it.
-- NOTE: uuidv7() is used only on surrogate PKs that the DB
-- generates. Extension table PKs that are FK references (e.g.
-- nodeLockedLicenseData.licenseId) carry no DEFAULT because their
-- value must equal the parent row's id.
--
-- Index strategy: non-unique indexes are intentionally deferred
-- pending real query profile data. Exceptions: heartbeats indexes
-- (time-series BRIN + sessionId btree) are included from day one
-- as the partitioning strategy requires them.
-- ============================================================

-- ------------------------------------------------------------
-- public."vendors"
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS "vendors" (
    "id"           UUID        PRIMARY KEY DEFAULT uuidv7(),
    "email"        TEXT        NOT NULL UNIQUE,
    "passwordHash" TEXT        NOT NULL,
    "createdAt"    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    "updatedAt"    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    "deletedAt"    TIMESTAMPTZ
);

COMMENT ON TABLE  "vendors"                      IS 'Software vendors who issue and manage licenses on the platform. Root multi-tenant boundary: all RLS policies anchor to vendors.id.';
COMMENT ON COLUMN "vendors"."id"                 IS 'Surrogate primary key (uuidv7). Time-ordered for B-tree locality. Tenant identifier for all RLS policies.';
COMMENT ON COLUMN "vendors"."email"              IS 'Vendor login email. Globally unique.';
COMMENT ON COLUMN "vendors"."passwordHash"       IS 'bcrypt hash (≥12 rounds). Raw password never persisted.';
COMMENT ON COLUMN "vendors"."createdAt"          IS 'Account creation timestamp.';
COMMENT ON COLUMN "vendors"."updatedAt"          IS 'Last update timestamp. Application must update on every write.';
COMMENT ON COLUMN "vendors"."deletedAt"          IS 'Soft-delete marker. Non-NULL means account is deactivated. All downstream data retained for audit.';

-- ------------------------------------------------------------
-- public."licenses"
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS "licenses" (
    "id"                UUID        PRIMARY KEY DEFAULT uuidv7(),
    "vendorId"          UUID        NOT NULL REFERENCES "vendors"("id")                     ON DELETE RESTRICT,
    "clientId"          UUID,
    "licenseStatusCode" TEXT        NOT NULL REFERENCES reference."licenseStatuses"("code") ON DELETE RESTRICT,
    "expiresAt"         TIMESTAMPTZ,
    "maxGraceSecs"      INTEGER     NOT NULL,
    "metadata"          JSONB,
    "createdAt"         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    "deletedAt"         TIMESTAMPTZ,
    CONSTRAINT "licenses_maxGraceSecs_positive" CHECK ("maxGraceSecs" > 0)
);

COMMENT ON TABLE  "licenses"                     IS 'Licenses issued by vendors to customers. Root entity for activation, session management, and audit trail. License type determined by presence of extension row (e.g. nodeLockedLicenseData).';
COMMENT ON COLUMN "licenses"."id"                IS 'Surrogate primary key (uuidv7, time-ordered).';
COMMENT ON COLUMN "licenses"."vendorId"          IS 'Owning vendor (FK). Enforces multi-tenancy. Filtered by RLS policies.';
COMMENT ON COLUMN "licenses"."clientId"          IS 'Nullable placeholder for v1.0 customers table. Allows logical grouping without FK constraint in MVP.';
COMMENT ON COLUMN "licenses"."licenseStatusCode" IS 'Stored lifecycle status (FK to reference.licenseStatuses). EXPIRED derived at query time from expiresAt.';
COMMENT ON COLUMN "licenses"."expiresAt"         IS 'Optional expiry timestamp. NULL means perpetual. Expiry checked at query time, not stored in status.';
COMMENT ON COLUMN "licenses"."maxGraceSecs"      IS 'Seconds between heartbeats before session becomes zombie. License-level policy shared by all sessions. Application must provide explicit value.';
COMMENT ON COLUMN "licenses"."metadata"          IS 'Arbitrary vendor-defined key-value metadata (e.g. product tier, feature flags). Platform does not interpret or validate.';
COMMENT ON COLUMN "licenses"."createdAt"         IS 'License creation timestamp.';
COMMENT ON COLUMN "licenses"."deletedAt"         IS 'Soft-delete marker. Non-NULL means license inactive. Retained for audit history.';

-- ------------------------------------------------------------
-- public."nodeLockedLicenseData"
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS "nodeLockedLicenseData" (
    "licenseId"             UUID    PRIMARY KEY REFERENCES "licenses"("id") ON DELETE RESTRICT,
    "licenseKey"            TEXT    NOT NULL UNIQUE,
    "deviceFingerprintHash" TEXT,
    "maxSessions"           INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT "nodeLocked_maxSessions_positive" CHECK ("maxSessions" > 0)
);

COMMENT ON TABLE  "nodeLockedLicenseData"                IS 'Extension table for node-locked license subtype. Presence of row indicates license is node-locked. Future subtypes each get their own extension table; no type discriminator needed on licenses.';
COMMENT ON COLUMN "nodeLockedLicenseData"."licenseId"             IS 'FK to and PK of parent license. Enforces strict 1:1 relationship. RESTRICT prevents parent deletion while extension exists.';
COMMENT ON COLUMN "nodeLockedLicenseData"."licenseKey"            IS 'Cryptographically random activation key distributed to customer. Globally unique.';
COMMENT ON COLUMN "nodeLockedLicenseData"."deviceFingerprintHash" IS 'SHA-256 hash of device identifiers (BIOS UUID + CPU serial + disk serial). Computed server-side. NULL until first activation; locked at first heartbeat.';
COMMENT ON COLUMN "nodeLockedLicenseData"."maxSessions"           IS 'Max concurrent ACTIVE sessions on this device. Default 1. Prevents multi-process execution of single-node-locked license.';

-- ------------------------------------------------------------
-- public."sessions"
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS "sessions" (
    "id"                    UUID        PRIMARY KEY DEFAULT uuidv7(),
    "licenseId"             UUID        NOT NULL REFERENCES "licenses"("id")                    ON DELETE RESTRICT,
    "sessionStatusCode"     TEXT        NOT NULL REFERENCES reference."sessionStatuses"("code") ON DELETE RESTRICT,
    "sessionToken"          TEXT        NOT NULL UNIQUE,
    "deviceFingerprintHash" TEXT        NOT NULL,
    "createdAt"             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    "metadata"              JSONB
);

COMMENT ON TABLE  "sessions"                       IS 'Active and historical sessions created via license activation. Mostly immutable after creation. Grace period computed at query time from MAX(heartbeats.heartbeatAt).';
COMMENT ON COLUMN "sessions"."id"                    IS 'Surrogate primary key (uuidv7, time-ordered).';
COMMENT ON COLUMN "sessions"."licenseId"             IS 'License activated by this session (FK). Joined on every heartbeat to fetch maxGraceSecs, licenseStatusCode, expiresAt.';
COMMENT ON COLUMN "sessions"."sessionStatusCode"     IS 'Stored lifecycle state (ACTIVE, REVOKED, ZOMBIE, CLEANUP). Derived states (grace exceeded, expired) computed at query time.';
COMMENT ON COLUMN "sessions"."sessionToken"         IS 'Cryptographically random bearer token. Sole credential for heartbeat requests. Treat as secret.';
COMMENT ON COLUMN "sessions"."deviceFingerprintHash" IS 'Device fingerprint snapshot at session creation. Denormalized to eliminate JOIN on hot-path heartbeat validation.';
COMMENT ON COLUMN "sessions"."createdAt"            IS 'Session creation timestamp (first activation timestamp for this device+license).';
COMMENT ON COLUMN "sessions"."metadata"             IS 'Arbitrary session metadata at activation time (SDK version, OS, hostname, etc.). Immutable after creation. Platform does not interpret.';

-- ------------------------------------------------------------
-- public."heartbeats"
-- ------------------------------------------------------------
-- Append-only time-series log for non-CONTINUE heartbeat events.
-- Successful CONTINUE heartbeats are not appended here to keep write
-- amplification low; grace period is computed by querying
-- MAX(heartbeatAt) for each session at validation time.
-- Composite PK (id, heartbeatAt) is required by PostgreSQL: all
-- partition key columns must be included in the primary key of a
-- declaratively partitioned table.
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS "heartbeats" (
    "id"                      UUID        NOT NULL DEFAULT uuidv7(),
    "sessionId"               UUID        NOT NULL REFERENCES "sessions"("id")                           ON DELETE CASCADE,
    "heartbeatRespStatusCode" TEXT        NOT NULL REFERENCES reference."heartbeatRespStatuses"("code") ON DELETE RESTRICT,
    "errorCode"               TEXT        REFERENCES reference."errorCodes"("code")                     ON DELETE RESTRICT,
    "heartbeatAt"             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY ("id", "heartbeatAt")
) PARTITION BY RANGE ("heartbeatAt");

COMMENT ON TABLE  "heartbeats"                        IS 'Append-only time-series log of non-CONTINUE heartbeat events (errors, revocations, expirations, refresh triggers). Range-partitioned by heartbeatAt for efficient archival and partition pruning.';
COMMENT ON COLUMN "heartbeats"."id"                   IS 'Unique identifier (uuidv7). Composite PK with heartbeatAt (required for partitioned table).';
COMMENT ON COLUMN "heartbeats"."sessionId"            IS 'Session that emitted this event (FK). CASCADE deletion removes heartbeats during session cleanup.';
COMMENT ON COLUMN "heartbeats"."heartbeatRespStatusCode" IS 'Response code returned to SDK. Only non-CONTINUE responses logged here.';
COMMENT ON COLUMN "heartbeats"."errorCode"            IS 'Error code if response was ERROR. NULL for non-error events (REFRESH, REVOKED, EXPIRED).';
COMMENT ON COLUMN "heartbeats"."heartbeatAt"          IS 'Timestamp when event received. Partition key. BRIN index supports efficient time-range scans.';

-- Partitions: pre-create 5 quarters covering 2026 and 2027 Q1.
-- Add future partitions before the current quarter boundary.

CREATE TABLE IF NOT EXISTS "heartbeats_2026_q1" PARTITION OF "heartbeats" FOR VALUES FROM ('2026-01-01') TO ('2026-04-01');
CREATE TABLE IF NOT EXISTS "heartbeats_2026_q2" PARTITION OF "heartbeats" FOR VALUES FROM ('2026-04-01') TO ('2026-07-01');
CREATE TABLE IF NOT EXISTS "heartbeats_2026_q3" PARTITION OF "heartbeats" FOR VALUES FROM ('2026-07-01') TO ('2026-10-01');
CREATE TABLE IF NOT EXISTS "heartbeats_2026_q4" PARTITION OF "heartbeats" FOR VALUES FROM ('2026-10-01') TO ('2027-01-01');
CREATE TABLE IF NOT EXISTS "heartbeats_2027_q1" PARTITION OF "heartbeats" FOR VALUES FROM ('2027-01-01') TO ('2027-04-01');

-- Heartbeat indexes are exceptions to the deferred index policy:
-- the time-series partitioning strategy requires the BRIN index
-- from day one, and sessionId is the primary FK access pattern.

CREATE INDEX IF NOT EXISTS "heartbeats_sessionId_idx"   ON "heartbeats" ("sessionId");
CREATE INDEX IF NOT EXISTS "heartbeats_heartbeatAt_idx" ON "heartbeats" USING BRIN ("heartbeatAt");
