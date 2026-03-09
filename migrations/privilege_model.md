# Up Migration Permission Model Overview

Scope: `migrations/01_roles.sql` -> `migrations/07_audit_triggers.sql` only (up migrations).

Excluded: down migrations, migration tests, runtime application code outside explicit SQL definitions.

## 1) Object Inventory (What Exists)

| Object Type | Count | Defined In | Notes |
|---|---:|---|---|
| Schemas | 3 | `01_roles.sql` | `reference`, `app`, `audit` |
| Roles (group roles) | 11 | `01_roles.sql` | All `NOLOGIN`, all `NOINHERIT`; only `app_reader_bypass` has `BYPASSRLS` |
| Tables (non-partition child) | 14 | `02_reference.sql`, `03_app.sql`, `04_audit.sql` | `reference` 5 + `app` 5 + `audit` 4 |
| Partition child tables | 6 | `03_app.sql` | `heartbeats_2026_q1..q4`, `heartbeats_2027_q1`, `heartbeats_default` |
| Views | 1 | `03_app.sql` | `app.v_license_node_locked` |
| Indexes | 6 | `03_app.sql`, `04_audit.sql` | 3 in `app`, 3 in `audit` |
| Functions | 11 | `04_audit.sql`, `05_functions.sql`, `07_audit_triggers.sql` | Utility + audit + trigger functions |
| Triggers | 8 | `04_audit.sql`, `07_audit_triggers.sql` | 4 immutability + 4 business/audit |
| RLS-enabled tables | 8 | `06_rls.sql` | 4 app + 4 audit |
| RLS policies | 24 | `06_rls.sql` | 16 app + 8 audit |
| Sequences explicitly created | 0 | N/A | UUIDv7 used; grants still include sequence privileges for future-proofing |

## 2) Schemas and Roles (What They Do, What They Need)

### 2.1 Role Attributes

| Role | Core Purpose | Key Attributes |
|---|---|---|
| `reference_owner` | Owns `reference` schema objects | `NOLOGIN NOINHERIT NOBYPASSRLS` |
| `reference_reader` | Read lookups | `NOLOGIN NOINHERIT NOBYPASSRLS` |
| `reference_writer` | Insert reference rows | `NOLOGIN NOINHERIT NOBYPASSRLS` |
| `app_owner` | Owns `app` schema objects | `NOLOGIN NOINHERIT NOBYPASSRLS` |
| `app_reader_rls` | Tenant-scoped app reads | `NOLOGIN NOINHERIT NOBYPASSRLS` |
| `app_reader_bypass` | Cross-tenant app reads | `NOLOGIN NOINHERIT BYPASSRLS` |
| `app_writer` | App write path (insert/update) | `NOLOGIN NOINHERIT NOBYPASSRLS` |
| `app_deleter` | App delete path | `NOLOGIN NOINHERIT NOBYPASSRLS` |
| `audit_owner` | Owns `audit` schema objects | `NOLOGIN NOINHERIT NOBYPASSRLS` |
| `audit_writer` | Insert into audit tables | `NOLOGIN NOINHERIT NOBYPASSRLS` |
| `audit_reader` | Read audit tables | `NOLOGIN NOINHERIT NOBYPASSRLS` |

### 2.2 Schema Ownership and Usage Grants

| Schema | Owner | Explicit `USAGE` Grants | Explicit `TRIGGER` Grants |
|---|---|---|---|
| `reference` | `reference_owner` | `reference_reader`, `reference_writer`, `app_owner`, `audit_owner` | — |
| `app` | `app_owner` | `app_reader_rls`, `app_reader_bypass`, `app_writer`, `app_deleter`, `audit_owner`, `audit_writer`, `audit_reader` | `audit_owner` (on `vendors`, `sessions`, `v_license_node_locked`) |
| `audit` | `audit_owner` | `audit_writer`, `audit_reader` | — |

### 2.3 Public Hardening (Explicit Revokes)

| Target | What Is Revoked |
|---|---|
| `public` schema | `CREATE`, `USAGE` from `PUBLIC` |
| `reference`, `app`, `audit` schemas | all privileges from `PUBLIC` |
| existing functions in all 3 schemas | `EXECUTE` from `PUBLIC` |
| future functions by `reference_owner`, `app_owner`, `audit_owner` | `EXECUTE` from `PUBLIC` (via `ALTER DEFAULT PRIVILEGES`) |

## 3) Explicit Privileges (DCL Matrix)

### 3.1 Default Privileges (Future Objects)

