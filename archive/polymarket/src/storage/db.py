"""Database connection and initialization."""
import sqlite3
from pathlib import Path
from typing import Optional
from contextlib import contextmanager

from ..config import DB_FULL_PATH, PROJECT_ROOT


class Database:
    """SQLite database manager."""
    
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_FULL_PATH
        self._initialized = False
    
    @contextmanager
    def get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def initialize(self):
        """Initialize database schema from schema.sql."""
        if self._initialized:
            return
        
        schema_path = PROJECT_ROOT / "sql" / "schema.sql"
        
        if not schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_path}")
        
        with open(schema_path, 'r') as f:
            schema_sql = f.read()
        
        with self.get_connection() as conn:
            conn.executescript(schema_sql)
        
        self._initialized = True
        print(f"✓ Database initialized: {self.db_path}")
    
    def execute(self, query: str, params: tuple = ()):
        """Execute a single query."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchall()
    
    def execute_many(self, query: str, params_list: list):
        """Execute a query with multiple parameter sets."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(query, params_list)
            return cursor.rowcount


# Global database instance
db = Database()
