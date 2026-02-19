# Permit LaaS Backend: Scaffold & Architecture Details

This document provides a comprehensive map of the backend project structure, the purpose of each file, and the architectural decisions driving the layout.

## 1. Project Directory Tree

```text
backend/
├── app/
│   ├── api/                   # API Layer (Routers & Dependencies)
│   │   ├── routes/            # Individual route modules
│   │   │   ├── health.py      # System health check
│   │   │   └── login.py       # Authentication handlers
│   │   ├── deps.py            # FastAPI dependency injections (DB, Auth)
│   │   └── main.py            # Central API router aggregator
│   ├── core/                  # Core System Logic
│   │   ├── config.py          # Settings & Env configuration
│   │   ├── db.py              # Raw SQL / Psycopg connection management
│   │   └── security.py        # Hashing (Argon2/Bcrypt) & JWT logic
│   ├── crud/                  # Raw SQL implementation logic (Data Access)
│   ├── models/                # SQL Query constants & Data structures
│   ├── schemas/               # Pydantic models (IO Validation Contract)
│   ├── services/              # Business logic & Orchestration
│   ├── internal/              # Internal utilities & admin scripts
│   ├── logging.py             # Logging configuration
│   ├── main.py                # FastAPI application entry point
│   └── pre_start.py           # Connectivity verification script
├── Dockerfile                 # Production container definition
├── pyproject.toml             # Python dependencies (uv/hatchling)
└── .env.example               # Template for environment variables
```

---

## 2. Component Explanations

### 🟢 API Layer (`app/api/`)

Handles the communication between the client and the server.
- **`routes/`**: Each file here focuses on a specific resource or domain (e.g., `health` for monitoring).
- **`deps.py`**: Centralizes dependencies. For this project, it is primarily used to inject **Psycopg cursors** into routes, ensuring every request has a clean database connection.
- **`main.py`**: Mounts all sub-routers with appropriate prefixes and tags.

### 🔵 Core Infrastructure (`app/core/`)

The foundational logic that powers the framework.
- **`config.py`**: Uses `pydantic-settings` to load environment variables. It enforces validation, ensuring the app won't start if critical credentials (like `POSTGRES_PASSWORD`) are missing.
- **`db.py`**: Manages the connection to PostgreSQL. Since we are using **Raw SQL**, this file orchestrates the `psycopg` connection pool.
- **`security.py`**: Implements specialized hashing using **Argon2** (primary) and **Bcrypt** (secondary). It also manages JWT encoding/decoding.

### 🟠 Data & Logic Layers

- **`crud/`**: Contains Python functions that execute **Raw SQL** queries. This keeps SQL strings out of the API routes.
- **`models/`**: Stores raw SQL table definitions or specific data structures used internally.
- **`schemas/`**: Defines the "Public Contract". These Pydantic models ensure that incoming JSON matches our expectations and outgoing JSON is filtered correctly.
- **`services/`**: The "Brain" of the app. If a task requires multiple database calls, external API hits, or complex math (like device fingerprinting), it happens here.

### 🔴 Operational Scripts

- **`main.py` (root)**: The object that `fastapi run` or `uvicorn` targets. It configures middleware and global settings.
- **`pre_start.py`**: Runs before the app starts (usually in Docker). It retries connection to the database to ensure the system is "Ready" to handle traffic.

---

## 3. Key Design Decisions

### Raw SQL vs. ORM

To ensure maximum performance and complete control over the PostgreSQL execution plan, this project uses **Raw SQL via Psycopg**. This avoids the overhead of SQLAlchemy/SQLModel and allows for direct usage of advanced PostgreSQL features like Row-Level Security (RLS) and complex joins.

### Security First

By default, the scaffold mandates the use of **Argon2** for password hashing, providing superior resistance against hardware-accelerated cracking compared to older algorithms.

### Statelessness

Communication is handled via short-lived JWTs, allowing the API to scale horizontally without needing sticky sessions or server-side session storage.
