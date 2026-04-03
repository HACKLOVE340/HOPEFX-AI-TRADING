# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Database Connection Management
- Connection pooling
- Query execution
- Transaction handling
- Migration support
"""

import logging
import re
import sqlite3
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)

# Allowlist pattern for SQL identifiers (table/column names).
# Only alphanumeric characters and underscores are permitted.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_identifier(name: str, label: str = "identifier") -> str:
    """Raise ValueError if *name* is not a safe SQL identifier."""
    if not _IDENTIFIER_RE.match(name):
        raise ValueError(f"Unsafe SQL {label} {name!r}: only [A-Za-z0-9_] characters are allowed")
    return name


class DatabasePool:
    """Database connection pool manager"""

    def __init__(self, db_path: str, max_connections: int = 5):
        """
        Initialize connection pool

        Args:
            db_path: Path to database file
            max_connections: Maximum connections in pool
        """
        self.db_path = db_path
        self.max_connections = max_connections
        self.connections: list[sqlite3.Connection] = []
        self._initialize_pool()

    def _initialize_pool(self):
        """Initialize connection pool"""
        for _ in range(self.max_connections):
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self.connections.append(conn)

    @contextmanager
    def get_connection(self):
        """Get connection from pool"""
        if not self.connections:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
        else:
            conn = self.connections.pop()

        try:
            yield conn
        finally:
            self.connections.append(conn)

    def close_all(self):
        """Close all connections"""
        for conn in self.connections:
            conn.close()
        self.connections = []


class Database:
    """Database operations wrapper"""

    def __init__(self, db_path: str = "hopefx.db"):
        self.pool = DatabasePool(db_path)

    def execute(self, query: str, params: tuple = ()) -> list[dict] | None:
        """Execute query and return results"""
        try:
            with self.pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)

                if query.strip().upper().startswith("SELECT"):
                    return [dict(row) for row in cursor.fetchall()]
                conn.commit()
                return None

        except Exception as e:
            logger.error("Database error: %s", e)

            return None

    def insert(self, table: str, data: dict[str, Any]) -> bool:
        """Insert record"""
        _validate_identifier(table, "table name")
        for col in data:
            _validate_identifier(col, "column name")
        columns = ", ".join(data.keys())
        placeholders = ", ".join(["?" for _ in data])
        query = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"  # nosec B608 - identifiers validated above

        try:
            with self.pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, tuple(data.values()))
                conn.commit()
                return True
        except Exception as e:
            logger.error("Insert error: %s", e)

            return False

    def update(self, table: str, data: dict[str, Any], where: str) -> bool:
        """Update records.

        *where* must be a plain column = ? expression; callers are responsible
        for ensuring it contains no user-supplied data.
        """
        _validate_identifier(table, "table name")
        for col in data:
            _validate_identifier(col, "column name")
        updates = ", ".join([f"{k} = ?" for k in data])
        query = f"UPDATE {table} SET {updates} WHERE {where}"  # nosec B608 - table/column identifiers validated; where is caller-controlled

        try:
            with self.pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, tuple(data.values()))
                conn.commit()
                return True
        except Exception as e:
            logger.error("Update error: %s", e)

            return False

    def delete(self, table: str, where: str) -> bool:
        """Delete records.

        *where* must be a plain column = ? expression; callers are responsible
        for ensuring it contains no user-supplied data.
        """
        _validate_identifier(table, "table name")
        query = f"DELETE FROM {table} WHERE {where}"  # nosec B608 - table identifier validated; where is caller-controlled

        try:
            with self.pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                conn.commit()
                return True
        except Exception as e:
            logger.error("Delete error: %s", e)

            return False

    def create_table(self, table: str, schema: str) -> bool:
        """Create table"""
        query = f"CREATE TABLE IF NOT EXISTS {table} ({schema})"

        try:
            with self.pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                conn.commit()
                return True
        except Exception as e:
            logger.error("Create table error: %s", e)

            return False

    def close(self):
        """Close database pool"""
        self.pool.close_all()
