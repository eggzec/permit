-- ============================================================
-- Migration : App Schema — Business Tables
-- Platform  : LaaS (License as a Service)
-- Database  : PostgreSQL 18
-- Run order : 03 — after 01_roles.sql, 02_reference.sql
-- Depends on: 01_roles.sql, 02_reference.sql
-- ============================================================
--
-- PURPOSE
--   Creates all core business tables in the `app` schema:
--   vendors, licenses, node_locked_license_data, sessions, and
--   heartbeats (range-partitioned by time).
--
-- IDEMPOTENCY
--   Safe to re-run multiple times.
--   • CREATE TABLE / partitions : wrapped in DO $$ … EXCEPTION
--     WHEN duplicate_table THEN RAISE NOTICE
--   • CREATE INDEX : wrapped in DO $$ … EXCEPTION WHEN
--     duplicate_object THEN RAISE NOTICE
--   • COMMENT ON   : outside DO blocks intentionally — COMMENT ON
--     is idempotent (replaces the existing comment) and requires
--     no guard.
--
-- TRANSACTION
--   Wrapped in BEGIN / COMMIT — all-or-nothing.
--
-- REQUIRED PERMISSIONS
--   The executing principal must hold:
--   • Ownership of the `app` schema (app_owner), OR
--   • SUPERUSER / database owner
--   Tables are created under SET LOCAL ROLE app_owner so that
--   ALTER DEFAULT PRIVILEGES FOR ROLE app_owner fire correctly
--   for all objects created here.
--
-- NOTE
--   SET LOCAL ROLE app_owner requires 01_roles.sql to have been
--   applied first. Running this file out of order will fail
--   immediately with "role does not exist", which is the intended
--   behaviour — the dependency is enforced at runtime.
--
-- UUID STRATEGY
--   uuidv7() is a native function in PostgreSQL 18
--   (pg_catalog.uuidv7). It generates time-ordered UUIDs (v7),
--   improving B-tree index locality compared to random UUIDv4.
--   DEFAULT uuidv7() on surrogate PK columns means the database
--   generates the value when the application omits it.
--   Extension table PKs that are FK references
--   (e.g. app."node_locked_license_data"."license_id") carry no
--   DEFAULT — their value must equal the parent row's id.
--
-- INDEX STRATEGY
--   Non-unique indexes are intentionally deferred pending real
--   query-profile data. Two exceptions exist for app."heartbeats":
--   the BRIN index on "heartbeat_at" and the btree index on
--   "session_id" are required from day one by the partitioning
--   and liveness-query strategy.
--
-- PARTITION MANAGEMENT
--   TODO (prod): implement automated partition management before
--   go-live. Options:
--     • pg_partman extension (recommended) — automates creation
--       and retention of time-based partitions with minimal config.
--     • Scheduled migration — a new migration file per quarter
--       created and applied before the quarter boundary date.
--   ⚠️  New partitions MUST be added before the current quarter
--   ends; inserts that fall past the last explicit range land in
--   the DEFAULT partition and lose time-range pruning benefits.
--   TODO (prod): tune BRIN pages_per_range for "heartbeat_at"
--   based on observed write volume. The default of 128 pages
--   may be too coarse for high-throughput heartbeat workloads;
--   a lower value (e.g. 32) gives finer time-range granularity
--   at the cost of a slightly larger index.
-- ============================================================

BEGIN;

-- Switch to the schema owner so that default privileges defined
-- in 01_roles.sql for app_owner apply to all objects created
-- in this transaction.
SET LOCAL ROLE app_owner;

-- ============================================================
-- app."vendors"
-- ============================================================
-- Root multi-tenant entity. All RLS policies anchor on vendor_id.
-- Soft-deleted via deleted_at; hard deletion is never performed.
-- ============================================================

DO $$ BEGIN
    CREATE TABLE app."vendors" (
        "id"              UUID        PRIMARY KEY DEFAULT uuidv7(),
        "email"           TEXT        NOT NULL,
        "password_hash"   TEXT        NOT NULL,
        "created_at"      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        "updated_at"      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        "deleted_at"      TIMESTAMPTZ
    );
EXCEPTION WHEN duplicate_table THEN
    RAISE NOTICE 'table app."vendors" already exists, skipping';
END $$;

-- Case-insensitive uniqueness on email via a functional unique index.
-- Replaces the column-level UNIQUE constraint.
DO $$ BEGIN
    CREATE UNIQUE INDEX "vendors_email_lower_idx"
        ON app."vendors" (LOWER("email"));