| Owner + Schema | Object Class | Privileges | Granted To |
|---|---|---|---|
| `reference_owner` in `reference` | TABLES | `SELECT` | `reference_reader` |
| `reference_owner` in `reference` | TABLES | `INSERT` | `reference_writer` |
| `reference_owner` in `reference` | SEQUENCES | `USAGE, SELECT` | `reference_writer` |
| `reference_owner` in `reference` | FUNCTIONS | `EXECUTE` | `reference_reader, reference_writer` |
| `reference_owner` in `reference` | TABLES | `REFERENCES` | `app_owner, audit_owner` |
| `audit_owner` in `audit` | TABLES | `INSERT` | `audit_writer` |
| `audit_owner` in `audit` | TABLES | `SELECT` | `audit_reader` |
| `audit_owner` in `audit` | SEQUENCES | `USAGE, SELECT` | `audit_writer` |
| `audit_owner` in `audit` | FUNCTIONS | `EXECUTE` | `audit_writer, audit_reader` |
| `app_owner` in `app` | TABLES | `SELECT` | `app_reader_rls, app_reader_bypass` |
| `app_owner` in `app` | TABLES | `SELECT, INSERT, UPDATE` | `app_writer` |
| `app_owner` in `app` | TABLES | `SELECT, DELETE` | `app_deleter` |
| `app_owner` in `app` | SEQUENCES | `USAGE, SELECT` | `app_writer` |
| `app_owner` in `app` | SEQUENCES | `SELECT` | `app_reader_rls, app_reader_bypass` |
| `app_owner` in `app` | FUNCTIONS | `EXECUTE` | `app_reader_rls, app_reader_bypass, app_writer, app_deleter` |
| `app_owner` in `app` | TABLES | `REFERENCES` | `audit_owner` |

### 3.2 Tables

All table-level privileges come from `ALTER DEFAULT PRIVILEGES` set in `01_roles.sql`; no per-table explicit `GRANT` statements exist in `01`–`07`.

| Table | Default Privileges | Explicit Grants |
|---|---|---|
| `reference.license_statuses` | `SELECT` → `reference_reader`; `INSERT` → `reference_writer`; `REFERENCES` → `app_owner`, `audit_owner` | — |
| `reference.session_statuses` | `SELECT` → `reference_reader`; `INSERT` → `reference_writer`; `REFERENCES` → `app_owner`, `audit_owner` | — |
| `reference.heartbeat_resp_statuses` | `SELECT` → `reference_reader`; `INSERT` → `reference_writer`; `REFERENCES` → `app_owner`, `audit_owner` | — |
| `reference.error_codes` | `SELECT` → `reference_reader`; `INSERT` → `reference_writer`; `REFERENCES` → `app_owner`, `audit_owner` | — |
| `reference.actions` | `SELECT` → `reference_reader`; `INSERT` → `reference_writer`; `REFERENCES` → `app_owner`, `audit_owner` | — |
| `app.vendors` | `SELECT` → `app_reader_rls`, `app_reader_bypass`, `app_writer`, `app_deleter`; `INSERT`, `UPDATE` → `app_writer`; `DELETE` → `app_deleter`; `REFERENCES` → `audit_owner` | — |
| `app.licenses` | `SELECT` → `app_reader_rls`, `app_reader_bypass`, `app_writer`, `app_deleter`; `INSERT`, `UPDATE` → `app_writer`; `DELETE` → `app_deleter`; `REFERENCES` → `audit_owner` | — |
| `app.node_locked_license_data` | `SELECT` → `app_reader_rls`, `app_reader_bypass`, `app_writer`, `app_deleter`; `INSERT`, `UPDATE` → `app_writer`; `DELETE` → `app_deleter`; `REFERENCES` → `audit_owner` | — |
| `app.sessions` | `SELECT` → `app_reader_rls`, `app_reader_bypass`, `app_writer`, `app_deleter`; `INSERT`, `UPDATE` → `app_writer`; `DELETE` → `app_deleter`; `REFERENCES` → `audit_owner` | — |
| `app.heartbeats` *(+ 6 partition children)* | `SELECT` → `app_reader_rls`, `app_reader_bypass`, `app_writer`, `app_deleter`; `INSERT`, `UPDATE` → `app_writer`; `DELETE` → `app_deleter`; `REFERENCES` → `audit_owner` | — |
| `app.v_license_node_locked` *(view)* | `SELECT` → `app_reader_rls`, `app_reader_bypass`, `app_writer`, `app_deleter`; `INSERT`, `UPDATE` → `app_writer`; `DELETE` → `app_deleter`; `REFERENCES` → `audit_owner` | — |
| `audit.audit_logs` | `INSERT` → `audit_writer`; `SELECT` → `audit_reader` | — |
| `audit.audit_log_vendor_actors` | `INSERT` → `audit_writer`; `SELECT` → `audit_reader` | — |
| `audit.audit_log_licenses` | `INSERT` → `audit_writer`; `SELECT` → `audit_reader` | — |
| `audit.audit_log_sessions` | `INSERT` → `audit_writer`; `SELECT` → `audit_reader` | — |

