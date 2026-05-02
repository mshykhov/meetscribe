"""Tests for rate-limit handling: 429 detection, Retry-After parsing, state updates."""

import importlib
import time
from unittest.mock import MagicMock

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


class TestParseRetryAfter:
    def test_integer_seconds(self):
        from src.openai_transcribe import _parse_retry_after
        assert _parse_retry_after("30") == 30

    def test_zero_returns_one(self):
        from src.openai_transcribe import _parse_retry_after
        assert _parse_retry_after("0") == 1

    def test_negative_returns_one(self):
        from src.openai_transcribe import _parse_retry_after
        assert _parse_retry_after("-5") == 1

    def test_none_returns_default(self):
        from src.openai_transcribe import _parse_retry_after, DEFAULT_RETRY_AFTER_SEC
        assert _parse_retry_after(None) == DEFAULT_RETRY_AFTER_SEC

    def test_empty_string_returns_default(self):
        from src.openai_transcribe import _parse_retry_after, DEFAULT_RETRY_AFTER_SEC
        assert _parse_retry_after("") == DEFAULT_RETRY_AFTER_SEC

    def test_garbage_returns_default(self):
        from src.openai_transcribe import _parse_retry_after, DEFAULT_RETRY_AFTER_SEC
        assert _parse_retry_after("not a number") == DEFAULT_RETRY_AFTER_SEC

    def test_http_date_in_future(self):
        from src.openai_transcribe import _parse_retry_after
        from email.utils import format_datetime
        from datetime import datetime, timezone, timedelta
        future = datetime.now(timezone.utc) + timedelta(seconds=120)
        result = _parse_retry_after(format_datetime(future))
        assert 100 <= result <= 130


class TestRateLimitedError:
    def test_carries_backend_and_seconds(self):
        from src.openai_transcribe import RateLimitedError
        e = RateLimitedError("groq", 60, "429 from API")
        assert e.backend == "groq"
        assert e.retry_after_seconds == 60
        assert "groq" in str(e)
        assert "60" in str(e)


class TestRateLimitOnTranscribe:
    def test_rate_limit_error_raised_on_429(self, tmp_path, monkeypatch):
        from src import openai_transcribe
        importlib.reload(openai_transcribe)

        # Make a fake video
        import subprocess
        video = tmp_path / "v.mp4"
        subprocess.run(
            ["ffmpeg", "-f", "lavfi", "-i", "color=c=black:s=160x120:d=2",
             "-f", "lavfi", "-i", "anullsrc=channel_layout=mono:sample_rate=16000:d=2",
             "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", "-shortest",
             "-y", str(video)],
            check=True, capture_output=True,
        )

        # Mock client to raise RateLimitError
        from openai import RateLimitError
        mock_response = MagicMock()
        mock_response.headers = {"retry-after": "45"}
        err = RateLimitError("rate limited", response=mock_response, body=None)
        mock_client = MagicMock()
        mock_client.audio.transcriptions.create.side_effect = err
        monkeypatch.setattr(openai_transcribe, "OpenAI", lambda **kwargs: mock_client)

        with pytest.raises(openai_transcribe.RateLimitedError) as excinfo:
            openai_transcribe.transcribe_via_openai(
                video, backend="groq", api_key="test", model="whisper-1", language=None,
            )
        assert excinfo.value.backend == "groq"
        assert excinfo.value.retry_after_seconds == 45


class TestSetRateLimit:
    def test_inserts_row_and_event(self, conn):
        from src.state import operations as ops
        ops.set_rate_limit(conn, "groq", 1234567890, "429 too many requests")
        row = conn.execute("SELECT * FROM rate_limits WHERE backend='groq'").fetchone()
        assert row["until_ts"] == 1234567890
        assert "too many" in row["reason"]
        events = conn.execute(
            "SELECT * FROM events WHERE event_type='rate_limited'"
        ).fetchall()
        assert len(events) == 1


class TestSetVideoNextAttempt:
    def test_updates_videos_field(self, conn):
        from src.state import operations as ops
        vid = ops.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
        ops.set_video_next_attempt(conn, vid, 1234567890)
        row = conn.execute("SELECT next_attempt_after FROM videos WHERE id=?", (vid,)).fetchone()
        assert row["next_attempt_after"] == 1234567890


class TestProcessVideoHandlesRateLimit:
    def test_rate_limit_marks_queued_with_next_attempt(self, fresh_db, tmp_path, monkeypatch):
        """RateLimitedError in transcribe -> video queued + rate_limits + next_attempt_after."""
        from src import process, openai_transcribe
        importlib.reload(openai_transcribe)
        importlib.reload(process)

        out = tmp_path / "output"
        out.mkdir()
        monkeypatch.setenv("OUTPUT_DIR", str(out))
        monkeypatch.setenv("HF_TOKEN", "hf_test")

        import subprocess
        video_path = tmp_path / "v.mp4"
        subprocess.run(
            ["ffmpeg", "-f", "lavfi", "-i", "color=c=black:s=160x120:d=2",
             "-f", "lavfi", "-i", "anullsrc=channel_layout=mono:sample_rate=16000:d=2",
             "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", "-shortest",
             "-y", str(video_path)],
            check=True, capture_output=True,
        )

        def fake_transcribe(path, cfg, video_id=None):
            raise openai_transcribe.RateLimitedError("groq", 60, "429")

        monkeypatch.setattr(process, "transcribe", fake_transcribe)

        with pytest.raises(openai_transcribe.RateLimitedError):
            process.process_video(str(video_path))

        with state.connection() as conn:
            videos = state.list_videos(conn)
            assert len(videos) == 1
            assert videos[0]["state"] == "queued"
            assert videos[0]["next_attempt_after"] is not None
            now = int(time.time())
            assert now <= videos[0]["next_attempt_after"] <= now + 70
            # rate_limits row written
            rl = conn.execute("SELECT * FROM rate_limits WHERE backend='groq'").fetchone()
            assert rl is not None
            assert rl["until_ts"] == videos[0]["next_attempt_after"]

    def test_rate_limit_triggers_notify_event(self, fresh_db, tmp_path, monkeypatch):
        """RateLimitedError -> process.py calls notify_event('rate_limited', ...)."""
        from src import process, openai_transcribe
        importlib.reload(openai_transcribe)
        importlib.reload(process)

        out = tmp_path / "output"
        out.mkdir()
        monkeypatch.setenv("OUTPUT_DIR", str(out))
        monkeypatch.setenv("HF_TOKEN", "hf_test")

        import subprocess
        video_path = tmp_path / "v.mp4"
        subprocess.run(
            ["ffmpeg", "-f", "lavfi", "-i", "color=c=black:s=160x120:d=2",
             "-f", "lavfi", "-i", "anullsrc=channel_layout=mono:sample_rate=16000:d=2",
             "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", "-shortest",
             "-y", str(video_path)],
            check=True, capture_output=True,
        )

        def fake_transcribe(path, cfg, video_id=None):
            raise openai_transcribe.RateLimitedError("groq", 60, "429")

        monkeypatch.setattr(process, "transcribe", fake_transcribe)

        called = []

        def spy_notify(event_type, **kwargs):
            called.append((event_type, kwargs))

        monkeypatch.setattr(process, "notify_event", spy_notify)

        with pytest.raises(openai_transcribe.RateLimitedError):
            process.process_video(str(video_path))

        rate_calls = [c for c in called if c[0] == "rate_limited"]
        assert len(rate_calls) == 1
        kwargs = rate_calls[0][1]
        assert kwargs["backend"] == "groq"
        assert kwargs["retry_after"] == 60
