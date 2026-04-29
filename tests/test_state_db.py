"""Tests for src.state.db connection management."""

import sqlite3
from pathlib import Path

import pytest

from src.state import db


class TestDbPath:
    def test_default_path_is_xdg_data_home(self, monkeypatch):
        monkeypatch.delenv("MEETSCRIBE_DB_PATH", raising=False)
        import importlib
        importlib.reload(db)
        assert str(db.DB_PATH).endswith(".local/share/meetscribe/state.db")

    def test_path_overridable_via_env(self, monkeypatch, tmp_path):
        target = tmp_path / "custom.db"
        monkeypatch.setenv("MEETSCRIBE_DB_PATH", str(target))
        import importlib
        importlib.reload(db)
        assert db.DB_PATH == target


class TestConnect:
    def test_connect_creates_parent_directory(self, tmp_path, monkeypatch):
        target = tmp_path / "subdir" / "state.db"
        monkeypatch.setenv("MEETSCRIBE_DB_PATH", str(target))
        import importlib
        importlib.reload(db)
        conn = db.connect()
        try:
            assert target.parent.exists()
            assert target.exists()
        finally:
            conn.close()

    def test_connect_sets_wal_mode(self, tmp_path, monkeypatch):
        target = tmp_path / "state.db"
        monkeypatch.setenv("MEETSCRIBE_DB_PATH", str(target))
        import importlib
        importlib.reload(db)
        conn = db.connect()
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode.lower() == "wal"
        finally:
            conn.close()

    def test_connect_sets_foreign_keys_on(self, tmp_path, monkeypatch):
        target = tmp_path / "state.db"
        monkeypatch.setenv("MEETSCRIBE_DB_PATH", str(target))
        import importlib
        importlib.reload(db)
        conn = db.connect()
        try:
            on = conn.execute("PRAGMA foreign_keys").fetchone()[0]
            assert on == 1
        finally:
            conn.close()

    def test_connect_returns_row_factory_for_dict_access(self, tmp_path, monkeypatch):
        target = tmp_path / "state.db"
        monkeypatch.setenv("MEETSCRIBE_DB_PATH", str(target))
        import importlib
        importlib.reload(db)
        conn = db.connect()
        try:
            assert conn.row_factory is sqlite3.Row
        finally:
            conn.close()


class TestConnectionContextManager:
    def test_commits_on_clean_exit(self, tmp_path, monkeypatch):
        target = tmp_path / "state.db"
        monkeypatch.setenv("MEETSCRIBE_DB_PATH", str(target))
        import importlib
        importlib.reload(db)
        with db.connection() as conn:
            conn.execute("CREATE TABLE t (x INTEGER)")
            conn.execute("INSERT INTO t VALUES (1)")
        with db.connection() as conn:
            row = conn.execute("SELECT x FROM t").fetchone()
            assert row[0] == 1

    def test_rolls_back_on_exception(self, tmp_path, monkeypatch):
        target = tmp_path / "state.db"
        monkeypatch.setenv("MEETSCRIBE_DB_PATH", str(target))
        import importlib
        importlib.reload(db)
        with db.connection() as conn:
            conn.execute("CREATE TABLE t (x INTEGER)")
        try:
            with db.connection() as conn:
                conn.execute("INSERT INTO t VALUES (1)")
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        with db.connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
            assert count == 0
