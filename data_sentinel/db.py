"""Database layer: SQLite by default, PostgreSQL when DATABASE_URL is set.

* Parameterized SQL only (``?`` placeholders, translated to ``%s`` for PostgreSQL).
* Thread-safe: one connection guarded by a re-entrant lock; ``transaction()`` holds the
  lock and a database write lock, so several watcher threads (and other processes such as
  the dashboard) can share it without breaking the audit hash chain.
"""
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import config

TABLES = ["audit_log", "alerts", "risk_assessments", "transfer_events", "files",
          "policies", "devices", "users"]          # drop order (children first)

SEED_USERS = [("alice", "employee"), ("bob", "admin"), ("carol", "contractor")]
SEED_DEVICES = [("corp-laptop", "internal", "trusted"),
                ("Corp-EncryptedUSB", "usb", "trusted"),
                ("SanDisk-USB-01", "usb", "unknown"),
                ("Unknown-USB-77", "usb", "untrusted")]
POLICY_TEXT = {"LOW": "Low risk: allow and log",
               "MEDIUM": "Medium risk: allow, warn the user and log",
               "HIGH": "High risk: block, alert and log",
               "CRITICAL": "Critical risk: block, alert and log"}


def utcnow():
    return datetime.now(timezone.utc)


def ts_str(dt):
    """Fixed-width UTC timestamp so string comparison equals time comparison."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


def parse_ts(s):
    return datetime.fromisoformat(s)


class Database:
    def __init__(self, url=None, sqlite_path=None):
        url = config.DATABASE_URL if url is None else url
        self.pg = bool(url) and url.startswith(("postgres://", "postgresql://"))
        self.lock = threading.RLock()
        self._depth = 0
        if self.pg:
            try:
                import psycopg
                self.conn = psycopg.connect(url, autocommit=True)
            except ImportError:
                import psycopg2
                self.conn = psycopg2.connect(url)
                self.conn.autocommit = True
            self.location = "PostgreSQL"
        else:
            path = str(sqlite_path or config.SQLITE_PATH)
            if path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
            # isolation_level=None: we issue BEGIN IMMEDIATE / COMMIT ourselves.
            self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=30)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA busy_timeout = 30000")
            self.conn.execute("PRAGMA foreign_keys = ON")
            if path != ":memory:":
                self.conn.execute("PRAGMA journal_mode = WAL")
            self.location = path

    # ------------------------------------------------------------------ basics
    def _q(self, sql):
        return sql.replace("?", "%s") if self.pg else sql

    def execute(self, sql, params=()):
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(self._q(sql), tuple(params))
            return cur

    def query(self, sql, params=()):
        with self.lock:
            cur = self.execute(sql, params)
            if cur.description is None:
                return []
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def one(self, sql, params=()):
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def scalar(self, sql, params=()):
        row = self.one(sql, params)
        return next(iter(row.values())) if row else None

    def insert(self, sql, params=()):
        with self.lock:
            if self.pg:
                return self.execute(sql + " RETURNING id", params).fetchone()[0]
            return self.execute(sql, params).lastrowid

    @contextmanager
    def transaction(self):
        """Atomic block. Holds the thread lock and the database write lock."""
        with self.lock:
            outer = self._depth == 0
            if outer:
                if self.pg:
                    self.execute("BEGIN")
                    self.execute("SELECT pg_advisory_xact_lock(4242)")
                else:
                    self.execute("BEGIN IMMEDIATE")
            self._depth += 1
            try:
                yield self
            except BaseException:
                self._depth -= 1
                if outer:
                    self.execute("ROLLBACK")
                raise
            self._depth -= 1
            if outer:
                self.execute("COMMIT")

    def close(self):
        with self.lock:
            self.conn.close()

    # ------------------------------------------------------------------ schema
    def init_schema(self, seed=True):
        pk = "SERIAL PRIMARY KEY" if self.pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
        stmts = [
            f"CREATE TABLE IF NOT EXISTS users (id {pk}, name TEXT UNIQUE NOT NULL, "
            "role TEXT NOT NULL, created_at TEXT)",
            f"CREATE TABLE IF NOT EXISTS devices (id {pk}, name TEXT UNIQUE NOT NULL, "
            "device_type TEXT NOT NULL, trust_status TEXT NOT NULL, created_at TEXT)",
            f"CREATE TABLE IF NOT EXISTS files (id {pk}, name TEXT NOT NULL, path TEXT, sha256 TEXT, "
            "size_bytes BIGINT, sensitivity TEXT, sensitivity_level INTEGER, matches TEXT, inspected INTEGER)",
            f"CREATE TABLE IF NOT EXISTS transfer_events (id {pk}, ts TEXT NOT NULL, "
            "user_id INTEGER REFERENCES users(id), device_id INTEGER REFERENCES devices(id), "
            "file_id INTEGER REFERENCES files(id), channel TEXT, dest_type TEXT, decision TEXT, "
            "action_taken TEXT, dry_run INTEGER DEFAULT 0)",
            f"CREATE TABLE IF NOT EXISTS risk_assessments (id {pk}, "
            "event_id INTEGER REFERENCES transfer_events(id), score REAL, level TEXT, "
            "reasons TEXT, features TEXT, signals TEXT)",
            f"CREATE TABLE IF NOT EXISTS alerts (id {pk}, event_id INTEGER REFERENCES transfer_events(id), "
            "severity TEXT, status TEXT, created_at TEXT, message TEXT, resolved_at TEXT, resolved_by TEXT)",
            f"CREATE TABLE IF NOT EXISTS policies (id {pk}, level TEXT UNIQUE NOT NULL, "
            "action TEXT NOT NULL, description TEXT)",
            f"CREATE TABLE IF NOT EXISTS audit_log (id {pk}, ts TEXT, event_id INTEGER, "
            "record TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL)",
            "CREATE INDEX IF NOT EXISTS ix_events_user_ts ON transfer_events (user_id, ts)",
            "CREATE INDEX IF NOT EXISTS ix_events_decision ON transfer_events (decision)",
        ]
        with self.transaction():
            for s in stmts:
                self.execute(s)
            self._append_only_guard()
            for level, action in config.DEFAULT_POLICY.items():
                if not self.one("SELECT id FROM policies WHERE level = ?", (level,)):
                    self.insert("INSERT INTO policies (level, action, description) VALUES (?, ?, ?)",
                                (level, action, POLICY_TEXT[level]))
            if seed:
                for name, role in SEED_USERS:
                    self.get_user(name, role)
                for name, dtype, trust in SEED_DEVICES:
                    self.get_device(name, dtype, trust)

    def _append_only_guard(self):
        """Refuse UPDATE/DELETE on audit_log at the database level."""
        if self.pg:
            self.execute("CREATE OR REPLACE FUNCTION audit_append_only() RETURNS trigger AS $$ "
                         "BEGIN RAISE EXCEPTION 'audit_log is append-only'; END; $$ LANGUAGE plpgsql")
            if not self.one("SELECT 1 AS x FROM pg_trigger WHERE tgname = 'audit_no_change'"):
                self.execute("CREATE TRIGGER audit_no_change BEFORE UPDATE OR DELETE ON audit_log "
                             "FOR EACH ROW EXECUTE FUNCTION audit_append_only()")
        else:
            for op in ("UPDATE", "DELETE"):
                self.execute(f"CREATE TRIGGER IF NOT EXISTS audit_no_{op.lower()} BEFORE {op} ON audit_log "
                             "BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END")

    def reset(self):
        """Drop every table and recreate the schema with seed data (used by simulate / demo)."""
        with self.transaction():
            for t in TABLES:
                self.execute(f"DROP TABLE IF EXISTS {t}" + (" CASCADE" if self.pg else ""))
        self.init_schema(seed=True)

    def event_count(self):
        try:
            return self.scalar("SELECT COUNT(*) AS n FROM transfer_events") or 0
        except Exception:
            return 0

    # ------------------------------------------------------------------ entities
    def get_user(self, name, role="employee"):
        row = self.one("SELECT * FROM users WHERE name = ?", (name,))
        if row:
            return row
        with self.transaction():
            uid = self.insert("INSERT INTO users (name, role, created_at) VALUES (?, ?, ?)",
                              (name, role, ts_str(utcnow())))
        return {"id": uid, "name": name, "role": role}

    def get_device(self, name, device_type="usb", trust="unknown"):
        row = self.one("SELECT * FROM devices WHERE name = ?", (name,))
        if row:
            return row
        with self.transaction():
            did = self.insert("INSERT INTO devices (name, device_type, trust_status, created_at) "
                              "VALUES (?, ?, ?, ?)", (name, device_type, trust, ts_str(utcnow())))
        return {"id": did, "name": name, "device_type": device_type, "trust_status": trust}

    def upsert_user(self, name, role):
        with self.transaction():
            if self.one("SELECT id FROM users WHERE name = ?", (name,)):
                self.execute("UPDATE users SET role = ? WHERE name = ?", (role, name))
            else:
                self.get_user(name, role)
        return self.one("SELECT * FROM users WHERE name = ?", (name,))

    def upsert_device(self, name, device_type, trust):
        with self.transaction():
            if self.one("SELECT id FROM devices WHERE name = ?", (name,)):
                self.execute("UPDATE devices SET device_type = ?, trust_status = ? WHERE name = ?",
                             (device_type, trust, name))
            else:
                self.get_device(name, device_type, trust)
        return self.one("SELECT * FROM devices WHERE name = ?", (name,))

    def policy_action(self, level):
        row = self.one("SELECT action FROM policies WHERE level = ?", (level,))
        return row["action"] if row else config.DEFAULT_POLICY[level]

    def resolve_alert(self, alert_id, who="dashboard"):
        with self.transaction():
            self.execute("UPDATE alerts SET status = 'RESOLVED', resolved_at = ?, resolved_by = ? "
                         "WHERE id = ? AND status = 'OPEN'", (ts_str(utcnow()), who, alert_id))
