"""Tests for partial_data helpers and CancelledError in src.process."""

import importlib
import json

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


class TestCancelledError:
    def test_is_exception(self):
        from src import process
        importlib.reload(process)
        assert issubclass(process.CancelledError, Exception)


class TestCheckCancelled:
    def test_no_op_when_video_id_none(self, fresh_db):
        from src import process
        importlib.reload(process)
        process._check_cancelled(None)

    def test_no_op_when_state_not_cancelled(self, fresh_db):
        from src import process
        importlib.reload(process)
        with state.connection() as conn:
            vid = state.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
        process._check_cancelled(vid)

    def test_raises_on_cancelled_state(self, fresh_db):
        from src import process
        importlib.reload(process)
        with state.connection() as conn:
            vid = state.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
            state.transition_state(conn, vid, "cancelled")
        with pytest.raises(process.CancelledError):
            process._check_cancelled(vid)


class TestWritePartial:
    def test_writes_blob_and_stage(self, fresh_db):
        from src import process
        importlib.reload(process)
        with state.connection() as conn:
            vid = state.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
        data = {"segments": [{"start": 0, "end": 1, "text": "hi"}], "language": "en"}
        process._write_partial(vid, data, "transcribe")
        with state.connection() as conn:
            row = conn.execute(
                "SELECT partial_data, partial_stage FROM videos WHERE id=?", (vid,)
            ).fetchone()
        assert row["partial_stage"] == "transcribe"
        assert json.loads(row["partial_data"]) == data

    def test_no_op_when_video_id_none(self, fresh_db):
        from src import process
        importlib.reload(process)
        process._write_partial(None, {"segments": []}, "transcribe")


class TestLoadPartial:
    def test_returns_none_none_when_no_partial(self, fresh_db):
        from src import process
        importlib.reload(process)
        with state.connection() as conn:
            vid = state.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
        data, stage = process._load_partial(vid)
        assert data is None
        assert stage is None

    def test_loads_written_partial(self, fresh_db):
        from src import process
        importlib.reload(process)
        with state.connection() as conn:
            vid = state.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
        original = {"segments": [{"start": 0, "end": 1, "text": "hi"}], "language": "en"}
        process._write_partial(vid, original, "align")
        data, stage = process._load_partial(vid)
        assert data == original
        assert stage == "align"

    def test_returns_none_none_for_unknown_video(self, fresh_db):
        from src import process
        importlib.reload(process)
        data, stage = process._load_partial(99999)
        assert data is None
        assert stage is None


def _make_fake_video(path):
    import subprocess as sp
    sp.run(
        ["ffmpeg", "-f", "lavfi", "-i", "color=c=black:s=160x120:d=2",
         "-f", "lavfi", "-i", "anullsrc=channel_layout=mono:sample_rate=16000:d=2",
         "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", "-shortest",
         "-y", str(path)],
        check=True, capture_output=True,
    )


class TestProcessVideoClearsPartial:
    def test_partial_cleared_after_success(self, fresh_db, tmp_path, monkeypatch):
        from src import process
        importlib.reload(process)

        out = tmp_path / "output"
        out.mkdir()
        monkeypatch.setenv("OUTPUT_DIR", str(out))
        monkeypatch.setenv("HF_TOKEN", "hf_test")

        video_path = tmp_path / "v.mp4"
        _make_fake_video(video_path)

        with state.connection() as conn:
            vid = state.record_video_seen(conn, str(video_path.resolve()), 1000, 100, 5.0)
        process._write_partial(vid, {"segments": [], "language": "en"}, "diarize")

        def fake_transcribe(path, cfg, video_id=None):
            return {"segments": [{"start": 0.0, "end": 1.0, "text": "hi"}], "language": "en"}

        def fake_call_claude(prompt, cfg, timeout=600):
            return "### Короткое название\nfake\n\n### Тема\ntest"

        monkeypatch.setattr(process, "transcribe", fake_transcribe)
        from src import summarize
        monkeypatch.setattr(summarize, "call_summary_provider", fake_call_claude)

        process.process_video(str(video_path), video_id=vid)

        with state.connection() as conn:
            row = conn.execute(
                "SELECT partial_data, partial_stage FROM videos WHERE id=?", (vid,)
            ).fetchone()
        assert row["partial_data"] is None
        assert row["partial_stage"] is None


class TestProcessVideoHandlesCancel:
    def test_cancelled_error_re_raised_no_failed_state(self, fresh_db, tmp_path, monkeypatch):
        from src import process
        importlib.reload(process)

        out = tmp_path / "output"
        out.mkdir()
        monkeypatch.setenv("OUTPUT_DIR", str(out))
        monkeypatch.setenv("HF_TOKEN", "hf_test")

        video_path = tmp_path / "v.mp4"
        _make_fake_video(video_path)

        def fake_transcribe(path, cfg, video_id=None):
            raise process.CancelledError(f"video {video_id} cancelled")

        monkeypatch.setattr(process, "transcribe", fake_transcribe)

        with pytest.raises(process.CancelledError):
            process.process_video(str(video_path))

        with state.connection() as conn:
            videos = state.list_videos(conn)
            assert len(videos) == 1
            assert videos[0]["state"] != "failed"
            attempts = state.get_attempts(conn, videos[0]["id"])
            assert len(attempts) == 1
            assert attempts[0]["error_message"] == "cancelled by user"
            assert attempts[0]["exit_code"] == 130
