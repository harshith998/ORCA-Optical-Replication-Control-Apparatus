"""
SQLite database for storing chamber and sensor history.
"""

import datetime
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import List, Dict, Optional, Any

DB_PATH = "chamber_data.db"


# ---------------------------------------------------------------------------
# Timestamp sync
# ---------------------------------------------------------------------------

class TimestampSync:
    """Provides best-effort Unix timestamps with progressive sync.

    Priority order:
    1. NTP-synced system clock (detected by year >= 2024 at startup).
    2. GPS time (applied as an offset when the first valid packet arrives).
    3. Fallback: time.time() as-is (Pi's unsync'd clock, increments naturally).

    If GPS or NTP sync arrives after the fallback has been used, timestamps
    jump forward to the correct time. This discontinuity is intentional and
    documented. See CLAUDE.md § Timestamp Sync Quirk.
    """

    def __init__(self):
        self._offset = 0.0
        self._synced = False

    def init(self, last_db_timestamp: Optional[float] = None):
        """Call once at startup after the DB is open."""
        if datetime.datetime.now().year >= 2024:
            self._synced = True
            self._offset = 0.0
        elif last_db_timestamp and last_db_timestamp > 0:
            # Monotonically increment from the last recorded timestamp so
            # the sequence stays consistent until a real sync arrives.
            self._offset = last_db_timestamp - time.time()
        # else: use time.time() as-is (user's preference for empty-DB case)

    def notify_gps(self, gps_unix_time: float):
        """Call when a GPS packet with valid time arrives."""
        if not self._synced and gps_unix_time > 0:
            self._offset = gps_unix_time - time.time()
            self._synced = True

    def now(self) -> float:
        return time.time() + self._offset


ts = TimestampSync()


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