EXCEPTION WHEN duplicate_table THEN
    RAISE NOTICE 'index "vendors_email_lower_idx" already exists, skipping';
END $$;

-- COMMENT ON is idempotent and intentionally outside the DO block.
COMMENT ON TABLE  app."vendors"                 IS 'Software vendors who issue and manage licenses on the platform. Root multi-tenant boundary: all RLS policies anchor to app."vendors"."id".';
COMMENT ON COLUMN app."vendors"."id"            IS 'Surrogate primary key (uuidv7, time-ordered). Acts as the tenant identifier for all RLS policies.';
COMMENT ON COLUMN app."vendors"."email"         IS 'Vendor login email. Globally unique across all tenants.';
COMMENT ON COLUMN app."vendors"."password_hash" IS 'Salted hash of the vendor password (bcrypt ≥12 rounds or Argon2 with adaptive cost). Raw password is never persisted. Algorithm and parameters are encoded in the hash; application handles verification.';
COMMENT ON COLUMN app."vendors"."created_at"    IS 'Account creation timestamp (UTC).';
COMMENT ON COLUMN app."vendors"."updated_at"    IS 'Last update timestamp (UTC). Application must set this on every write.';
COMMENT ON COLUMN app."vendors"."deleted_at"    IS 'Soft-delete marker. Non-NULL means the account is deactivated. All downstream data is retained for audit purposes.';

-- ============================================================
-- app."licenses"
-- ============================================================
-- Issued by a vendor to a customer. The license type is
-- determined by the presence of an extension row (e.g.
-- app."node_locked_license_data"). EXPIRED is never stored as a
-- status — it is derived at query time from "expires_at".
-- ============================================================

DO $$ BEGIN
    CREATE TABLE app."licenses" (
        "id"                   UUID        PRIMARY KEY DEFAULT uuidv7(),
        "vendor_id"            UUID        NOT NULL
                                           REFERENCES app."vendors"("id")
                                           ON DELETE RESTRICT,
        "client_id"            UUID,
        "license_status_code"  TEXT        NOT NULL
                                           REFERENCES reference."license_statuses"("code")
                                           ON DELETE RESTRICT,
        "expires_at"           TIMESTAMPTZ,
        "max_grace_secs"       INTEGER     NOT NULL,
        "metadata"             JSONB,
        "created_at"           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        "updated_at"           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        "deleted_at"           TIMESTAMPTZ,
        CONSTRAINT "licenses_max_grace_secs_positive"
            CHECK ("max_grace_secs" > 0)
    );
EXCEPTION WHEN duplicate_table THEN
    RAISE NOTICE 'table app."licenses" already exists, skipping';
END $$;

COMMENT ON TABLE  app."licenses"                       IS 'Licenses issued by vendors to customers. Root entity for activation, session management, and the audit trail. License type is determined by the presence of an extension row (e.g. app."node_locked_license_data").';
COMMENT ON COLUMN app."licenses"."id"                  IS 'Surrogate primary key (uuidv7, time-ordered).';
COMMENT ON COLUMN app."licenses"."vendor_id"           IS 'Owning vendor (FK → app."vendors"). Enforces multi-tenancy; filtered by RLS policies.';
COMMENT ON COLUMN app."licenses"."client_id"           IS 'Nullable placeholder for a future app."customers" table. Allows logical customer grouping without a FK constraint in the current schema version.';
COMMENT ON COLUMN app."licenses"."license_status_code" IS 'Stored lifecycle status (FK → reference."license_statuses"). EXPIRED is intentionally absent — it is derived at query time from "expires_at" to avoid redundancy.';
COMMENT ON COLUMN app."licenses"."expires_at"          IS 'Optional expiry timestamp (UTC). NULL means the license is perpetual. Expiry is checked at query time, not persisted as a status.';
COMMENT ON COLUMN app."licenses"."max_grace_secs"      IS 'Seconds between heartbeats before a session transitions to ZOMBIE. License-level policy shared by all sessions on this license. Must be > 0; application must supply an explicit value.';
COMMENT ON COLUMN app."licenses"."metadata"            IS 'Arbitrary vendor-defined key-value metadata (e.g. product tier, feature flags). The platform does not interpret or validate this field.';
COMMENT ON COLUMN app."licenses"."created_at"          IS 'License creation timestamp (UTC).';
COMMENT ON COLUMN app."licenses"."updated_at"          IS 'Last update timestamp (UTC). Application must set this on every write.';
COMMENT ON COLUMN app."licenses"."deleted_at"          IS 'Soft-delete marker. Non-NULL means the license is inactive. Retained for audit history; hard deletion is never performed.';

