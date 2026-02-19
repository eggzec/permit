from psycopg_pool import ConnectionPool

from app.core.config import settings

# Stub engine for Issue #1 - Foundation
# In a real implementation, this would be a Psycopg pool object.
pool = ConnectionPool(str(settings.DATABASE_DSN))
