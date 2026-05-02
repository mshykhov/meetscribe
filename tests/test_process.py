"""Integration tests for src.process pipeline."""

import importlib
import subprocess
from pathlib import Path

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


def _make_video(tmp_path: Path) -> Path:
    video_path = tmp_path / "v.mp4"
    subprocess.run(
        ["ffmpeg", "-f", "lavfi", "-i", "color=c=black:s=160x120:d=2",
         "-f", "lavfi", "-i", "anullsrc=channel_layout=mono:sample_rate=16000:d=2",
         "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", "-shortest",
         "-y", str(video_path)],
        check=True, capture_output=True,
    )
    return video_path


class TestProcessVideoSidecar:
    def test_sidecar_overrides_applied_to_cfg(self, fresh_db, tmp_path, monkeypatch):
        """Sidecar with whisper_model='tiny' overrides env default."""
        from src import process
        importlib.reload(process)

        out = tmp_path / "output"
        out.mkdir()
        monkeypatch.setenv("OUTPUT_DIR", str(out))
        monkeypatch.setenv("HF_TOKEN", "hf_test")
        monkeypatch.setenv("WHISPER_MODEL", "large-v2")  # baseline

        video_path = _make_video(tmp_path)
        sidecar = tmp_path / "v.meetscribe.toml"
        sidecar.write_text('whisper_model = "tiny"\n')

        captured: dict = {}

        def fake_transcribe(path, cfg, video_id=None):
            captured["cfg"] = cfg
            raise RuntimeError("stop here, we only need cfg")

        monkeypatch.setattr(process, "transcribe", fake_transcribe)

        with pytest.raises(RuntimeError, match="stop here"):
            process.process_video(str(video_path))

        assert captured["cfg"]["whisper_model"] == "tiny"

    def test_invalid_sidecar_marks_video_invalid(self, fresh_db, tmp_path, monkeypatch):
        """SidecarError -> state='invalid' + invalid notification + re-raise."""
        from src import process
        importlib.reload(process)

        out = tmp_path / "output"
        out.mkdir()
        monkeypatch.setenv("OUTPUT_DIR", str(out))
        monkeypatch.setenv("HF_TOKEN", "hf_test")

        video_path = _make_video(tmp_path)
        with state.connection() as conn:
            video_id = state.record_video_seen(
                conn, str(video_path.resolve()), 1000, 100, 60.0
            )
        sidecar = tmp_path / "v.meetscribe.toml"
        sidecar.write_text("foo = 1\n")  # unknown key

        called = []

        def spy_notify(event_type, **kwargs):
            called.append((event_type, kwargs))

        monkeypatch.setattr(process, "notify_event", spy_notify)

        from src.sidecar import SidecarError
        with pytest.raises(SidecarError):
            process.process_video(str(video_path), video_id=video_id)

        with state.connection() as conn:
            video = state.get_video(conn, str(video_id))
        assert video["state"] == "invalid"

        invalid_calls = [c for c in called if c[0] == "invalid"]
        assert len(invalid_calls) == 1

        with state.connection() as conn:
            events = state.get_events(conn, video_id)
        invalid_events = [
            e for e in events if e["event_type"] == "state_invalid"
        ]
        assert len(invalid_events) == 1
        assert "unknown key 'foo'" in invalid_events[0]["details"]