-- ============================================================
-- app."node_locked_license_data"
-- ============================================================
-- Extension table for the node-locked license subtype.
-- Presence of a row signals the parent license is node-locked.
-- Future subtypes (e.g. floating, site) each get their own
-- extension table — no type discriminator column is needed on
-- app."licenses".
-- ============================================================

DO $$ BEGIN
    CREATE TABLE app."node_locked_license_data" (
        "license_id"              UUID    PRIMARY KEY
                                          REFERENCES app."licenses"("id")
                                          ON DELETE RESTRICT,
        "license_key"             TEXT    NOT NULL UNIQUE,
        "device_fingerprint_hash" TEXT,
        "max_sessions"            INTEGER NOT NULL DEFAULT 1,
        CONSTRAINT "node_locked_max_sessions_positive"
            CHECK ("max_sessions" > 0)
    );
EXCEPTION WHEN duplicate_table THEN
    RAISE NOTICE 'table app."node_locked_license_data" already exists, skipping';
END $$;

COMMENT ON TABLE  app."node_locked_license_data"                           IS 'Extension table for the node-locked license subtype. Presence of a row indicates the parent license is node-locked. Future subtypes each get their own extension table; no type discriminator is needed on app."licenses".';
COMMENT ON COLUMN app."node_locked_license_data"."license_id"              IS 'FK to and PK of the parent license (app."licenses"). Enforces a strict 1:1 relationship. RESTRICT prevents parent deletion while this extension row exists.';
COMMENT ON COLUMN app."node_locked_license_data"."license_key"             IS 'Cryptographically random activation key distributed to the customer. Globally unique across all licenses.';
COMMENT ON COLUMN app."node_locked_license_data"."device_fingerprint_hash" IS 'SHA-256 hash of device identifiers (BIOS UUID + CPU serial + disk serial). Computed server-side. NULL until first activation; locked to the value stored in app."sessions"."device_fingerprint_hash" on the first successful heartbeat for this license.';
COMMENT ON COLUMN app."node_locked_license_data"."max_sessions"            IS 'Maximum number of concurrent ACTIVE sessions permitted on this device. Default 1. Prevents multi-process execution of a single node-locked license.';

-- ============================================================
-- app."sessions"
-- ============================================================
-- Created on license activation; mostly immutable thereafter.
-- session_status_code and updated_at are updated on state
-- transitions. Liveness is determined at query time by
-- querying MAX("heartbeat_at") in app."heartbeats" for the
-- given session_id — no hot-table updates on heartbeat events.
-- ============================================================

DO $$ BEGIN
    CREATE TABLE app."sessions" (
        "id"                      UUID        PRIMARY KEY DEFAULT uuidv7(),
        "license_id"              UUID        NOT NULL
                                              REFERENCES app."licenses"("id")
                                              ON DELETE RESTRICT,
        "session_status_code"     TEXT        NOT NULL
                                              REFERENCES reference."session_statuses"("code")
                                              ON DELETE RESTRICT,
        "session_token_hash"      BYTEA       NOT NULL UNIQUE,
        "device_fingerprint_hash" TEXT        NOT NULL,
        "created_at"              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        "updated_at"              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        "metadata"                JSONB
    );
EXCEPTION WHEN duplicate_table THEN
    RAISE NOTICE 'table app."sessions" already exists, skipping';
END $$;

COMMENT ON TABLE  app."sessions"                           IS 'Active and historical sessions created via license activation. Mostly immutable after creation; "session_status_code" and "updated_at" are updated on state transitions. Liveness is determined by querying MAX("heartbeat_at") in app."heartbeats" for the given session_id.';
COMMENT ON COLUMN app."sessions"."id"                      IS 'Surrogate primary key (uuidv7, time-ordered).';
COMMENT ON COLUMN app."sessions"."license_id"              IS 'License activated by this session (FK → app."licenses"). Joined on every heartbeat to retrieve max_grace_secs, license_status_code, and expires_at.';
COMMENT ON COLUMN app."sessions"."session_status_code"     IS 'Stored lifecycle state (FK → reference."session_statuses"). Values: ACTIVE, REVOKED, ZOMBIE, CLEANUP. Derived states (grace period exceeded, license expired) are computed at query time and never stored.';
COMMENT ON COLUMN app."sessions"."session_token_hash"      IS 'One-way hash (HMAC-SHA256) of the session bearer token. The sole credential used to authenticate heartbeat requests.';
COMMENT ON COLUMN app."sessions"."device_fingerprint_hash" IS 'Device fingerprint captured at session creation (activation time). For node-locked licenses, this value is used to populate app."node_locked_license_data"."device_fingerprint_hash" on the first successful heartbeat if that column is still NULL.';
COMMENT ON COLUMN app."sessions"."created_at"              IS 'Session creation timestamp (UTC). Represents the activation moment for this device and license combination.';
COMMENT ON COLUMN app."sessions"."updated_at"              IS 'Last update timestamp (UTC). Updated on every session state transition (e.g. ACTIVE → ZOMBIE).';
COMMENT ON COLUMN app."sessions"."metadata"                IS 'Arbitrary metadata captured at activation time (SDK version, OS, hostname, etc.). Immutable after creation. The platform does not interpret this field.';

