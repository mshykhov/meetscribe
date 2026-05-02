"""Tests for src.worker daemon."""

import importlib
import threading

import pytest

from src import state


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    target = tmp_path / "state.db"
    monkeypatch.setenv("MEETSCRIBE_DB_PATH", str(target))
    from src.state import db
    importlib.reload(db)
    from src.state import runner
    with db.connection() as c:
        runner.apply_migrations(c)
    return target


class TestPickNext:
    def test_returns_none_on_empty_queue(self, fresh_db):
        from src import worker
        importlib.reload(worker)
        result = worker._pick_next(threading.Event())
        assert result is None

    def test_returns_oldest_queued_video(self, fresh_db):
        from src import worker
        importlib.reload(worker)
        with state.connection() as conn:
            v1 = state.record_video_seen(conn, "/tmp/old.mp4", 1000, 100, 10.0)
            v2 = state.record_video_seen(conn, "/tmp/new.mp4", 2000, 100, 10.0)
            state.transition_state(conn, v1, "queued")
            state.transition_state(conn, v2, "queued")
        result = worker._pick_next(threading.Event())
        assert result is not None
        assert result["id"] == v1

    def test_skips_non_queued(self, fresh_db):
        from src import worker
        importlib.reload(worker)
        with state.connection() as conn:
            state.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
        result = worker._pick_next(threading.Event())
        assert result is None

    def test_skips_video_with_future_next_attempt_after(self, fresh_db):
        from src import worker
        importlib.reload(worker)
        with state.connection() as conn:
            v1 = state.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
            state.transition_state(conn, v1, "queued")
            conn.execute(
                "UPDATE videos SET next_attempt_after=? WHERE id=?",
                (9_999_999_999, v1),
            )
        result = worker._pick_next(threading.Event())
        assert result is None

    def test_skips_video_when_backend_rate_limited(self, fresh_db):
        from src import worker
        importlib.reload(worker)
        with state.connection() as conn:
            v1 = state.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
            state.transition_state(conn, v1, "queued")
            conn.execute("UPDATE videos SET backend_used='groq' WHERE id=?", (v1,))
            conn.execute(
                "INSERT INTO rate_limits (backend, until_ts, reason) VALUES ('groq', ?, '429')",
                (9_999_999_999,),
            )
        result = worker._pick_next(threading.Event())
        assert result is None


class TestOrphanRecovery:
    def test_processing_orphans_transitioned_to_queued(self, fresh_db):
        from src import worker
        importlib.reload(worker)
        with state.connection() as conn:
            v = state.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
            state.start_attempt(conn, v, "local")

        worker._recover_orphans()

        with state.connection() as conn:
            row = conn.execute("SELECT state FROM videos WHERE id=?", (v,)).fetchone()
        assert row["state"] == "queued"


class TestProcessVideo:
    def test_calls_subprocess_with_video_id(self, fresh_db, monkeypatch):
        from src import worker
        importlib.reload(worker)
        with state.connection() as conn:
            v = state.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)

        captured = []

        class FakeProc:
            returncode = 0

        def fake_run(args, **kwargs):
            captured.append(args)
            return FakeProc()

        monkeypatch.setattr(worker.subprocess, "run", fake_run)

        video = {"id": v, "path": "/tmp/v.mp4", "state": "queued"}
        worker._process_video(video, threading.Event())

        # Find the subprocess call (terminal-notifier suppressed via autouse fixture)
        process_calls = [c for c in captured if "src.process" in c]
        assert len(process_calls) == 1
        args = process_calls[0]
        assert "--video-id" in args
        assert str(v) in args