class Database:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._local = threading.local()
        self._init_db()
        last = self.get_latest_state()
        ts.init(last.get('timestamp') if last else None)

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    @contextmanager
    def _cursor(self):
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
        with self._cursor() as cursor:
            # Chamber history — logged every 1 s
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chamber_history (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL    NOT NULL,
                    led_lux   INTEGER NOT NULL,
                    led_mode  INTEGER NOT NULL,
                    s1        INTEGER NOT NULL,
                    s2        INTEGER NOT NULL,
                    s3        INTEGER NOT NULL
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_chamber_timestamp
                ON chamber_history(timestamp)
            """)

            # Sensor history — logged each LoRa / RS-485 packet (~every 10 s)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sensor_history (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp    REAL    NOT NULL,
                    f1           INTEGER,
                    f2           INTEGER,
                    fz           INTEGER,
                    f3           INTEGER,
                    f4           INTEGER,
                    f5           INTEGER,
                    fy           INTEGER,
                    f6           INTEGER,
                    fxl          INTEGER,
                    f7           INTEGER,
                    f8           INTEGER,
                    nir          INTEGER,
                    clear        INTEGER,
                    gps_valid    INTEGER DEFAULT 0,
                    gps_lat      REAL    DEFAULT 0.0,
                    gps_lon      REAL    DEFAULT 0.0,
                    gps_unix_time INTEGER DEFAULT 0,
                    sanity_flag  INTEGER DEFAULT 0
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_sensor_timestamp
                ON sensor_history(timestamp)
            """)

    # -----------------------------------------------------------------------
    # Timestamp sync
    # -----------------------------------------------------------------------

    def notify_gps_time(self, gps_unix_time: float):
        """Notify the timestamp manager that a valid GPS time has arrived."""
        ts.notify_gps(gps_unix_time)

    # -----------------------------------------------------------------------
    # Write
    # -----------------------------------------------------------------------

    def log_chamber(self, led_lux: int, led_mode: int,
                    s1: int, s2: int, s3: int):
        """Log one chamber history row (called every 1 s)."""
        with self._cursor() as cursor:
            cursor.execute("""
                INSERT INTO chamber_history
                    (timestamp, led_lux, led_mode, s1, s2, s3)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (ts.now(), led_lux, led_mode, s1, s2, s3))

    def log_sensor(self, channels: dict, gps: dict, sanity_flag: bool):
        """Log one sensor history row (called on each received packet)."""
        with self._cursor() as cursor:
            cursor.execute("""
                INSERT INTO sensor_history
                    (timestamp, f1, f2, fz, f3, f4, f5, fy, f6, fxl,
                     f7, f8, nir, clear,
                     gps_valid, gps_lat, gps_lon, gps_unix_time, sanity_flag)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?, ?, ?)
            """, (
                ts.now(),
                channels.get('f1', 0), channels.get('f2', 0), channels.get('fz', 0),
                channels.get('f3', 0), channels.get('f4', 0), channels.get('f5', 0),
                channels.get('fy', 0), channels.get('f6', 0), channels.get('fxl', 0),
                channels.get('f7', 0), channels.get('f8', 0), channels.get('nir', 0),
                channels.get('clear', 0),
                int(gps.get('valid', False)),
                gps.get('latitude', 0.0), gps.get('longitude', 0.0),
                gps.get('unix_time', 0),
                int(sanity_flag),
            ))

    # -----------------------------------------------------------------------
    # Read
    # -----------------------------------------------------------------------

    def get_latest_state(self) -> Optional[Dict[str, Any]]:
        """Return the most recent chamber_history row, or None if empty."""
        with self._cursor() as cursor:
            cursor.execute("""
                SELECT * FROM chamber_history ORDER BY timestamp DESC LIMIT 1
            """)
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_chamber_history(self, start_time: Optional[float] = None,
                            end_time: Optional[float] = None,
                            limit: int = 1000,
                            bucket_secs: Optional[float] = None) -> List[Dict[str, Any]]:
        """Return chamber history, optionally time-bucketed for chart display."""
        with self._cursor() as cursor:
            if bucket_secs:
                where_clauses = ["1=1"]
                where_params: list = []
                if start_time:
                    where_clauses.append("timestamp >= ?")
                    where_params.append(start_time)
                if end_time:
                    where_clauses.append("timestamp <= ?")
                    where_params.append(end_time)
                where_str = " AND ".join(where_clauses)
                query = f"""
                    SELECT
                        CAST(timestamp / ? AS INTEGER) * ? AS timestamp,
                        CAST(AVG(led_lux)  AS INTEGER) AS led_lux,
                        CAST(AVG(led_mode) AS INTEGER) AS led_mode,
                        CAST(AVG(s1) AS INTEGER) AS s1,
                        CAST(AVG(s2) AS INTEGER) AS s2,
                        CAST(AVG(s3) AS INTEGER) AS s3
                    FROM chamber_history
                    WHERE {where_str}
                    GROUP BY CAST(timestamp / ? AS INTEGER)
                    ORDER BY timestamp ASC
                """
                params = [bucket_secs, bucket_secs] + where_params + [bucket_secs]
                cursor.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]

            query = "SELECT * FROM chamber_history WHERE 1=1"
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
            return [dict(row) for row in reversed(cursor.fetchall())]

    def get_sensor_history(self, hours: float = 6, limit: int = 500,
                           bucket_secs: Optional[float] = None) -> List[Dict[str, Any]]:
        """Return sensor history for the last N hours, optionally time-bucketed."""
        start_time = time.time() - (hours * 3600)
        with self._cursor() as cursor:
            if bucket_secs:
                cursor.execute("""
                    SELECT
                        CAST(timestamp / ? AS INTEGER) * ? AS timestamp,
                        CAST(AVG(f1)    AS INTEGER) AS f1,
                        CAST(AVG(f2)    AS INTEGER) AS f2,
                        CAST(AVG(fz)    AS INTEGER) AS fz,
                        CAST(AVG(f3)    AS INTEGER) AS f3,
                        CAST(AVG(f4)    AS INTEGER) AS f4,
                        CAST(AVG(f5)    AS INTEGER) AS f5,
                        CAST(AVG(fy)    AS INTEGER) AS fy,
                        CAST(AVG(f6)    AS INTEGER) AS f6,
                        CAST(AVG(fxl)   AS INTEGER) AS fxl,
                        CAST(AVG(f7)    AS INTEGER) AS f7,
                        CAST(AVG(f8)    AS INTEGER) AS f8,
                        CAST(AVG(nir)   AS INTEGER) AS nir,
                        CAST(AVG(clear) AS INTEGER) AS clear
                    FROM sensor_history
                    WHERE timestamp >= ?
                    GROUP BY CAST(timestamp / ? AS INTEGER)
                    ORDER BY timestamp ASC
                """, (bucket_secs, bucket_secs, start_time, bucket_secs))
                return [dict(row) for row in cursor.fetchall()]

            cursor.execute("""
                SELECT * FROM sensor_history
                WHERE timestamp >= ?
                ORDER BY timestamp DESC LIMIT ?
            """, (start_time, limit))
            return [dict(row) for row in reversed(cursor.fetchall())]

    def get_stats(self, hours: int = 24) -> Dict[str, Any]:
        """Return aggregate stats for the last N hours."""
        start_time = time.time() - (hours * 3600)
        with self._cursor() as cursor:
            cursor.execute("""
                SELECT
                    COUNT(*)       AS count,
                    AVG(led_lux)   AS avg_led_lux,
                    MIN(led_lux)   AS min_led_lux,
                    MAX(led_lux)   AS max_led_lux
                FROM chamber_history
                WHERE timestamp >= ?
            """, (start_time,))
            row = cursor.fetchone()
            return dict(row) if row else {}

    def cleanup_old_data(self, max_age_hours: int = 168):
        """Delete data older than max_age_hours (default 7 days)."""
        cutoff = time.time() - (max_age_hours * 3600)
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM chamber_history WHERE timestamp < ?", (cutoff,))
            cursor.execute("DELETE FROM sensor_history  WHERE timestamp < ?", (cutoff,))

    def close(self):
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None


# Global database instance
db = Database()