-- ============================================================
-- app."heartbeats"
-- ============================================================
-- Append-only time-series log of every heartbeat event
-- (CONTINUE and all non-CONTINUE responses). Recording all
-- types enables accurate liveness tracking via
-- MAX("heartbeat_at") without write-heavy updates to
-- app."sessions".
--
-- COMPOSITE PK ("id", "heartbeat_at")
--   Required by PostgreSQL: all partition key columns must be
--   included in the primary key of a declaratively partitioned
--   table.
--
-- FOREIGN KEY FROM PARTITIONED TABLE
--   FK references from a partitioned table are supported in
--   PostgreSQL 12+ and are enforced per-partition automatically.
--
-- ON DELETE CASCADE ON "session_id"
--   Hard-deleting a session removes all its heartbeat rows.
--   Sessions are soft-deleted (CLEANUP status) under normal
--   operation, so the CASCADE should never fire in production.
--   Retained as a safety net for explicit hard-delete maintenance
--   operations. Confirm this aligns with your audit retention
--   policy before performing hard deletes on app."sessions".
--
-- PARTITION DEPENDENCY NOTE
--   Partition DO blocks below depend on app."heartbeats" existing.
--   If the parent CREATE TABLE was skipped (already exists), the
--   PARTITION OF statements execute correctly against the existing
--   parent. If the parent is absent for any other reason the
--   partition statements will fail with an unhandled error and
--   abort the transaction — this is the desired behaviour.
-- ============================================================

DO $$ BEGIN
    CREATE TABLE app."heartbeats" (
        "id"                         UUID        NOT NULL DEFAULT uuidv7(),
        "session_id"                 UUID        NOT NULL
                                                 REFERENCES app."sessions"("id")
                                                 ON DELETE CASCADE,
        "heartbeat_resp_status_code" TEXT        NOT NULL
                                                 REFERENCES reference."heartbeat_resp_statuses"("code")
                                                 ON DELETE RESTRICT,
        "error_code"                 TEXT
                                                 REFERENCES reference."error_codes"("code")
                                                 ON DELETE RESTRICT,
        "heartbeat_at"               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY ("id", "heartbeat_at"),
        -- error_code must be non-NULL when the response is ERROR,
        -- and must be NULL for all other response codes.
        CONSTRAINT "chk_heartbeats_status_error_code_consistency" CHECK (
            ("heartbeat_resp_status_code" =  'ERROR' AND "error_code" IS NOT NULL) OR
            ("heartbeat_resp_status_code" != 'ERROR' AND "error_code" IS NULL)
        )
    ) PARTITION BY RANGE ("heartbeat_at");
EXCEPTION WHEN duplicate_table THEN
    RAISE NOTICE 'table app."heartbeats" (partitioned) already exists, skipping';
END $$;

COMMENT ON TABLE  app."heartbeats"                              IS 'Append-only time-series log of all heartbeat events (CONTINUE, errors, revocations, expirations). Range-partitioned by "heartbeat_at". Liveness is determined by querying MAX("heartbeat_at") for a given session_id.';
COMMENT ON COLUMN app."heartbeats"."id"                         IS 'Unique row identifier (uuidv7). Forms part of the composite PK required by PostgreSQL for partitioned tables.';
COMMENT ON COLUMN app."heartbeats"."session_id"                 IS 'Session that emitted this heartbeat event (FK → app."sessions"). CASCADE deletion removes heartbeat rows if a session is hard-deleted.';
COMMENT ON COLUMN app."heartbeats"."heartbeat_resp_status_code" IS 'Response code returned to the SDK (FK → reference."heartbeat_resp_statuses"). CONTINUE responses are recorded to support liveness tracking without updating app."sessions".';
COMMENT ON COLUMN app."heartbeats"."error_code"                 IS 'Error code populated when "heartbeat_resp_status_code" = ERROR (FK → reference."error_codes"). Must be NULL for all non-ERROR responses. Enforced by chk_heartbeats_status_error_code_consistency.';
COMMENT ON COLUMN app."heartbeats"."heartbeat_at"               IS 'Timestamp when the heartbeat event was received by the server (UTC). Partition key; BRIN index supports efficient time-range scans for liveness queries.';

