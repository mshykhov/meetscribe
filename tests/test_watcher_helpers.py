"""Unit tests for watcher daemon pure helpers."""

import importlib
import subprocess
import threading
import time as time_module
from pathlib import Path

import pytest

from src import state, watcher


class TestIsVideo:
    @pytest.mark.parametrize("name", ["a.mp4", "b.mkv", "c.webm", "d.mov", "e.flv", "f.avi"])
    def test_video_extensions(self, name):
        assert watcher._is_video(Path(name)) is True

    @pytest.mark.parametrize("name", ["a.txt", "b.opus", "c.json", "d", "e.tmp"])
    def test_non_video(self, name):
        assert watcher._is_video(Path(name)) is False

    def test_case_insensitive(self):
        assert watcher._is_video(Path("video.MP4")) is True
        assert watcher._is_video(Path("video.MKV")) is True


class TestEligibleForProcessing:
    def test_unknown_path_eligible(self, conn, tmp_path):
        path = tmp_path / "new.mp4"
        path.touch()
        importlib.reload(watcher)
        assert watcher._eligible_for_processing(path) is True

    def test_done_state_not_eligible(self, conn, tmp_path):
        path = tmp_path / "done.mp4"
        path.touch()
        vid = state.record_video_seen(conn, str(path.resolve()), 1000, 100, 10.0)
        a = state.start_attempt(conn, vid, "local")
        state.complete_attempt(conn, a, vid, "/out")
        conn.commit()
        importlib.reload(watcher)
        assert watcher._eligible_for_processing(path) is False

    def test_failed_state_eligible(self, conn, tmp_path):
        path = tmp_path / "failed.mp4"
        path.touch()
        vid = state.record_video_seen(conn, str(path.resolve()), 1000, 100, 10.0)
        a = state.start_attempt(conn, vid, "local")
        state.fail_attempt(conn, a, vid, "boom", "transcribe")
        conn.commit()
        importlib.reload(watcher)
        assert watcher._eligible_for_processing(path) is True

    def test_processing_state_not_eligible(self, conn, tmp_path):
        path = tmp_path / "running.mp4"
        path.touch()
        vid = state.record_video_seen(conn, str(path.resolve()), 1000, 100, 10.0)
        state.start_attempt(conn, vid, "local")
        conn.commit()
        importlib.reload(watcher)
        assert watcher._eligible_for_processing(path) is False

    def test_skipped_state_not_eligible(self, conn, tmp_path):
        path = tmp_path / "skipped.mp4"
        path.touch()
        vid = state.record_video_seen(conn, str(path.resolve()), 1000, 100, 10.0)
        state.mark_skipped(conn, vid)
        conn.commit()
        importlib.reload(watcher)
        assert watcher._eligible_for_processing(path) is False


class TestInitialScan:
    def test_empty_dir_returns_empty(self, conn, tmp_path):
        watch_dir = tmp_path / "watch"
        watch_dir.mkdir()
        importlib.reload(watcher)
        assert watcher._initial_scan(watch_dir) == []

    def test_finds_videos(self, conn, tmp_path):
        watch_dir = tmp_path / "watch"
        watch_dir.mkdir()
        (watch_dir / "a.mp4").touch()
        (watch_dir / "b.mkv").touch()
        (watch_dir / "ignored.txt").touch()
        importlib.reload(watcher)
        result = watcher._initial_scan(watch_dir)
        names = sorted(Path(p).name for p in result)
        assert names == ["a.mp4", "b.mkv"]

    def test_skips_non_eligible(self, conn, tmp_path):
        watch_dir = tmp_path / "watch"
        watch_dir.mkdir()
        path = watch_dir / "done.mp4"
        path.touch()
        vid = state.record_video_seen(conn, str(path.resolve()), 1000, 100, 10.0)
        a = state.start_attempt(conn, vid, "local")
        state.complete_attempt(conn, a, vid, "/out")
        conn.commit()
        importlib.reload(watcher)
        result = watcher._initial_scan(watch_dir)
        assert result == []


class TestIsOpen:
    def test_returns_true_when_lsof_finds_process(self, monkeypatch):
        def fake_run(args, **kwargs):
            return subprocess.CompletedProcess(args, returncode=0, stdout=b"data", stderr=b"")
        monkeypatch.setattr(watcher.subprocess, "run", fake_run)
        assert watcher._is_open(Path("/tmp/x.mp4")) is True

    def test_returns_false_when_lsof_returncode_nonzero(self, monkeypatch):
        def fake_run(args, **kwargs):
            return subprocess.CompletedProcess(args, returncode=1, stdout=b"", stderr=b"")
        monkeypatch.setattr(watcher.subprocess, "run", fake_run)
        assert watcher._is_open(Path("/tmp/x.mp4")) is False


class TestValidate:
    def test_missing_file(self, tmp_path):
        ok, reason = watcher._validate(tmp_path / "missing.mp4")
        assert ok is False
        assert "does not exist" in reason

    def test_short_file(self, tmp_path, monkeypatch):
        path = tmp_path / "short.mp4"
        path.touch()
        monkeypatch.setattr(watcher, "_get_duration", lambda p: 2.0)
        ok, reason = watcher._validate(path)
        assert ok is False
        assert "too short" in reason

    def test_long_file(self, tmp_path, monkeypatch):
        path = tmp_path / "long.mp4"
        path.touch()
        monkeypatch.setattr(watcher, "_get_duration", lambda p: 5 * 3600)
        ok, reason = watcher._validate(path)
        assert ok is False
        assert "too long" in reason

    def test_ok(self, tmp_path, monkeypatch):
        path = tmp_path / "ok.mp4"
        path.touch()
        monkeypatch.setattr(watcher, "_get_duration", lambda p: 60.0)
        ok, reason = watcher._validate(path)
        assert ok is True
        assert reason is None


class TestWaitForStable:
    def test_returns_false_on_shutdown(self, conn, tmp_path, monkeypatch):
        path = tmp_path / "v.mp4"
        path.write_bytes(b"x" * 100)
        monkeypatch.setattr(watcher, "_is_open", lambda p: True)
        monkeypatch.setattr(watcher.time, "sleep", lambda s: None)
        vid = state.record_video_seen(conn, str(path.resolve()), 1000, 100, 10.0)
        conn.commit()
        shutdown = threading.Event()
        threading.Thread(target=lambda: (time_module.sleep(0.1), shutdown.set()), daemon=True).start()
        ok = watcher._wait_for_stable(path, video_id=vid, shutdown=shutdown)
        assert ok is False

    def test_returns_true_when_size_stable(self, conn, tmp_path, monkeypatch):
        path = tmp_path / "v.mp4"
        path.write_bytes(b"x" * 100)
        monkeypatch.setattr(watcher, "_is_open", lambda p: False)
        monkeypatch.setattr(watcher.time, "sleep", lambda s: None)
        vid = state.record_video_seen(conn, str(path.resolve()), 1000, 100, 10.0)
        conn.commit()
        shutdown = threading.Event()
        ok = watcher._wait_for_stable(path, video_id=vid, shutdown=shutdown)
        assert ok is True
