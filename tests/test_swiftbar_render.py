"""Tests for src.swiftbar.render() output."""

import importlib

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


class TestRenderIdle:
    def test_empty_db_shows_idle(self, fresh_db):
        from src import swiftbar
        importlib.reload(swiftbar)
        out = swiftbar.render()
        assert "color=#888888" in out
        assert "---" in out
        assert "Meetscribe" in out


class TestRenderProcessing:
    def test_processing_shows_stage_icon(self, fresh_db):
        from src import swiftbar
        importlib.reload(swiftbar)
        with state.connection() as conn:
            vid = state.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 60.0)
            state.start_attempt(conn, vid, "local")
            state.set_current_stage(conn, vid, "diarize")
            conn.commit()
        out = swiftbar.render()
        assert "person.2.wave.2" in out
        assert "color=#4CAF50" in out
        assert "v.mp4" in out

    def test_each_stage_has_icon(self, fresh_db):
        from src import swiftbar
        importlib.reload(swiftbar)
        stages_to_icons = {
            "transcribe": "waveform",
            "align": "text.alignleft",
            "diarize": "person.2.wave.2",
            "summary": "sparkles",
        }
        for stage, icon in stages_to_icons.items():
            with state.connection() as conn:
                conn.execute("DELETE FROM videos")
                conn.commit()
            with state.connection() as conn:
                vid = state.record_video_seen(conn, f"/tmp/{stage}.mp4", 1000, 100, 60.0)
                state.start_attempt(conn, vid, "local")
                state.set_current_stage(conn, vid, stage)
                conn.commit()
            out = swiftbar.render()
            assert icon in out, f"stage {stage} should show icon {icon}"


class TestRenderQueued:
    def test_queued_only_shows_clock(self, fresh_db):
        from src import swiftbar
        importlib.reload(swiftbar)
        with state.connection() as conn:
            for i in range(3):
                v = state.record_video_seen(conn, f"/tmp/q{i}.mp4", 1000 + i, 100, 60.0)
                state.transition_state(conn, v, "queued")
            conn.commit()
        out = swiftbar.render()
        assert "clock" in out
        assert "3" in out


class TestRenderFailed:
    def test_failed_videos_show_red(self, fresh_db):
        from src import swiftbar
        importlib.reload(swiftbar)
        with state.connection() as conn:
            v = state.record_video_seen(conn, "/tmp/f.mp4", 1000, 100, 60.0)
            a = state.start_attempt(conn, v, "local")
            state.fail_attempt(conn, a, v, "boom", "transcribe")
            conn.commit()
        out = swiftbar.render()
        assert "exclamationmark.triangle" in out or "F44336" in out


class TestRenderRateLimited:
    def test_rate_limit_shows_pause_icon(self, fresh_db):
        from src import swiftbar
        importlib.reload(swiftbar)
        with state.connection() as conn:
            conn.execute(
                "INSERT INTO rate_limits (backend, until_ts, reason) VALUES ('groq', ?, '429')",
                (9_999_999_999,),
            )
            conn.commit()
        out = swiftbar.render()
        assert "Rate-limited" in out


class TestRenderPriorityOrder:
    def test_processing_takes_priority_over_queued(self, fresh_db):
        from src import swiftbar
        importlib.reload(swiftbar)
        with state.connection() as conn:
            v1 = state.record_video_seen(conn, "/tmp/active.mp4", 1000, 100, 60.0)
            state.start_attempt(conn, v1, "local")
            state.set_current_stage(conn, v1, "transcribe")
            v2 = state.record_video_seen(conn, "/tmp/queued.mp4", 2000, 100, 60.0)
            state.transition_state(conn, v2, "queued")
            conn.commit()
        out = swiftbar.render()
        first_line = next(l for l in out.split("\n") if l.strip() and not l.startswith("---"))
        assert "waveform" in first_line