-- ------------------------------------------------------------
-- Quarterly range partitions — 2026 Q1 through 2027 Q1
-- See PARTITION MANAGEMENT in the file header for production
-- guidance on adding future partitions before go-live.
-- ------------------------------------------------------------

DO $$ BEGIN
    CREATE TABLE app."heartbeats_2026_q1"
        PARTITION OF app."heartbeats"
        FOR VALUES FROM (TIMESTAMPTZ '2026-01-01 00:00:00+00')
                     TO (TIMESTAMPTZ '2026-04-01 00:00:00+00');
EXCEPTION WHEN duplicate_table THEN
    RAISE NOTICE 'partition app."heartbeats_2026_q1" already exists, skipping';
END $$;

DO $$ BEGIN
    CREATE TABLE app."heartbeats_2026_q2"
        PARTITION OF app."heartbeats"
        FOR VALUES FROM (TIMESTAMPTZ '2026-04-01 00:00:00+00')
                     TO (TIMESTAMPTZ '2026-07-01 00:00:00+00');
EXCEPTION WHEN duplicate_table THEN
    RAISE NOTICE 'partition app."heartbeats_2026_q2" already exists, skipping';
END $$;

DO $$ BEGIN
    CREATE TABLE app."heartbeats_2026_q3"
        PARTITION OF app."heartbeats"
        FOR VALUES FROM (TIMESTAMPTZ '2026-07-01 00:00:00+00')
                     TO (TIMESTAMPTZ '2026-10-01 00:00:00+00');
EXCEPTION WHEN duplicate_table THEN
    RAISE NOTICE 'partition app."heartbeats_2026_q3" already exists, skipping';
END $$;

DO $$ BEGIN
    CREATE TABLE app."heartbeats_2026_q4"
        PARTITION OF app."heartbeats"
        FOR VALUES FROM (TIMESTAMPTZ '2026-10-01 00:00:00+00')
                     TO (TIMESTAMPTZ '2027-01-01 00:00:00+00');
EXCEPTION WHEN duplicate_table THEN
    RAISE NOTICE 'partition app."heartbeats_2026_q4" already exists, skipping';
END $$;

DO $$ BEGIN
    CREATE TABLE app."heartbeats_2027_q1"
        PARTITION OF app."heartbeats"
        FOR VALUES FROM (TIMESTAMPTZ '2027-01-01 00:00:00+00')
                     TO (TIMESTAMPTZ '2027-04-01 00:00:00+00');
EXCEPTION WHEN duplicate_table THEN
    RAISE NOTICE 'partition app."heartbeats_2027_q1" already exists, skipping';
END $$;

-- DEFAULT partition: catches any insert beyond the last explicit
-- range boundary, preventing insert failures at the cost of
-- losing time-range pruning for those rows. Monitor and move
-- rows to a proper partition during the next partition rotation.
DO $$ BEGIN
    CREATE TABLE app."heartbeats_default"
        PARTITION OF app."heartbeats" DEFAULT;
EXCEPTION WHEN duplicate_table THEN
    RAISE NOTICE 'partition app."heartbeats_default" already exists, skipping';
END $$;

-- ------------------------------------------------------------
-- Indexes on app."heartbeats"
-- ------------------------------------------------------------
-- Indexes created on the partition parent are automatically
-- propagated to all existing and future child partitions
-- (PostgreSQL 11+), including heartbeats_default.
--
-- These two indexes are exceptions to the deferred index policy
-- and are required from day one:
--   heartbeats_session_id_idx    — primary FK access pattern on
--     every heartbeat validation query.
--   heartbeats_heartbeat_at_idx  — BRIN index required by the
--     time-range liveness query strategy.
-- ------------------------------------------------------------

DO $$ BEGIN
    CREATE INDEX "heartbeats_session_id_idx"
        ON app."heartbeats" ("session_id");
EXCEPTION WHEN duplicate_table THEN
    RAISE NOTICE 'index "heartbeats_session_id_idx" already exists, skipping';
END $$;

DO $$ BEGIN
    CREATE INDEX "heartbeats_heartbeat_at_idx"
        ON app."heartbeats" USING BRIN ("heartbeat_at");
EXCEPTION WHEN duplicate_table THEN
    RAISE NOTICE 'index "heartbeats_heartbeat_at_idx" already exists, skipping';
END $$;

COMMIT;
