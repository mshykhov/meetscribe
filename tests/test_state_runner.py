"""Tests for src.state.runner migration runner."""

import sqlite3

import pytest

from src.state import db, runner


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    target = tmp_path / "state.db"
    monkeypatch.setenv("MEETSCRIBE_DB_PATH", str(target))
    import importlib
    importlib.reload(db)
    return target


class TestCurrentVersion:
    def test_returns_zero_on_empty_db(self, fresh_db):
        with db.connection() as conn:
            assert runner.current_version(conn) == 0

    def test_returns_version_after_migrations(self, fresh_db):
        with db.connection() as conn:
            runner.apply_migrations(conn)
            assert runner.current_version(conn) >= 1


class TestPendingMigrations:
    def test_all_pending_on_empty_db(self, fresh_db):
        with db.connection() as conn:
            pending = runner.pending_migrations(conn)
            assert len(pending) >= 1
            assert all(p.suffix == ".sql" for p in pending)
            assert pending[0].name.startswith("001_")

    def test_no_pending_after_apply(self, fresh_db):
        with db.connection() as conn:
            runner.apply_migrations(conn)
            assert runner.pending_migrations(conn) == []

    def test_returns_files_in_numeric_order(self, fresh_db):
        with db.connection() as conn:
            pending = runner.pending_migrations(conn)
            numbers = [int(p.name.split("_")[0]) for p in pending]
            assert numbers == sorted(numbers)


class TestApplyMigrations:
    def test_creates_schema_version_table(self, fresh_db):
        with db.connection() as conn:
            runner.apply_migrations(conn)
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
            ).fetchone()
            assert row is not None

    def test_creates_all_expected_tables(self, fresh_db):
        with db.connection() as conn:
            runner.apply_migrations(conn)
            tables = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                ).fetchall()
            }
            for expected in ("schema_version", "videos", "attempts", "events", "rate_limits"):
                assert expected in tables, f"missing table: {expected}"

    def test_returns_count_of_applied(self, fresh_db):
        with db.connection() as conn:
            count = runner.apply_migrations(conn)
            assert count >= 1

    def test_second_run_is_noop(self, fresh_db):
        with db.connection() as conn:
            runner.apply_migrations(conn)
        with db.connection() as conn:
            count = runner.apply_migrations(conn)
            assert count == 0

    def test_videos_check_constraint_enforced(self, fresh_db):
        with db.connection() as conn:
            runner.apply_migrations(conn)
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO videos (path, detected_at, state, updated_at) "
                    "VALUES ('/tmp/x.mp4', 0, 'bogus_state', 0)"
                )

    def test_foreign_key_enforced(self, fresh_db):
        with db.connection() as conn:
            runner.apply_migrations(conn)
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO attempts (video_id, attempt_num, backend, started_at) "
                    "VALUES (999, 1, 'local', 0)"
                )