### 3.3 Functions and Trigger Functions

Schema-wide `REVOKE EXECUTE FROM PUBLIC` for all functions is covered in §2.3 and is not repeated per row.

**Notation**: Strikethrough entries (~~role~~) in the "Explicit EXECUTE" column indicate explicit REVOKE statements added to reverse overly-permissive default privileges from 01_roles.sql. These ensure SECURITY DEFINER functions are restricted to their intended executor roles only (least privilege principle).

| Function | Owner | Security | Default EXECUTE | Explicit EXECUTE | Purpose |
|---|---|---|---|---|---|
| `app.set_app_context(UUID, TEXT, TEXT)` | `app_owner` | INVOKER | `app_reader_rls`, `app_reader_bypass`, `app_writer`, `app_deleter` | `audit_reader` | Sets tx-local `app.vendor_id`, `app.ip_address`, `app.user_agent` for RLS and audit |
| `audit.prevent_audit_update_delete()` | `audit_owner` | SECURITY DEFINER; `search_path` fixed | `audit_writer`, `audit_reader` | — | Raises exception on any `UPDATE`/`DELETE` on audit tables; trigger-only |
| `audit._insert_log(TEXT, UUID, JSONB, UUID, UUID, UUID)` | `audit_owner` | SECURITY DEFINER; `search_path` fixed | `audit_writer`, `audit_reader` | `app_writer`, `app_deleter` \| ~~`audit_reader`~~ | Writes `audit_logs` row + optional junction rows; reads ip/user_agent from tx context. Body is INSERT-only; broader audit_owner scope is safe in practice. |
| `audit.log_login_success(UUID)` | `audit_owner` | INVOKER | `audit_writer`, `audit_reader` | `app_writer`, `app_deleter` | Emits `LOGIN_SUCCESS` |
| `audit.log_login_failed(UUID)` | `audit_owner` | INVOKER | `audit_writer`, `audit_reader` | `app_writer`, `app_deleter` | Emits `LOGIN_FAILED`; `p_vendor_id` nullable |
| `audit.log_token_refreshed(UUID)` | `audit_owner` | INVOKER | `audit_writer`, `audit_reader` | `app_writer`, `app_deleter` | Emits `TOKEN_REFRESHED` |
| `audit.log_heartbeat_error(UUID, UUID, TEXT)` | `audit_owner` | INVOKER | `audit_writer`, `audit_reader` | `app_writer`, `app_deleter` | Emits `HEARTBEAT_ERROR` with session + license junctions |
| `audit.trg_vendors_audit()` *(trigger fn)* | `audit_owner` | INVOKER | `audit_writer`, `audit_reader` | — | AFTER INSERT/UPDATE on `app.vendors`; emits SIGNUP, DELETED, PASSWORD_CHANGED |
| `audit.trg_v_license_node_locked_write()` *(trigger fn)* | `audit_owner` | INVOKER; `search_path` fixed | `audit_writer`, `audit_reader` | ~~`audit_reader`~~ | INSTEAD OF INSERT/UPDATE on `app.v_license_node_locked`; routes to base tables; emits CREATED, DELETED, REVOKED, CONFIG_UPDATED, MODIFIED. Safe as INVOKER: only `app_writer` holds INSERT/UPDATE on the view. |
| `audit.trg_v_license_node_locked_delete()` *(trigger fn)* | `audit_owner` | INVOKER; `search_path` fixed | `audit_writer`, `audit_reader` | ~~`audit_reader`~~ | INSTEAD OF DELETE on `app.v_license_node_locked`; deletes extension→base; emits DELETED. Safe as INVOKER: only `app_deleter` holds DELETE on the view. |
| `audit.trg_sessions_audit()` *(trigger fn)* | `audit_owner` | INVOKER | `audit_writer`, `audit_reader` | — | AFTER INSERT/UPDATE on `app.sessions`; emits ACTIVATED, CLEANED, REVOKED, MODIFIED, TOKEN_ROTATED |

## 4) RLS and Policy Coverage (What Is Enforced)

### 4.1 App Schema RLS

