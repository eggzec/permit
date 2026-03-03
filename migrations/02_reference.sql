-- ============================================================
-- Migration : Reference Schema — Lookup Tables
-- Platform  : LaaS (License as a Service)
-- Database  : PostgreSQL 18
-- Run order : 02 — after 01_roles.sql
-- Depends on: 01_roles.sql
-- ============================================================
--
-- PURPOSE
--   Creates and seeds all static lookup tables in the
--   `reference` schema. These tables represent closed
--   enumerations used as FK targets by the app and audit
--   schemas. Rows are inserted once at deploy time.
--
-- IDEMPOTENCY
--   Safe to re-run multiple times.
--   • CREATE TABLE : wrapped in DO $$ … EXCEPTION WHEN
--                    duplicate_table THEN RAISE NOTICE
--   • INSERT       : ON CONFLICT ("code") DO NOTHING
--                    If a code already exists the existing row
--                    is preserved unchanged. To correct a
--                    description, write a dedicated migration
--                    with an explicit UPDATE statement.
--   • COMMENT ON   : outside DO blocks intentionally — COMMENT ON
--                    is idempotent (replaces the existing comment)
--                    and requires no guard.
--
-- TRANSACTION
--   Wrapped in BEGIN / COMMIT — all-or-nothing.
--
-- REQUIRED PERMISSIONS
--   The executing principal must hold:
--   • Ownership of the `reference` schema (reference_owner), OR
--   • SUPERUSER / database owner
--   Tables are created under SET LOCAL ROLE reference_owner so
--   that ALTER DEFAULT PRIVILEGES FOR ROLE reference_owner fire
--   correctly for all objects created here.
--
-- NOTE
--   SET LOCAL ROLE reference_owner requires 01_roles.sql to have
--   been applied first. Running this file out of order will fail
--   immediately with "role does not exist", which is the intended
--   behaviour — the dependency is enforced at runtime.
--
-- DESIGN
--   All lookup tables use their `code` TEXT column as the
--   PRIMARY KEY. This avoids a meaningless surrogate UUID and
--   makes FK columns in referencing tables self-documenting
--   (e.g. license_status_code = 'ACTIVE' is readable without a
--   join). New enum values are added by INSERT only — no UPDATE
--   or DELETE of existing rows is ever permitted.
-- ============================================================

BEGIN;

-- Switch to the schema owner so that default privileges defined
-- in 01_roles.sql for reference_owner apply to all objects
-- created in this transaction.
SET LOCAL ROLE reference_owner;

-- ============================================================
-- reference."license_statuses"
-- ============================================================
-- Closed enumeration of all valid license lifecycle states.
-- EXPIRED is intentionally absent: it is a derived state
-- computed at query time from app."licenses"."expires_at".
-- Persisting it would create a redundancy risk.
-- ============================================================

DO $$ BEGIN
    CREATE TABLE reference."license_statuses" (
        "code"        TEXT PRIMARY KEY,
        "description" TEXT NOT NULL
    );
EXCEPTION WHEN duplicate_table THEN
    RAISE NOTICE 'table reference."license_statuses" already exists, skipping';
END $$;

-- COMMENT ON is idempotent and intentionally outside the DO block.
COMMENT ON TABLE  reference."license_statuses"               IS 'Lookup table for license lifecycle states. EXPIRED is intentionally omitted: expiry is a derived state computed at query time from app."licenses"."expires_at". Storing it redundantly would risk inconsistency.';
COMMENT ON COLUMN reference."license_statuses"."code"        IS 'Machine-readable status code (PK). Self-documents FK references in app."licenses". Examples: ACTIVE, REVOKED.';
COMMENT ON COLUMN reference."license_statuses"."description" IS 'Human-readable explanation of this license state for developers and operators.';

INSERT INTO reference."license_statuses" ("code", "description")
VALUES
    ('ACTIVE',  'License is valid and can be activated by a customer device.'),
    ('REVOKED', 'License was manually revoked by the vendor; no further activations or heartbeats are permitted.')
ON CONFLICT ("code") DO NOTHING;

-- ============================================================
-- reference."session_statuses"
-- ============================================================
-- Closed enumeration of all stored session lifecycle states.
-- Derived states (grace period exceeded, license expired) are
-- computed at query time and never stored.
-- ============================================================

