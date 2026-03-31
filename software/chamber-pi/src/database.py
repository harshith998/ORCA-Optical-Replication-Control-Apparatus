"""
SQLite database for storing lux history and system state.
"""

import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import List, Dict, Optional, Any

DB_PATH = "chamber_data.db"


class Database:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    @contextmanager
    def _cursor(self):
        """Context manager for database cursor."""
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()

    def _init_db(self):
        """Initialize database tables."""
        with self._cursor() as cursor:
            # Lux history table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS lux_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    raw_lux INTEGER NOT NULL,
                    clamped_lux INTEGER NOT NULL,
                    pwm_value INTEGER NOT NULL,
                    mode TEXT NOT NULL,
                    bounds_min INTEGER,
                    bounds_max INTEGER
                )
            """)

            # Create index for faster time-based queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_lux_timestamp
                ON lux_history(timestamp)
            """)

            # System state table (single row)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS system_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    web_manual_enabled INTEGER DEFAULT 0,
                    web_manual_pwm INTEGER DEFAULT 0,
                    updated_at REAL
                )
            """)

            # Initialize system state if not exists
            cursor.execute("""
                INSERT OR IGNORE INTO system_state (id, web_manual_enabled, web_manual_pwm, updated_at)
                VALUES (1, 0, 0, ?)
            """, (time.time(),))

    def log_reading(self, raw_lux: int, clamped_lux: int, pwm_value: int,
                    mode: str, bounds_min: int, bounds_max: int):
        """Log a lux reading to history."""
        with self._cursor() as cursor:
            cursor.execute("""
                INSERT INTO lux_history
                (timestamp, raw_lux, clamped_lux, pwm_value, mode, bounds_min, bounds_max)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (time.time(), raw_lux, clamped_lux, pwm_value, mode, bounds_min, bounds_max))

    def get_history(self, start_time: Optional[float] = None,
                    end_time: Optional[float] = None,
                    limit: int = 1000) -> List[Dict[str, Any]]:
        """Get lux history within time range."""
        with self._cursor() as cursor:
            query = "SELECT * FROM lux_history WHERE 1=1"
            params = []

            if start_time:
                query += " AND timestamp >= ?"
                params.append(start_time)
            if end_time:
                query += " AND timestamp <= ?"
                params.append(end_time)

            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            rows = cursor.fetchall()

            return [dict(row) for row in reversed(rows)]

    def get_latest_reading(self) -> Optional[Dict[str, Any]]:
        """Get the most recent reading."""
        with self._cursor() as cursor:
            cursor.execute("""
                SELECT * FROM lux_history
                ORDER BY timestamp DESC LIMIT 1
            """)
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_web_control_state(self) -> Dict[str, Any]:
        """Get web manual control state."""
        with self._cursor() as cursor:
            cursor.execute("SELECT * FROM system_state WHERE id = 1")
            row = cursor.fetchone()
            if row:
                return {
                    'web_manual_enabled': bool(row['web_manual_enabled']),
                    'web_manual_pwm': row['web_manual_pwm'],
                    'updated_at': row['updated_at']
                }
            return {'web_manual_enabled': False, 'web_manual_pwm': 0, 'updated_at': None}

    def set_web_control_state(self, enabled: bool, pwm_value: int):
        """Set web manual control state."""
        with self._cursor() as cursor:
            cursor.execute("""
                UPDATE system_state
                SET web_manual_enabled = ?, web_manual_pwm = ?, updated_at = ?
                WHERE id = 1
            """, (int(enabled), pwm_value, time.time()))

    def cleanup_old_data(self, max_age_hours: int = 168):
        """Delete data older than max_age_hours (default 7 days)."""
        cutoff = time.time() - (max_age_hours * 3600)
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM lux_history WHERE timestamp < ?", (cutoff,))
            return cursor.rowcount

    def get_stats(self, hours: int = 24) -> Dict[str, Any]:
        """Get statistics for the last N hours."""
        start_time = time.time() - (hours * 3600)
        with self._cursor() as cursor:
            cursor.execute("""
                SELECT
                    COUNT(*) as count,
                    AVG(raw_lux) as avg_lux,
                    MIN(raw_lux) as min_lux,
                    MAX(raw_lux) as max_lux,
                    AVG(pwm_value) as avg_pwm
                FROM lux_history
                WHERE timestamp >= ?
            """, (start_time,))
            row = cursor.fetchone()
            return dict(row) if row else {}

    def close(self):
        """Close database connection."""
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None


# Global database instance
db = Database()