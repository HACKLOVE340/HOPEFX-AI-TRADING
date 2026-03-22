"""
Database Connection Management
- Connection pooling
- Query execution
- Transaction handling
- Migration support
"""

import sqlite3
from typing import List, Dict, Optional, Any
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)

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
        self.connections: List[sqlite3.Connection] = []
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
    
    def execute(self, query: str, params: tuple = ()) -> Optional[List[Dict]]:
        """Execute query and return results"""
        try:
            with self.pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                
                if query.strip().upper().startswith('SELECT'):
                    return [dict(row) for row in cursor.fetchall()]
                else:
                    conn.commit()
                    return None
        
        except Exception as e:
            logger.error(f"Database error: {e}")
            return None
    
    def insert(self, table: str, data: Dict[str, Any]) -> bool:
        """Insert record"""
        columns = ', '.join(data.keys())
        placeholders = ', '.join(['?' for _ in data])
        query = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
        
        try:
            with self.pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, tuple(data.values()))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Insert error: {e}")
            return False
    
    def update(self, table: str, data: Dict[str, Any], where: str) -> bool:
        """Update records"""
        updates = ', '.join([f"{k} = ?" for k in data.keys()])
        query = f"UPDATE {table} SET {updates} WHERE {where}"
        
        try:
            with self.pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, tuple(data.values()))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Update error: {e}")
            return False
    
    def delete(self, table: str, where: str) -> bool:
        """Delete records"""
        query = f"DELETE FROM {table} WHERE {where}"
        
        try:
            with self.pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Delete error: {e}")
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
            logger.error(f"Create table error: {e}")
            return False
    
    def close(self):
        """Close database pool"""
        self.pool.close_all()