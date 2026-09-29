"""Login rate limiting that survives a restart and works across replicas.

Both dashboards previously kept failed attempts in a module-level dict. That
has two holes worth closing before hosting: the counter resets every time the
process restarts, and with more than one replica behind a load balancer an
attacker simply alternates between them to get N attempts per replica.

State lives in the database instead. If the database refuses the table — the
same fallback `my_desk` uses for its own state — the in-process dict is used
so a local run without Postgres still works. The backend in force is
reported by `backend()` so the limitation is visible rather than assumed.
"""

import time

from config import LOCKOUT_SECONDS, MAX_LOGIN_ATTEMPTS
from db import PARAM, get_connection

_DDL = """
CREATE TABLE IF NOT EXISTS login_attempts (
    email        TEXT PRIMARY KEY,
    attempts     INTEGER NOT NULL DEFAULT 0,
    locked_until DOUBLE PRECISION,
    updated_at   DOUBLE PRECISION
)
"""
_DDL_SQLITE = _DDL.replace("DOUBLE PRECISION", "REAL")

_memory = {}
_backend = None


def backend():
    """'db' once the table is usable, otherwise 'memory'. Probed once."""
    global _backend
    if _backend is not None:
        return _backend
    try:
        from db import IS_PG
        conn = get_connection()
        conn.execute(_DDL if IS_PG else _DDL_SQLITE)
        conn.commit()
        conn.close()
        _backend = "db"
    except Exception:
        _backend = "memory"
    return _backend


def _read(email):
    if backend() == "memory":
        return _memory.get(email, (0, None))
    try:
        conn = get_connection()
        row = conn.execute(
            f"SELECT attempts, locked_until FROM login_attempts WHERE email={PARAM}",
            (email,)).fetchone()
        conn.close()
        return (row[0], row[1]) if row else (0, None)
    except Exception:
        return _memory.get(email, (0, None))


def _write(email, attempts, locked_until):
    if backend() == "memory":
        _memory[email] = (attempts, locked_until)
        return
    now = time.time()
    try:
        conn = get_connection()
        # No ON CONFLICT: SQLite and Postgres spell the upsert differently and
        # a delete-then-insert is correct on both for a single-row key.
        conn.execute(f"DELETE FROM login_attempts WHERE email={PARAM}", (email,))
        conn.execute(
            f"INSERT INTO login_attempts (email, attempts, locked_until, updated_at) "
            f"VALUES ({PARAM}, {PARAM}, {PARAM}, {PARAM})",
            (email, attempts, locked_until, now))
        conn.commit()
        conn.close()
    except Exception:
        _memory[email] = (attempts, locked_until)


def check(email):
    """Return a message if this address is locked out, else None."""
    attempts, locked_until = _read(email)
    if not locked_until:
        return None
    now = time.time()
    if now < locked_until:
        remaining = int(locked_until - now)
        return (f"Too many failed attempts. Try again in "
                f"{remaining // 60}m {remaining % 60}s.")
    clear(email)
    return None


def record_failure(email):
    attempts, _ = _read(email)
    attempts += 1
    locked_until = (time.time() + LOCKOUT_SECONDS
                    if attempts >= MAX_LOGIN_ATTEMPTS else None)
    _write(email, attempts, locked_until)


def clear(email):
    if backend() == "memory":
        _memory.pop(email, None)
        return
    try:
        conn = get_connection()
        conn.execute(f"DELETE FROM login_attempts WHERE email={PARAM}", (email,))
        conn.commit()
        conn.close()
    except Exception:
        _memory.pop(email, None)