DO $$ BEGIN
    CREATE TABLE reference."session_statuses" (
        "code"        TEXT PRIMARY KEY,
        "description" TEXT NOT NULL
    );
EXCEPTION WHEN duplicate_table THEN
    RAISE NOTICE 'table reference."session_statuses" already exists, skipping';
END $$;

COMMENT ON TABLE  reference."session_statuses"               IS 'Lookup table for session lifecycle states. Derived states (grace period exceeded, license expired) are computed at query time, not stored.';
COMMENT ON COLUMN reference."session_statuses"."code"        IS 'Machine-readable status code (PK). Values: ACTIVE, REVOKED, ZOMBIE, CLEANUP.';
COMMENT ON COLUMN reference."session_statuses"."description" IS 'Human-readable explanation of this session state for developers and operators.';

INSERT INTO reference."session_statuses" ("code", "description")
VALUES
    ('ACTIVE',  'Session is running and receiving heartbeats normally.'),
    ('REVOKED', 'Session was explicitly terminated by a vendor action or an automated system process.'),
    ('ZOMBIE',  'Session has missed the configured heartbeat grace period and is considered dead. Retained until evicted by the scheduled cleanup job or displaced when a new activation against the same license would exceed max_sessions.'),
    ('CLEANUP', 'Session is soft-deleted and retained solely for audit continuity. Eligible for hard deletion after the configured retention window expires.')
ON CONFLICT ("code") DO NOTHING;

-- ============================================================
-- reference."heartbeat_resp_statuses"
-- ============================================================
-- Response codes the server returns to the SDK on each
-- heartbeat. The SDK takes a mandatory action based on the code.
-- ============================================================

DO $$ BEGIN
    CREATE TABLE reference."heartbeat_resp_statuses" (
        "code"        TEXT PRIMARY KEY,
        "description" TEXT NOT NULL
    );
EXCEPTION WHEN duplicate_table THEN
    RAISE NOTICE 'table reference."heartbeat_resp_statuses" already exists, skipping';
END $$;

COMMENT ON TABLE  reference."heartbeat_resp_statuses"               IS 'Lookup table for heartbeat response codes returned by the server to the SDK. The server selects a code based on current license and session state; the SDK takes a mandatory action based on the code received.';
COMMENT ON COLUMN reference."heartbeat_resp_statuses"."code"        IS 'Machine-readable response code (PK). Values: CONTINUE, REFRESH, REVOKED, EXPIRED, ERROR.';
COMMENT ON COLUMN reference."heartbeat_resp_statuses"."description" IS 'Human-readable description of the response code and the SDK action it mandates.';

INSERT INTO reference."heartbeat_resp_statuses" ("code", "description")
VALUES
    ('CONTINUE', 'License is valid and the session is healthy. SDK should continue normal protected operation with no state change.'),
    ('REFRESH',  'The vendor has modified the license configuration since the last heartbeat (e.g. expiry extended, max_grace_secs changed, metadata updated). SDK must re-fetch the current license state and apply it before continuing.'),
    ('REVOKED',  'The license has been revoked. SDK must immediately halt all protected functionality and notify the end user.'),
    ('EXPIRED',  'The license has passed its expires_at timestamp. SDK must immediately halt all protected functionality and notify the end user.'),
    ('ERROR',    'An unexpected server-side error occurred during heartbeat validation. SDK should log the event and retry with exponential backoff; do not immediately halt protected functionality.')
ON CONFLICT ("code") DO NOTHING;

-- ============================================================
-- reference."error_codes"
-- ============================================================
-- Canonical business error codes for API responses and SDK
-- error handling. HTTP status code mapping is handled
-- exclusively in application code, decoupled from this table.
-- ============================================================

DO $$ BEGIN
    CREATE TABLE reference."error_codes" (
        "code"        TEXT PRIMARY KEY,
        "description" TEXT NOT NULL
    );
EXCEPTION WHEN duplicate_table THEN
    RAISE NOTICE 'table reference."error_codes" already exists, skipping';
END $$;

