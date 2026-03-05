import os


# Environment variables must be set before importing the app
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("PROJECT_NAME", "permit-test")
os.environ.setdefault("POSTGRES_SERVER", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("POSTGRES_DB", "test")
