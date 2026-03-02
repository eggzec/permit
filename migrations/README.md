# Database Migrations

This directory contains the PostgreSQL 18 migration scripts for the LaaS (License as a Service) platform.

---

## Migration Files

Scripts are executed in lexicographical order. Each file is idempotent (safe to re-run) and wrapped in a `BEGIN / COMMIT` transaction block.

| # | File | Description |
|---|---|---|
| 01 | `01_roles.sql` | Creates the `reference`, `app`, and `audit` schemas; defines all group roles; assigns schema ownership; sets default privileges. Must run first. |
| 02 | `02_reference.sql` | Creates and seeds all static lookup tables (statuses, error codes, actions) in the `reference` schema. |
| 03 | `03_app.sql` | Creates all core business tables (`vendors`, `licenses`, `node_locked_license_data`, `sessions`, `heartbeats`) in the `app` schema, including range partitions and indexes. |
| 04 | `04_audit.sql` | Creates immutable audit trail tables in the `audit` schema and attaches `BEFORE UPDATE OR DELETE` triggers to enforce append-only semantics. |

### Role & Schema Design

All database objects are owned by dedicated group roles (`reference_owner`, `app_owner`, `audit_owner`). Login users are granted group roles and must activate them explicitly:

```sql
-- Per-transaction (recommended for connection pools):
SET LOCAL ROLE app_reader_rls;   -- resets automatically at COMMIT / ROLLBACK

-- Per-session (interactive use):
SET ROLE app_reader_rls;
RESET ROLE;

-- Automatic at session start (single-role login users):
ALTER ROLE <login_user> SET role TO 'app_reader_rls';
```

#### Group Roles Summary

| Role | Schema | Privileges |
|---|---|---|
| `reference_owner` | reference | Owns all objects |
| `reference_reader` | reference | SELECT on tables; EXECUTE on functions |
| `reference_writer` | reference | INSERT, UPDATE on tables; USAGE/SELECT on sequences; EXECUTE on functions |
| `audit_owner` | audit | Owns all objects |
| `audit_writer` | audit | INSERT on tables; USAGE/SELECT on sequences; EXECUTE on functions |
| `audit_reader` | audit | SELECT on tables; EXECUTE on functions |
| `app_owner` | app | Owns all objects |
| `app_reader_rls` | app | SELECT on tables/sequences (RLS applies); EXECUTE on functions |
| `app_reader_bypass` | app | SELECT on tables/sequences (BYPASSRLS); EXECUTE on functions |
| `app_writer` | app | INSERT, UPDATE on tables; USAGE/SELECT on sequences; EXECUTE on functions |
| `app_deleter` | app | SELECT, DELETE on tables; EXECUTE on functions ⚠️ Grant with care — reserve for soft-delete or cleanup service accounts only |

---

## Downgrade Scripts

Downgrade scripts are located in the `down/` subdirectory and must be executed in **reverse order** to safely remove all schema objects while respecting foreign key dependencies.

| Order | File | Description |
|---|---|---|
| 1st | `04_audit_down.sql` | Removes audit tables, indexes, and trigger functions |
| 2nd | `03_app_down.sql` | Removes business tables, partitions, and indexes |
| 3rd | `02_reference_down.sql` | Removes reference lookup tables |
| 4th | `01_roles_down.sql` | Removes schemas and all group roles |

To downgrade the entire database:

```bash
# Must be run in this exact order to respect FK constraints
docker compose exec db psql -U postgres -d laas -f /docker-entrypoint-initdb.d/down/04_audit_down.sql
docker compose exec db psql -U postgres -d laas -f /docker-entrypoint-initdb.d/down/03_app_down.sql
docker compose exec db psql -U postgres -d laas -f /docker-entrypoint-initdb.d/down/02_reference_down.sql
docker compose exec db psql -U postgres -d laas -f /docker-entrypoint-initdb.d/down/01_roles_down.sql
```

---

## Entity Relationship Diagram (ERD)

```mermaid
erDiagram
    %% ── REFERENCE SCHEMA ─────────────────────────────────────
    reference_license_statuses {
        text code PK
        text description
    }
    reference_session_statuses {
        text code PK
        text description
    }
    reference_heartbeat_resp_statuses {
        text code PK
        text description
    }
    reference_error_codes {
        text code PK
        text description
    }
    reference_actions {
        text code PK
        text description
    }

    %% ── APP SCHEMA ───────────────────────────────────────────
    app_vendors {
        uuid id PK
        text email
        text password_hash
        timestamptz created_at
        timestamptz updated_at
        timestamptz deleted_at
    }
    app_licenses {
        uuid id PK
        uuid vendor_id FK
        uuid client_id
        text license_status_code FK
        timestamptz expires_at
        int max_grace_secs
        jsonb metadata
        timestamptz created_at
        timestamptz updated_at
        timestamptz deleted_at
    }
    app_node_locked_license_data {
        uuid license_id PK_FK
        text license_key
        text device_fingerprint_hash
        int max_sessions
    }
    app_sessions {
        uuid id PK
        uuid license_id FK
        text session_status_code FK
        bytea session_token_hash
        text device_fingerprint_hash
        timestamptz created_at
        timestamptz updated_at
        jsonb metadata
    }
    app_heartbeats {
        uuid id PK
        timestamptz heartbeat_at PK
        uuid session_id FK
        text heartbeat_resp_status_code FK
        text error_code FK
    }

    %% ── AUDIT SCHEMA ─────────────────────────────────────────
    audit_audit_logs {
        uuid id PK
        text action_code FK
        inet ip_address
        text user_agent
        timestamptz created_at
    }
    audit_audit_log_vendor_actors {
        uuid audit_log_id PK_FK
        uuid vendor_id FK
    }
    audit_audit_log_licenses {
        uuid audit_log_id PK_FK
        uuid license_id FK
        jsonb changes
    }
    audit_audit_log_sessions {
        uuid audit_log_id PK_FK
        uuid session_id FK
        jsonb changes
    }

    %% ── RELATIONSHIPS ────────────────────────────────────────
    app_vendors                ||--o{ app_licenses                : "owns"
    app_licenses               ||--o| app_node_locked_license_data   : "extends (1:1)"
    app_licenses               ||--o{ app_sessions                : "has"
    app_sessions               ||--o{ app_heartbeats              : "emits"

    reference_license_statuses      ||--o{ app_licenses           : "defines status"
    reference_session_statuses      ||--o{ app_sessions           : "defines status"
    reference_heartbeat_resp_statuses ||--o{ app_heartbeats       : "defines response"
    reference_error_codes           ||--o{ app_heartbeats         : "defines error"

    reference_actions              ||--o{ audit_audit_logs        : "defines action"
    audit_audit_logs ||--o| audit_audit_log_vendor_actors         : "actor"
    audit_audit_logs ||--o| audit_audit_log_licenses              : "affects"
    audit_audit_logs ||--o| audit_audit_log_sessions              : "affects"

    app_vendors   ||--o{ audit_audit_log_vendor_actors            : "performs"
    app_licenses  ||--o{ audit_audit_log_licenses                 : "target of"
    app_sessions  ||--o{ audit_audit_log_sessions                 : "target of"
```
