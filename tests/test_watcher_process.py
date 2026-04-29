"""Integration tests for watcher._process_one - the per-video orchestrator."""

import importlib
import threading
from pathlib import Path

import pytest

from src import state, watcher


@pytest.fixture
def patched_subprocess(monkeypatch):
    """Replace subprocess.run with a mock that records calls and returns success."""
    calls = []
    real_run = watcher.subprocess.run

    def fake_run(args, **kwargs):
        # Pass through lsof / ffprobe / terminal-notifier; intercept python -m src.process
        if args and args[0] == watcher.sys.executable and len(args) > 2 and args[2] == "src.process":
            calls.append((args, kwargs))
            from subprocess import CompletedProcess
            return CompletedProcess(args=args, returncode=0)
        return real_run(args, **kwargs)

    monkeypatch.setattr(watcher.subprocess, "run", fake_run)
    return calls


def test_process_one_happy_path(conn, tmp_path, monkeypatch, patched_subprocess):
    path = tmp_path / "v.mp4"
    path.write_bytes(b"x" * 100)

    monkeypatch.setattr(watcher, "_is_open", lambda p: False)
    monkeypatch.setattr(watcher, "_get_duration", lambda p: 60.0)
    monkeypatch.setattr(watcher.time, "sleep", lambda s: None)
    monkeypatch.setattr(watcher, "notify", lambda *a, **kw: None)

    shutdown = threading.Event()
    watcher._process_one(str(path.resolve()), shutdown)

    assert len(patched_subprocess) == 1
    args, _ = patched_subprocess[0]
    assert args[1] == "-m"
    assert args[2] == "src.process"
    assert args[3] == str(path.resolve())

    with state.connection() as c:
        videos = state.list_videos(c)
        assert len(videos) == 1
        assert videos[0]["state"] == "queued"


def test_process_one_skips_invalid_duration(conn, tmp_path, monkeypatch, patched_subprocess):
    path = tmp_path / "tiny.mp4"
    path.write_bytes(b"x" * 100)

    monkeypatch.setattr(watcher, "_is_open", lambda p: False)
    monkeypatch.setattr(watcher, "_get_duration", lambda p: 2.0)
    monkeypatch.setattr(watcher.time, "sleep", lambda s: None)
    monkeypatch.setattr(watcher, "notify", lambda *a, **kw: None)

    shutdown = threading.Event()
    watcher._process_one(str(path.resolve()), shutdown)

    assert len(patched_subprocess) == 0
    with state.connection() as c:
        videos = state.list_videos(c)
        assert len(videos) == 1
        assert videos[0]["state"] == "invalid"


def test_process_one_skips_already_done(conn, tmp_path, monkeypatch, patched_subprocess):
    path = tmp_path / "done.mp4"
    path.write_bytes(b"x" * 100)
    vid = state.record_video_seen(conn, str(path.resolve()), 1000, 100, 60.0)
    a = state.start_attempt(conn, vid, "local")
    state.complete_attempt(conn, a, vid, "/out")
    conn.commit()

    monkeypatch.setattr(watcher.time, "sleep", lambda s: None)
    monkeypatch.setattr(watcher, "notify", lambda *a, **kw: None)

    shutdown = threading.Event()
    watcher._process_one(str(path.resolve()), shutdown)

    assert len(patched_subprocess) == 0


class TestWatchHandler:
    def test_on_created_enqueues_video(self, conn, tmp_path):
        from queue import Queue
        from watchdog.events import FileCreatedEvent
        watch_dir = tmp_path / "w"
        watch_dir.mkdir()
        path = watch_dir / "new.mp4"
        path.touch()

        q = Queue()
        handler = watcher.WatchHandler(q, watch_dir)
        handler.on_created(FileCreatedEvent(str(path)))

        assert not q.empty()
        assert q.get() == str(path.resolve())

    def test_on_created_ignores_non_video(self, tmp_path):
        from queue import Queue
        from watchdog.events import FileCreatedEvent
        watch_dir = tmp_path / "w"
        watch_dir.mkdir()
        path = watch_dir / "junk.txt"
        path.touch()

        q = Queue()
        handler = watcher.WatchHandler(q, watch_dir)
        handler.on_created(FileCreatedEvent(str(path)))
        assert q.empty()

    def test_on_created_ignores_directory(self, tmp_path):
        from queue import Queue
        from watchdog.events import DirCreatedEvent
        watch_dir = tmp_path / "w"
        watch_dir.mkdir()
        sub = watch_dir / "sub"
        sub.mkdir()

        q = Queue()
        handler = watcher.WatchHandler(q, watch_dir)
        handler.on_created(DirCreatedEvent(str(sub)))
        assert q.empty()

    def test_on_created_skips_non_eligible(self, conn, tmp_path):
        from queue import Queue
        from watchdog.events import FileCreatedEvent
        watch_dir = tmp_path / "w"
        watch_dir.mkdir()
        path = watch_dir / "done.mp4"
        path.touch()
        vid = state.record_video_seen(conn, str(path.resolve()), 1000, 100, 10.0)
        a = state.start_attempt(conn, vid, "local")
        state.complete_attempt(conn, a, vid, "/out")
        conn.commit()

        q = Queue()
        importlib.reload(watcher)
        handler = watcher.WatchHandler(q, watch_dir)
        handler.on_created(FileCreatedEvent(str(path)))
        assert q.empty()
