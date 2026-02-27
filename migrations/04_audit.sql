-- ============================================================
-- Migration: Audit Schema — Immutable Audit Tables
-- PostgreSQL 18
-- Run order: 04_audit.sql (last)
-- Depends on: 01_schemas.sql, 02_reference.sql, 03_public.sql
-- ============================================================
-- All tables in this file belong to the audit schema.
-- Separating audit tables into their own schema:
--   1) Enables a dedicated DB role with INSERT-only access on
--      audit.* and no UPDATE/DELETE, enforcing append-only
--      semantics at the database permission layer.
--   2) Reduces row lock contention between the high-throughput
--      public business tables and the audit write path.
--   3) Enables schema-level GRANT/REVOKE without touching
--      public schema objects (least-privilege by default).
--
-- Design pattern: core audit.auditLogs row captures what action
-- was taken, from which IP, via which user agent, and when.
-- Junction tables (auditLogVendorActors, auditLogLicenses,
-- auditLogSessions) record WHO performed the action and WHICH
-- resource was affected. Separating actor and resource into
-- junction tables allows new actor types (e.g. auditLogClientActors)
-- and new resource types to be added as new tables without any
-- migration of existing audit rows.
--
-- Cross-schema FK references use fully qualified names:
--   reference."actions", public."vendors", public."licenses",
--   public."sessions", audit."auditLogs"
-- ============================================================

-- ------------------------------------------------------------
-- audit."auditLogs"
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS audit."auditLogs" (
    "id"         UUID        PRIMARY KEY DEFAULT uuidv7(),
    "actionCode" TEXT        NOT NULL REFERENCES reference."actions"("code") ON DELETE RESTRICT,
    "ipAddress"  INET,
    "userAgent"  TEXT,
    "createdAt"  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  audit."auditLogs"               IS 'Core audit log table. Immutable append-only record of every auditable system event. Captures security and compliance context. Actor and resource recorded in separate junction tables.';
COMMENT ON COLUMN audit."auditLogs"."id"          IS 'Surrogate primary key (uuidv7, time-ordered). Referenced by all audit junction tables.';
COMMENT ON COLUMN audit."auditLogs"."actionCode"  IS 'Resource-agnostic action verb (FK to reference.actions). Resource type and ID captured in junction table (auditLogLicenses, auditLogSessions, etc.).';
COMMENT ON COLUMN audit."auditLogs"."ipAddress"   IS 'Client IP address (INET type). Supports efficient IP range queries and subnet filtering.';
COMMENT ON COLUMN audit."auditLogs"."userAgent"   IS 'HTTP User-Agent header. Used to identify SDK versions, detect automated scripts, flag anomalies.';
COMMENT ON COLUMN audit."auditLogs"."createdAt"   IS 'Timestamp when entry recorded. Always UTC. Immutable after insertion.';

-- ------------------------------------------------------------
-- audit."auditLogVendorActors"
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS audit."auditLogVendorActors" (
    "auditLogId" UUID NOT NULL PRIMARY KEY REFERENCES audit."auditLogs"("id")  ON DELETE CASCADE,
    "vendorId"   UUID NOT NULL             REFERENCES public."vendors"("id")   ON DELETE RESTRICT
);

COMMENT ON TABLE  audit."auditLogVendorActors"              IS 'Junction table linking audit entry to vendor actor. Enforces at most one vendor actor per entry (PK). Pattern allows adding auditLogClientActors in v1.0 without migrating audit.auditLogs.';
COMMENT ON COLUMN audit."auditLogVendorActors"."auditLogId" IS 'FK to audit log entry. Also the PK of this table.';
COMMENT ON COLUMN audit."auditLogVendorActors"."vendorId"   IS 'Vendor who performed the action (FK). RESTRICT prevents vendor deletion while audit trail exists.';

CREATE INDEX IF NOT EXISTS "auditLogVendorActors_vendorId_idx" ON audit."auditLogVendorActors" ("vendorId");

-- ------------------------------------------------------------
-- audit."auditLogLicenses"
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS audit."auditLogLicenses" (
    "auditLogId" UUID  NOT NULL PRIMARY KEY REFERENCES audit."auditLogs"("id")  ON DELETE CASCADE,
    "licenseId"  UUID  NOT NULL             REFERENCES public."licenses"("id")  ON DELETE RESTRICT,
    "changes"    JSONB
);

COMMENT ON TABLE  audit."auditLogLicenses"              IS 'Junction table identifying license as affected resource. Stores mutation context in changes column.';
COMMENT ON COLUMN audit."auditLogLicenses"."auditLogId" IS 'FK to audit log entry. Also the PK of this table.';
COMMENT ON COLUMN audit."auditLogLicenses"."licenseId"  IS 'License affected by action (FK). RESTRICT prevents deletion while audit trail exists.';
COMMENT ON COLUMN audit."auditLogLicenses"."changes"    IS 'Optional JSONB diff of license mutations (e.g. {"licenseStatusCode": {"from": "ACTIVE", "to": "REVOKED"}}). NULL for read-only actions.';

-- ------------------------------------------------------------
-- audit."auditLogSessions"
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS audit."auditLogSessions" (
    "auditLogId" UUID  NOT NULL PRIMARY KEY REFERENCES audit."auditLogs"("id")  ON DELETE CASCADE,
    "sessionId"  UUID  NOT NULL             REFERENCES public."sessions"("id")  ON DELETE RESTRICT,
    "changes"    JSONB
);

COMMENT ON TABLE  audit."auditLogSessions"              IS 'Junction table identifying session as affected resource. Stores mutation context in changes column.';
COMMENT ON COLUMN audit."auditLogSessions"."auditLogId" IS 'FK to audit log entry. Also the PK of this table.';
COMMENT ON COLUMN audit."auditLogSessions"."sessionId"  IS 'Session affected by action (FK). RESTRICT prevents deletion while audit trail exists.';
COMMENT ON COLUMN audit."auditLogSessions"."changes"    IS 'Optional JSONB diff of session mutations (e.g. {"sessionStatusCode": {"from": "ACTIVE", "to": "REVOKED"}}). NULL for read-only actions.';
