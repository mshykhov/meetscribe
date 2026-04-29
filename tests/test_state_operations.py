"""Tests for src.state.operations (CRUD)."""

import time

import pytest

from src.state import operations as ops


def _bump_updated_at(conn, video_id: int, ts: int) -> None:
    conn.execute("UPDATE videos SET updated_at = ? WHERE id = ?", (ts, video_id))


class TestRecordVideoSeen:
    def test_inserts_new_video(self, conn):
        video_id = ops.record_video_seen(
            conn, path="/tmp/v.mp4", detected_at=1000,
            size_bytes=12345, duration_sec=60.5,
        )
        assert video_id > 0
        row = conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
        assert row["path"] == "/tmp/v.mp4"
        assert row["state"] == "detected"
        assert row["size_bytes"] == 12345
        assert row["duration_sec"] == 60.5

    def test_idempotent_on_same_path(self, conn):
        v1 = ops.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
        v2 = ops.record_video_seen(conn, "/tmp/v.mp4", 2000, 200, 20.0)
        assert v1 == v2
        row = conn.execute("SELECT detected_at FROM videos WHERE id = ?", (v1,)).fetchone()
        assert row["detected_at"] == 1000


class TestStartAttempt:
    def test_inserts_attempt_row(self, conn):
        video_id = ops.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
        attempt_id = ops.start_attempt(conn, video_id, backend="local")
        assert attempt_id > 0
        row = conn.execute("SELECT * FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
        assert row["video_id"] == video_id
        assert row["attempt_num"] == 1
        assert row["backend"] == "local"
        assert row["completed_at"] is None

    def test_increments_attempt_num(self, conn):
        video_id = ops.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
        a1 = ops.start_attempt(conn, video_id, "local")
        ops.fail_attempt(conn, a1, video_id, error_message="x", stage_reached="transcribe")
        a2 = ops.start_attempt(conn, video_id, "local")
        row = conn.execute("SELECT attempt_num FROM attempts WHERE id = ?", (a2,)).fetchone()
        assert row["attempt_num"] == 2

    def test_updates_videos_state_to_processing(self, conn):
        video_id = ops.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
        ops.start_attempt(conn, video_id, "local")
        row = conn.execute(
            "SELECT state, current_stage, backend_used, attempts_count FROM videos WHERE id = ?",
            (video_id,),
        ).fetchone()
        assert row["state"] == "processing"
        assert row["current_stage"] == "transcribe"
        assert row["backend_used"] == "local"
        assert row["attempts_count"] == 1


class TestSetCurrentStage:
    def test_updates_current_stage(self, conn):
        video_id = ops.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
        ops.start_attempt(conn, video_id, "local")
        ops.set_current_stage(conn, video_id, "diarize")
        row = conn.execute("SELECT current_stage FROM videos WHERE id = ?", (video_id,)).fetchone()
        assert row["current_stage"] == "diarize"

    def test_inserts_stage_change_event(self, conn):
        video_id = ops.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
        ops.start_attempt(conn, video_id, "local")
        ops.set_current_stage(conn, video_id, "align")
        rows = conn.execute(
            "SELECT event_type, details FROM events WHERE video_id = ? AND event_type = 'stage_change'",
            (video_id,),
        ).fetchall()
        assert len(rows) >= 1
        assert "align" in rows[-1]["details"]


class TestCompleteAttempt:
    def test_updates_videos_to_done(self, conn):
        video_id = ops.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
        attempt_id = ops.start_attempt(conn, video_id, "local")
        ops.complete_attempt(conn, attempt_id, video_id, output_path="/out/dir")
        row = conn.execute(
            "SELECT state, output_path, completed_at, current_stage FROM videos WHERE id = ?",
            (video_id,),
        ).fetchone()
        assert row["state"] == "done"
        assert row["output_path"] == "/out/dir"
        assert row["completed_at"] is not None
        assert row["current_stage"] is None

    def test_updates_attempt_exit_code_zero(self, conn):
        video_id = ops.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
        attempt_id = ops.start_attempt(conn, video_id, "local")
        ops.complete_attempt(conn, attempt_id, video_id, output_path="/out/dir")
        row = conn.execute(
            "SELECT exit_code, completed_at FROM attempts WHERE id = ?", (attempt_id,)
        ).fetchone()
        assert row["exit_code"] == 0
        assert row["completed_at"] is not None


class TestFailAttempt:
    def test_updates_videos_to_failed(self, conn):
        video_id = ops.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
        attempt_id = ops.start_attempt(conn, video_id, "local")
        ops.fail_attempt(conn, attempt_id, video_id, error_message="boom", stage_reached="transcribe")
        row = conn.execute(
            "SELECT state, last_error, current_stage FROM videos WHERE id = ?", (video_id,)
        ).fetchone()
        assert row["state"] == "failed"
        assert row["last_error"] == "boom"
        assert row["current_stage"] is None

    def test_updates_attempt_with_error(self, conn):
        video_id = ops.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
        attempt_id = ops.start_attempt(conn, video_id, "local")
        ops.fail_attempt(conn, attempt_id, video_id, error_message="boom", stage_reached="diarize")
        row = conn.execute(
            "SELECT exit_code, error_message, stage_reached FROM attempts WHERE id = ?",
            (attempt_id,),
        ).fetchone()
        assert row["exit_code"] == 1
        assert row["error_message"] == "boom"
        assert row["stage_reached"] == "diarize"


class TestListVideos:
    def test_empty_db_returns_empty_list(self, conn):
        assert ops.list_videos(conn) == []

    def test_returns_videos_ordered_by_updated_at_desc(self, conn):
        v1 = ops.record_video_seen(conn, "/tmp/old.mp4", 1000, 100, 10.0)
        v2 = ops.record_video_seen(conn, "/tmp/new.mp4", 2000, 200, 20.0)
        # Force distinct updated_at values
        _bump_updated_at(conn, v1, 1000)
        _bump_updated_at(conn, v2, 2000)
        videos = ops.list_videos(conn)
        assert len(videos) == 2
        assert videos[0]["id"] == v2
        assert videos[1]["id"] == v1

    def test_filters_by_state(self, conn):
        v1 = ops.record_video_seen(conn, "/tmp/a.mp4", 1000, 100, 10.0)
        v2 = ops.record_video_seen(conn, "/tmp/b.mp4", 2000, 200, 20.0)
        a = ops.start_attempt(conn, v1, "local")
        ops.complete_attempt(conn, a, v1, "/out/a")
        done = ops.list_videos(conn, state="done")
        detected = ops.list_videos(conn, state="detected")
        assert len(done) == 1 and done[0]["id"] == v1
        assert len(detected) == 1 and detected[0]["id"] == v2

    def test_respects_limit(self, conn):
        for i in range(5):
            ops.record_video_seen(conn, f"/tmp/v{i}.mp4", 1000 + i, 100, 10.0)
        videos = ops.list_videos(conn, limit=3)
        assert len(videos) == 3


class TestGetVideo:
    def test_get_by_numeric_id(self, conn):
        vid = ops.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
        result = ops.get_video(conn, str(vid))
        assert result is not None
        assert result["id"] == vid
        assert result["path"] == "/tmp/v.mp4"

    def test_get_by_path(self, conn):
        vid = ops.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
        result = ops.get_video(conn, "/tmp/v.mp4")
        assert result is not None
        assert result["id"] == vid

    def test_returns_none_for_missing(self, conn):
        assert ops.get_video(conn, "999") is None
        assert ops.get_video(conn, "/tmp/missing.mp4") is None


class TestGetAttempts:
    def test_returns_attempts_for_video(self, conn):
        vid = ops.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
        a1 = ops.start_attempt(conn, vid, "local")
        ops.fail_attempt(conn, a1, vid, "x", "transcribe")
        a2 = ops.start_attempt(conn, vid, "openai")
        ops.complete_attempt(conn, a2, vid, "/out")
        attempts = ops.get_attempts(conn, vid)
        assert len(attempts) == 2
        assert attempts[0]["attempt_num"] == 1
        assert attempts[1]["attempt_num"] == 2
        assert attempts[0]["exit_code"] == 1
        assert attempts[1]["exit_code"] == 0


class TestGetEvents:
    def test_returns_events_recent_first(self, conn):
        vid = ops.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
        ops.start_attempt(conn, vid, "local")
        ops.set_current_stage(conn, vid, "diarize")
        events = ops.get_events(conn, vid, limit=10)
        assert len(events) >= 3
        types = [e["event_type"] for e in events]
        assert types[0] == "stage_change"
