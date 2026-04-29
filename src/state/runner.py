"""Apply pending SQL migrations from src/state/migrations/."""

import re
import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_NAME_RE = re.compile(r"^(\d{3})_.*\.sql$")


def current_version(conn: sqlite3.Connection) -> int:
    """Return current schema_version, or 0 if table doesn't exist."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchone()
    if row is None:
        return 0
    result = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return result[0] or 0


def _all_migrations() -> list[Path]:
    files = []
    for path in MIGRATIONS_DIR.iterdir():
        m = _NAME_RE.match(path.name)
        if m:
            files.append((int(m.group(1)), path))
    files.sort()
    return [p for _, p in files]


def pending_migrations(conn: sqlite3.Connection) -> list[Path]:
    """Return migration files with version > current_version, in order."""
    version = current_version(conn)
    return [p for p in _all_migrations() if int(_NAME_RE.match(p.name).group(1)) > version]


def apply_migrations(conn: sqlite3.Connection) -> int:
    """Apply pending migrations in order. Each in its own transaction.

    Returns count of migrations applied.
    """
    applied = 0
    for path in pending_migrations(conn):
        sql = path.read_text()
        conn.executescript(sql)
        applied += 1
    return applied
