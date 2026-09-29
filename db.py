"""Shared database connection helpers — PostgreSQL (primary) with SQLite fallback."""

import os
import sqlite3

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")

_DB_DIR = os.path.dirname(os.path.abspath(__file__))
_SQLITE_PATH = os.path.join(_DB_DIR, "capstone2.db")

def _check_pg():
    if not DATABASE_URL.startswith("postgresql"):
        return False
    try:
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL, connect_timeout=3)
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        return True
    except Exception:
        return False

IS_PG = _check_pg()
PARAM = "%s" if IS_PG else "?"


class _PGConnectionWrapper:
    """Wraps psycopg2 connection to support conn.execute() like sqlite3."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=None):
        cur = self._conn.cursor()
        cur.execute(sql, params or ())
        return cur

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()

    def cursor(self):
        return self._conn.cursor()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._conn.close()


def get_connection():
    if IS_PG:
        import psycopg2
        return _PGConnectionWrapper(psycopg2.connect(DATABASE_URL))
    return sqlite3.connect(_SQLITE_PATH)


def get_dict_connection():
    if IS_PG:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        return _PGConnectionWrapper(conn)
    conn = sqlite3.connect(_SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


_engine = None

def get_engine():
    global _engine
    if _engine is not None:
        return _engine
    from sqlalchemy import create_engine
    if IS_PG:
        _engine = create_engine(
            DATABASE_URL,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=300,
        )
    else:
        _engine = create_engine(f"sqlite:///{_SQLITE_PATH}")
    return _engine
