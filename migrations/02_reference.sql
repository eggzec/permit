-- ============================================================
-- Migration: Reference Schema — Lookup Tables
-- PostgreSQL 18
-- Run order: 02_reference.sql
-- Depends on: 01_schemas.sql
-- ============================================================
-- All lookup tables use their `code` TEXT column as the PRIMARY
-- KEY. This avoids a surrogate UUID that carries no information
-- and makes FK columns in referencing tables self-documenting
-- (e.g. licenseStatusCode = 'ACTIVE' is readable without a join).
--
-- Rows are seeded at deploy time and treated as immutable.
-- New values are added via INSERT only — never UPDATE or DELETE.
-- ============================================================

-- ------------------------------------------------------------
-- reference."licenseStatuses"
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS reference."licenseStatuses" (
    "code"        TEXT PRIMARY KEY,
    "description" TEXT NOT NULL
);

COMMENT ON TABLE  reference."licenseStatuses"               IS 'Lookup table for license lifecycle states. EXPIRED is intentionally omitted: expiry is a derived state computed at query time from licenses.expiresAt. Storing it redundantly would risk inconsistency.';
COMMENT ON COLUMN reference."licenseStatuses"."code"        IS 'Machine-readable status code (PK). Self-documents FK references. Examples: ACTIVE, REVOKED.';
COMMENT ON COLUMN reference."licenseStatuses"."description" IS 'Human-readable explanation of this license state for developers and operators.';

INSERT INTO reference."licenseStatuses" ("code", "description") VALUES
    ('ACTIVE',  'License is valid and can be activated by a customer device.'),
    ('REVOKED', 'License was manually revoked by the vendor; no further activations or heartbeats are permitted.')
ON CONFLICT ("code") DO NOTHING;

-- ------------------------------------------------------------
-- reference."sessionStatuses"
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS reference."sessionStatuses" (
    "code"        TEXT PRIMARY KEY,
    "description" TEXT NOT NULL
);

COMMENT ON TABLE  reference."sessionStatuses"               IS 'Lookup table for session lifecycle states. Derived states (grace period exceeded, license expired) are computed at query time, not stored.';
COMMENT ON COLUMN reference."sessionStatuses"."code"        IS 'Machine-readable status code (PK). Examples: ACTIVE, REVOKED, ZOMBIE, CLEANUP.';
COMMENT ON COLUMN reference."sessionStatuses"."description" IS 'Human-readable explanation of this session state for developers and operators.';

INSERT INTO reference."sessionStatuses" ("code", "description") VALUES
    ('ACTIVE',  'Session is running and receiving heartbeats normally.'),
    ('REVOKED', 'Session was explicitly terminated by a vendor action or an automated system process.'),
    ('ZOMBIE',  'Session has missed the configured heartbeat grace period and is considered dead. Retained in the table until evicted by the scheduled cleanup job or displaced when a new activation against the same license would exceed maxSessions.'),
    ('CLEANUP', 'Session is soft-deleted and retained solely for audit continuity. Eligible for hard deletion after the configured retention window expires.')
ON CONFLICT ("code") DO NOTHING;

-- ------------------------------------------------------------
-- reference."heartbeatRespStatuses"
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS reference."heartbeatRespStatuses" (
    "code"        TEXT PRIMARY KEY,
    "description" TEXT NOT NULL
);

COMMENT ON TABLE  reference."heartbeatRespStatuses"           IS 'Lookup table for heartbeat response codes returned by server to SDK. Server selects a code based on license and session state; SDK acts on it.';
COMMENT ON COLUMN reference."heartbeatRespStatuses"."code"  IS 'Machine-readable response code (PK). Examples: CONTINUE, REFRESH, REVOKED, EXPIRED, ERROR.';
COMMENT ON COLUMN reference."heartbeatRespStatuses"."description" IS 'Human-readable description of the response code and SDK action it mandates.';

INSERT INTO reference."heartbeatRespStatuses" ("code", "description") VALUES
    ('CONTINUE', 'License is valid and the session is healthy. SDK should continue normal protected operation with no state change.'),
    ('REFRESH',  'The vendor has legitimately modified the license configuration since the last heartbeat (e.g. expiry extended, maxGraceSecs changed, metadata updated). SDK must re-fetch the current license state and apply it before continuing.'),
    ('REVOKED',  'Server determined the license has been revoked. SDK must immediately halt all protected functionality and notify the end user.'),
    ('EXPIRED',  'Server determined the license has passed its expiresAt timestamp. SDK must immediately halt all protected functionality and notify the end user.'),
    ('ERROR',    'An unexpected server-side error occurred during heartbeat validation. SDK should log the event and retry with exponential backoff; do not immediately halt protected functionality.')
ON CONFLICT ("code") DO NOTHING;

-- ------------------------------------------------------------
-- reference."errorCodes"
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS reference."errorCodes" (
    "code"        TEXT PRIMARY KEY,
    "description" TEXT NOT NULL
);

COMMENT ON TABLE  reference."errorCodes"                 IS 'Canonical lookup table for business error codes used in API responses and SDK error handling. HTTP status codes are mapped exclusively in application code (decoupled from business logic).';
COMMENT ON COLUMN reference."errorCodes"."code"           IS 'Machine-readable error code constant (PK). Referenced by API responses, SDK handlers, and logs.';
COMMENT ON COLUMN reference."errorCodes"."description"    IS 'Human-readable explanation of the error condition for developers and operators.';

INSERT INTO reference."errorCodes" ("code", "description") VALUES
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
    ('MAX_SESSIONS_EXCEEDED', 'The license has reached the maximum number of permitted concurrent active sessions for this device.'),
    ('INTERNAL_ERROR',        'An unexpected internal server error occurred.')
ON CONFLICT ("code") DO NOTHING;

-- ------------------------------------------------------------
-- reference."actions"
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS reference."actions" (
    "code"        TEXT PRIMARY KEY,
    "description" TEXT NOT NULL
);

COMMENT ON TABLE  reference."actions"                  IS 'Lookup table for auditable action verbs. Codes are resource-agnostic; affected resource is captured in audit junction tables (auditLogLicenses, auditLogSessions, etc.). Allows adding new resource types in v1.0 without modifying audit.auditLogs.';
COMMENT ON COLUMN reference."actions"."code"             IS 'Machine-readable action verb (PK). Examples: CREATED, MODIFIED, REVOKED, DELETED.';
COMMENT ON COLUMN reference."actions"."description"      IS 'Human-readable description of what this action represents in the system.';

INSERT INTO reference."actions" ("code", "description") VALUES
    ('SIGNUP',          'A new actor account was registered on the platform.'),
    ('LOGIN_SUCCESS',   'An actor successfully authenticated and received an access token.'),
    ('LOGIN_FAILED',    'An actor authentication attempt failed due to invalid credentials.'),
    ('TOKEN_REFRESHED', 'An actor obtained a new access token using a valid refresh token.'),
    ('CREATED',         'A new resource was created.'),
    ('MODIFIED',        'An existing resource was modified.'),
    ('REVOKED',         'A resource was revoked by an authorised actor.'),
    ('EXPIRED',         'A resource was transitioned to an expired state by the system.'),
    ('ACTIVATED',       'A new session was created via a successful license key activation.'),
    ('HEARTBEAT_ERROR', 'A heartbeat was received but produced a non-CONTINUE response; the event is appended to audit.heartbeats for the audit trail.'),
    ('DELETED',         'A resource was soft-deleted.')
ON CONFLICT ("code") DO NOTHING;