COMMENT ON TABLE  reference."error_codes"               IS 'Canonical lookup table for business error codes used in API responses and SDK error handling. HTTP status code mapping is handled exclusively in application code and is decoupled from this table.';
COMMENT ON COLUMN reference."error_codes"."code"        IS 'Machine-readable error code constant (PK). Referenced by API responses, SDK error handlers, and log entries.';
COMMENT ON COLUMN reference."error_codes"."description" IS 'Human-readable explanation of the error condition for developers and operators.';

INSERT INTO reference."error_codes" ("code", "description")
VALUES
    ('INVALID_CREDENTIALS',   'Authentication failed due to incorrect email or password.'),
    ('INVALID_TOKEN',         'JWT access token is missing, malformed, or has expired.'),
    ('INVALID_REFRESH_TOKEN', 'Refresh token is missing, invalid, or has passed its expiry.'),
    ('INVALID_LICENSE_KEY',   'The provided license key does not exist in the system or is malformed.'),
    ('LICENSE_REVOKED',       'The license has been revoked by the vendor and is no longer valid.'),
    ('LICENSE_EXPIRED',       'The license has passed its configured expiry date.'),
    ('INVALID_DEVICE',        'The device fingerprint submitted does not match the registered fingerprint for this node-locked license.'),
    ('UNAUTHORIZED',          'The authenticated actor does not have permission to access or modify this resource (RLS policy violation).'),
    ('NOT_FOUND',             'The requested resource does not exist.'),
    ('GRACE_PERIOD_EXCEEDED', 'The session has not received a successful heartbeat within the configured grace period window.'),
    ('MAX_SESSIONS_EXCEEDED', 'The license has reached the maximum number of permitted concurrent active sessions.'),
    ('INTERNAL_ERROR',        'An unexpected internal server error occurred.')
ON CONFLICT ("code") DO NOTHING;

-- ============================================================
-- reference."actions"
-- ============================================================
-- Auditable action verbs recorded in audit."auditLogs".
-- Codes are broadly resource-agnostic; the affected resource
-- is captured in audit junction tables. This allows new
-- resource types to be added without modifying audit."auditLogs".
-- Exception: HEARTBEAT_ERROR is heartbeat-specific by nature
-- and is an intentional exception to the resource-agnostic
-- principle — documented here to prevent future confusion.
-- ============================================================

DO $$ BEGIN
    CREATE TABLE reference."actions" (
        "code"        TEXT PRIMARY KEY,
        "description" TEXT NOT NULL
    );
EXCEPTION WHEN duplicate_table THEN
    RAISE NOTICE 'table reference."actions" already exists, skipping';
END $$;

COMMENT ON TABLE  reference."actions"               IS 'Lookup table for auditable action verbs recorded in audit."auditLogs". Codes are broadly resource-agnostic; the affected resource is captured in audit junction tables (audit."auditLogLicenses", audit."auditLogSessions", etc.). HEARTBEAT_ERROR is an intentional exception: it is heartbeat-specific by nature.';
COMMENT ON COLUMN reference."actions"."code"        IS 'Machine-readable action verb (PK). Examples: CREATED, MODIFIED, REVOKED, DELETED.';
COMMENT ON COLUMN reference."actions"."description" IS 'Human-readable description of what this action represents in the system.';

INSERT INTO reference."actions" ("code", "description")
VALUES
    ('SIGNUP',          'A new actor account was registered on the platform.'),
    ('LOGIN_SUCCESS',   'An actor successfully authenticated and received an access token.'),
    ('LOGIN_FAILED',    'An actor authentication attempt failed due to invalid credentials.'),
    ('TOKEN_REFRESHED', 'An actor obtained a new access token using a valid refresh token.'),
    ('CREATED',         'A new resource was created.'),
    ('MODIFIED',        'An existing resource was modified.'),
    ('REVOKED',         'A resource was revoked by an authorised actor.'),
    ('EXPIRED',         'A resource was transitioned to an expired state by the system.'),
    ('ACTIVATED',       'A new session was created via a successful license key activation.'),
    ('HEARTBEAT_ERROR', 'A heartbeat was received but produced a non-CONTINUE response; the event is recorded in app."heartbeats" for audit continuity.'),
    ('DELETED',         'A resource was soft-deleted.')
ON CONFLICT ("code") DO NOTHING;

COMMIT;
