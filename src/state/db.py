"""SQLite connection management for meetscribe state tracking."""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def _resolve_path() -> Path:
    override = os.environ.get("MEETSCRIBE_DB_PATH")
    if override:
        return Path(override)
    return Path("~/.local/share/meetscribe/state.db").expanduser()


DB_PATH = _resolve_path()


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open a SQLite connection, configure WAL mode and foreign keys.

    Auto-creates the parent directory if missing.
    """
    target = path if path is not None else _resolve_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def connection(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Context manager: commits on clean exit, rolls back on exception."""
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