Each table has 4 policies covering all DML: `SELECT` (`USING`), `INSERT` (`WITH CHECK`), `UPDATE` (`USING` + `WITH CHECK`), `DELETE` (`USING`). The Isolation Strategy column describes the `vendor_id` condition used in all four.

**Note: `app.vendors` is intentionally excluded from RLS** to avoid a bootstrap deadlock. The `vendor_id` context variable (set via `app.set_app_context()` after authentication) is derived by querying `app.vendors`. If RLS were enabled on `app.vendors`, that query would itself require `vendor_id` to be already set, creating an impossible circular dependency. See [migrations/06_rls.sql](06_rls.sql) for the implementation of RLS on tenant-scoped tables.

| Table | Policies | Isolation Strategy |
|---|---:|---|
| `app.licenses` | 4 (SELECT, INSERT, UPDATE, DELETE) | Direct `vendor_id = current_setting('app.vendor_id', true)::UUID` |
| `app.node_locked_license_data` | 4 (SELECT, INSERT, UPDATE, DELETE) | `license_id` membership through vendor-owned `app.licenses` |
| `app.sessions` | 4 (SELECT, INSERT, UPDATE, DELETE) | `license_id` membership through `sessions → licenses → vendor_id` |
| `app.heartbeats` | 4 (SELECT, INSERT, UPDATE, DELETE) | `session_id` membership through `heartbeats → sessions → licenses → vendor_id` |

### 4.2 Audit Schema RLS

| Table | Policies | Isolation Strategy |
|---|---:|---|
| `audit.audit_logs` | 2 | Insert allowed to `audit_writer`; select only if vendor is in `audit_log_vendor_actors` |
| `audit.audit_log_vendor_actors` | 2 | Insert allowed to `audit_writer`; select direct vendor equality |
| `audit.audit_log_licenses` | 2 | Insert allowed to `audit_writer`; select delegated via `app.licenses` RLS |
| `audit.audit_log_sessions` | 2 | Insert allowed to `audit_writer`; select delegated via `app.sessions` RLS |

## 5) Object Trees

### 5.1 Schema Object Tree

```text
reference
├── tables
│   ├── license_statuses
│   ├── session_statuses
│   ├── heartbeat_resp_statuses
│   ├── error_codes
│   └── actions
└── used by FK in app and audit schemas

app
├── tables
│   ├── vendors
│   ├── licenses -> FK vendor_id -> app.vendors
│   ├── node_locked_license_data -> FK license_id -> app.licenses
│   ├── sessions -> FK license_id -> app.licenses
│   └── heartbeats (partitioned) -> FK session_id -> app.sessions
├── partitions
│   ├── heartbeats_2026_q1
│   ├── heartbeats_2026_q2
│   ├── heartbeats_2026_q3
│   ├── heartbeats_2026_q4
│   ├── heartbeats_2027_q1
│   └── heartbeats_default
├── view
│   └── v_license_node_locked (write interface)
└── indexes
    ├── vendors_email_lower_idx
    ├── heartbeats_session_id_idx
    └── heartbeats_heartbeat_at_idx (BRIN)

audit
├── tables
│   ├── audit_logs
│   ├── audit_log_vendor_actors
│   ├── audit_log_licenses
│   └── audit_log_sessions
├── indexes
│   ├── audit_log_vendor_actors_vendor_id_idx
│   ├── audit_log_licenses_license_id_idx
│   └── audit_log_sessions_session_id_idx
├── immutability
│   ├── function: prevent_audit_update_delete() [SECURITY DEFINER]
│   └── triggers on all 4 audit tables
└── logging functions and trigger functions
```

### 5.2 Security Call Chain Tree

```text
Application transaction
└── app.set_app_context(vendor_id, ip, user_agent)
    ├── sets app.vendor_id (RLS selector)
    ├── sets app.ip_address
    └── sets app.user_agent

Write paths
├── app.v_license_node_locked (INSERT/UPDATE/DELETE)
│   ├── INSTEAD OF trigger -> audit.trg_v_license_node_locked_write/delete [SECURITY INVOKER; search_path fixed]
│   ├── mutates app.licenses + app.node_locked_license_data
│   └── calls audit._insert_log(...) [SECURITY DEFINER owner=audit_owner]
│       └── inserts audit.audit_logs + optional junction rows
├── app.vendors (INSERT/UPDATE)
│   └── AFTER trigger -> audit.trg_vendors_audit() -> audit._insert_log(...)
└── app.sessions (INSERT/UPDATE)
    └── AFTER trigger -> audit.trg_sessions_audit() -> audit._insert_log(...)

Explicit-call audit paths
├── audit.log_login_success(vendor_id) -> audit._insert_log(...)
├── audit.log_login_failed(vendor_id?) -> audit._insert_log(...)
├── audit.log_token_refreshed(vendor_id) -> audit._insert_log(...)
└── audit.log_heartbeat_error(session_id, license_id, error_code)
    -> audit._insert_log(...)

Read paths
├── app_reader_rls/app_writer/app_deleter/audit_writer/audit_reader: subject to RLS
└── app_reader_bypass: bypasses RLS via role attribute BYPASSRLS
```

