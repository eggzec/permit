# Database Migrations

This directory contains the PostgreSQL 18 migration scripts for the LaaS (License as a Service) platform.

## Migration Files

Scripts are executed in alphabetical order by the Docker `postgres` image during container initialization.

1.  **`01_schemas.sql`**: Creates the `reference`, `public`, and `audit` schemas.
2.  **`02_reference.sql`**: Seeds lookup tables (statuses, error codes, actions).
3.  **`03_public.sql`**: Defines core business tables, partitions, and indexes.
4.  **`04_audit.sql`**: Sets up immutable audit trail tables with cross-schema references.

---

## Entity Relationship Diagram (ERD)

```mermaid
erDiagram
    %% REFERENCE SCHEMA
    reference_licenseStatuses {
        text code
        text description
    }
    reference_sessionStatuses {
        text code
        text description
    }
    reference_heartbeatRespStatuses {
        text code
        text description
    }
    reference_errorCodes {
        text code
        text description
    }
    reference_actions {
        text code
        text description
    }

    %% PUBLIC SCHEMA
    public_vendors {
        uuid id
        text email
        text passwordHash
        timestamptz createdAt
        timestamptz updatedAt
        timestamptz deletedAt
    }
    public_licenses {
        uuid id
        uuid vendorId
        uuid clientId
        text licenseStatusCode
        timestamptz expiresAt
        int maxGraceSecs
        jsonb metadata
        timestamptz createdAt
        timestamptz deletedAt
    }
    public_nodeLockedLicenseData {
        uuid licenseId
        text licenseKey
        text deviceFingerprintHash
        int maxSessions
    }
    public_sessions {
        uuid id
        uuid licenseId
        text sessionStatusCode
        text sessionToken
        text deviceFingerprintHash
        timestamptz createdAt
        timestamptz lastHeartbeatAt
        jsonb metadata
    }
    public_heartbeats {
        uuid id
        uuid sessionId
        text heartbeatRespStatusCode
        text errorCode
        timestamptz heartbeatAt
    }
    public_licenseVersions {
        uuid id
        uuid licenseId
        uuid vendorId
        text changeType
        jsonb previousState
        jsonb newState
        text changedBy
        text changeReason
        timestamptz changedAt
    }

    %% AUDIT SCHEMA
    audit_auditLogs {
        uuid id
        text actionCode
        inet ipAddress
        text userAgent
        timestamptz createdAt
    }
    audit_auditLogVendorActors {
        uuid auditLogId
        uuid vendorId
    }
    audit_auditLogLicenses {
        uuid auditLogId
        uuid licenseId
        jsonb changes
    }
    audit_auditLogSessions {
        uuid auditLogId
        uuid sessionId
        jsonb changes
    }

    %% RELATIONSHIPS
    public_vendors ||--o{ public_licenses : owns
    public_licenses ||--|| public_nodeLockedLicenseData : extends
    public_licenses ||--o{ public_sessions : has
    public_sessions ||--o{ public_heartbeats : emits
    public_licenses ||--o{ public_licenseVersions : versions
    public_vendors ||--o{ public_licenseVersions : modifies

    reference_licenseStatuses ||--o{ public_licenses : defines_status
    reference_sessionStatuses ||--o{ public_sessions : defines_status
    reference_heartbeatRespStatuses ||--o{ public_heartbeats : defines_result
    reference_errorCodes ||--o{ public_heartbeats : defines_error

    reference_actions ||--o{ audit_auditLogs : defines_type
    audit_auditLogs ||--|| audit_auditLogVendorActors : acts_as
    audit_auditLogs ||--o| audit_auditLogLicenses : affects
    audit_auditLogs ||--o| audit_auditLogSessions : affects

    public_vendors ||--o{ audit_auditLogVendorActors : performs
    public_licenses ||--o{ audit_auditLogLicenses : target
    public_sessions ||--o{ audit_auditLogSessions : target
```

---

## Post-Migration Verification

After the container starts, you can verify the deployment using the following commands:

### 1. Verify Schemas and Tables
```bash
# Connect to the database (assuming 'app' db name and 'postgres' user)
docker compose exec db psql -U postgres -d app -c "\dn"
docker compose exec db psql -U postgres -d app -c "SELECT schemaname, tablename FROM pg_tables WHERE schemaname IN ('reference','public','audit') ORDER BY schemaname, tablename;"
```

### 2. Check Seed Data Counts
```bash
docker compose exec db psql -U postgres -d app -c "
SELECT 'licenseStatuses: ' || COUNT(*) FROM reference.\"licenseStatuses\"
UNION ALL SELECT 'sessionStatuses: ' || COUNT(*) FROM reference.\"sessionStatuses\"
UNION ALL SELECT 'heartbeatRespStatuses: ' || COUNT(*) FROM reference.\"heartbeatRespStatuses\"
UNION ALL SELECT 'errorCodes: ' || COUNT(*) FROM reference.\"errorCodes\"
UNION ALL SELECT 'actions: ' || COUNT(*) FROM reference.\"actions\";"
```

### 3. Verify Heartbeat Partitions
```bash
docker compose exec db psql -U postgres -d app -c "SELECT tablename FROM pg_tables WHERE tablename LIKE 'heartbeats_%' ORDER BY tablename;"
```

### 4. Check UUIDv7 Defaults
```bash
docker compose exec db psql -U postgres -d app -c "SELECT table_name, column_name, column_default FROM information_schema.columns WHERE table_schema='public' AND column_name='id' AND table_name IN ('vendors', 'licenses', 'sessions');"
```

### 5. Inspect Seed Data Content
```bash
# View all registered statuses, error codes, and audit actions
docker compose exec db psql -U postgres -d app -c "SELECT * FROM reference.\"licenseStatuses\" ORDER BY code;"
docker compose exec db psql -U postgres -d app -c "SELECT * FROM reference.\"sessionStatuses\" ORDER BY code;"
docker compose exec db psql -U postgres -d app -c "SELECT * FROM reference.\"heartbeatRespStatuses\" ORDER BY code;"
docker compose exec db psql -U postgres -d app -c "SELECT code, description FROM reference.\"errorCodes\" ORDER BY code;"
docker compose exec db psql -U postgres -d app -c "SELECT code, description FROM reference.\"actions\" ORDER BY code;"
```

