"""Integration tests verifying src.process writes correctly to state.db.

We mock transcribe + claude to avoid running real ML / API.
"""

import importlib
import subprocess
from pathlib import Path

import pytest


def _make_fake_video(path: Path, duration: float = 5.0) -> None:
    """Create a real but minimal mp4 file for ffprobe to introspect."""
    subprocess.run(
        ["ffmpeg", "-f", "lavfi", "-i", f"color=c=black:s=160x120:d={int(duration)}",
         "-f", "lavfi", "-i", f"anullsrc=channel_layout=mono:sample_rate=16000:d={int(duration)}",
         "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", "-shortest",
         "-y", str(path)],
        check=True, capture_output=True,
    )


@pytest.fixture
def db_setup(tmp_path, monkeypatch):
    target = tmp_path / "state.db"
    monkeypatch.setenv("MEETSCRIBE_DB_PATH", str(target))
    from src.state import db
    importlib.reload(db)
    return target


@pytest.fixture
def output_dir(tmp_path, monkeypatch):
    out = tmp_path / "output"
    out.mkdir()
    monkeypatch.setenv("OUTPUT_DIR", str(out))
    return out


def test_process_video_writes_done_state_on_success(db_setup, output_dir, tmp_path, monkeypatch):
    """Successful pipeline -> 1 video / 1 attempt / multiple events / state='done'."""
    monkeypatch.setenv("HF_TOKEN", "hf_test")
    monkeypatch.setenv("CLAUDE_CLI", "claude")

    video_path = tmp_path / "test.mp4"
    _make_fake_video(video_path, duration=5.0)

    from src import process
    importlib.reload(process)

    fake_result = {
        "segments": [{"start": 0.0, "end": 1.0, "text": " hi", "speaker": "SPEAKER_00"}],
        "language": "en",
    }

    def fake_transcribe(path, cfg, video_id=None):
        return fake_result

    def fake_call_claude(prompt, cfg, timeout=600):
        return "### Короткое название\nfake summary\n\n### Тема\ntest"

    monkeypatch.setattr(process, "transcribe", fake_transcribe)
    monkeypatch.setattr(process, "call_claude", fake_call_claude)

    process.process_video(str(video_path))

    from src import state
    with state.connection() as conn:
        videos = state.list_videos(conn)
        assert len(videos) == 1
        assert videos[0]["state"] == "done"
        assert videos[0]["path"] == str(video_path.resolve())
        attempts = state.get_attempts(conn, videos[0]["id"])
        assert len(attempts) == 1
        assert attempts[0]["exit_code"] == 0
        events = state.get_events(conn, videos[0]["id"])
        event_types = {e["event_type"] for e in events}
        assert "detected" in event_types
        assert "processing_started" in event_types
        assert "completed" in event_types


def test_process_video_writes_failed_state_and_reraises(db_setup, output_dir, tmp_path, monkeypatch):
    """Exception in transcribe -> state='failed' / exit_code=1 / exception re-raised."""
    monkeypatch.setenv("HF_TOKEN", "hf_test")

    video_path = tmp_path / "test.mp4"
    _make_fake_video(video_path, duration=5.0)

    from src import process
    importlib.reload(process)

    def boom(path, cfg, video_id=None):
        raise RuntimeError("transcribe failed")

    monkeypatch.setattr(process, "transcribe", boom)

    with pytest.raises(RuntimeError, match="transcribe failed"):
        process.process_video(str(video_path))

    from src import state
    with state.connection() as conn:
        videos = state.list_videos(conn)
        assert len(videos) == 1
        assert videos[0]["state"] == "failed"
        assert "transcribe failed" in (videos[0]["last_error"] or "")
        attempts = state.get_attempts(conn, videos[0]["id"])
        assert len(attempts) == 1
        assert attempts[0]["exit_code"] == 1
        assert attempts[0]["error_message"] == "transcribe failed"


def test_state_write_failure_does_not_abort_pipeline(db_setup, output_dir, tmp_path, monkeypatch):
    """If state.db is unwritable, pipeline still completes; we log but don't raise."""
    monkeypatch.setenv("MEETSCRIBE_DB_PATH", "/nonexistent_root/cannot_create/state.db")
    from src.state import db
    importlib.reload(db)

    monkeypatch.setenv("HF_TOKEN", "hf_test")
    video_path = tmp_path / "test.mp4"
    _make_fake_video(video_path, duration=5.0)

    from src import process
    importlib.reload(process)

    fake_result = {"segments": [{"start": 0.0, "end": 1.0, "text": " hi"}], "language": "en"}

    def fake_transcribe(path, cfg, video_id=None):
        return fake_result

    def fake_call_claude(prompt, cfg, timeout=600):
        return "### Короткое название\nfake\n\n### Тема\ntest"

    monkeypatch.setattr(process, "transcribe", fake_transcribe)
    monkeypatch.setattr(process, "call_claude", fake_call_claude)

    process.process_video(str(video_path))