## 6) Object-by-Object Quick Map (What It Does + What It Needs + Who Owns It)

| Object | Owner | Type | Purpose | Needs / Depends On | Security Notes |
|---|---|---|---|---|---|
| `reference.*` lookup tables | `reference_owner` | table set | Canonical enums/FK codes | schemas + roles (01) | Read-only after seed; FK targets for app/audit |
| `app.vendors` | `app_owner` | table | Multi-tenant root identity | schemas + roles (01) | Excluded from RLS — bootstrap source for vendor_id propagated downstream |
| `app.licenses` | `app_owner` | table | Core license state | `app.vendors`, `reference.license_statuses` | RLS direct on `vendor_id`; write via view only |
| `app.node_locked_license_data` | `app_owner` | table | Node-locked license extension | `app.licenses` | RLS via parent license; write via view only |
| `app.sessions` | `app_owner` | table | Activation and session lifecycle | `app.licenses`, `reference.session_statuses` | RLS via parent license |
| `app.heartbeats` (+ partitions) | `app_owner` | partitioned table | Append-only heartbeat time-series | `app.sessions`, lookup FKs | RLS via sessions/licenses; no triggers (is the trail) |
| `app.v_license_node_locked` | `app_owner` | view | Mandatory write interface for node-locked licenses | `app.licenses`, `app.node_locked_license_data` | Audited and routed by INSTEAD OF triggers |
| `audit.audit_logs` | `audit_owner` | table | Core immutable audit event record | `reference.actions` | RLS: select only if vendor in actor junction; immutability trigger |
| `audit.audit_log_vendor_actors` | `audit_owner` | table | Actor (vendor) junction | `audit.audit_logs`, `app.vendors` | Drives audit row visibility via RLS |
| `audit.audit_log_licenses` | `audit_owner` | table | License resource junction | `audit.audit_logs`, `app.licenses` | Visibility delegated via `app.licenses` RLS |
| `audit.audit_log_sessions` | `audit_owner` | table | Session resource junction | `audit.audit_logs`, `app.sessions` | Visibility delegated via `app.sessions` RLS |
| `audit.prevent_audit_update_delete()` | `audit_owner` | function | Immutability guard | 4 audit tables | SECURITY DEFINER; see §3.3 |
| `audit._insert_log(...)` | `audit_owner` | function | Central audit row writer | audit tables + tx context | SECURITY DEFINER; body INSERT-only; see §3.3 |
| `audit.log_*()` wrappers | `audit_owner` | function set | Explicit-call audit events | `audit._insert_log` | INVOKER; fixed action codes; see §3.3 |
| `audit.trg_vendors_audit()` | `audit_owner` | trigger fn | Auto-audit vendor mutations | `app.vendors`, `audit._insert_log` | INVOKER; see §3.3 |
| `audit.trg_v_license_node_locked_write()` | `audit_owner` | trigger fn | Write routing + audit for view | base tables, `audit._insert_log` | SECURITY INVOKER; see §3.3 |
| `audit.trg_v_license_node_locked_delete()` | `audit_owner` | trigger fn | Delete routing + audit for view | base tables, `audit._insert_log` | SECURITY INVOKER; see §3.3 |
| `audit.trg_sessions_audit()` | `audit_owner` | trigger fn | Auto-audit session mutations | `app.sessions`, `audit._insert_log` | INVOKER; see §3.3 |

## 7) Notes on Explicit vs Derived Access

- Explicit privileges are taken from `GRANT`, `REVOKE`, and `ALTER DEFAULT PRIVILEGES` only.
- Derived capabilities arise from ownership and `SECURITY DEFINER` execution context.
- `NOINHERIT` means login roles must `SET ROLE` (or have role preset) before privileges activate.
- `BYPASSRLS` appears only on `app_reader_bypass`.
- `app.v_license_node_locked` (view) inherits `SELECT`, `INSERT`, `UPDATE`, `DELETE`, `REFERENCES` privileges via `ALTER DEFAULT PRIVILEGES FOR ROLE app_owner IN SCHEMA app`; no separate per-object `GRANT` targets the view. Actual write routing is handled by the INSTEAD OF trigger functions.
