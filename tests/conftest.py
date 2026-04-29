"""Pytest fixtures shared across tests."""

import importlib
from pathlib import Path

import pytest


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch) -> Path:
    target = tmp_path / "state.db"
    monkeypatch.setenv("MEETSCRIBE_DB_PATH", str(target))
    from src.state import db
    importlib.reload(db)
    return target


@pytest.fixture
def conn(db_path):
    """Yield a connection to a fresh, migrated state.db."""
    from src.state import db, runner
    with db.connection() as c:
        runner.apply_migrations(c)
    with db.connection() as c:
        yield c
