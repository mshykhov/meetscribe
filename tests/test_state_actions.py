"""Tests for state action helpers (transition_state, record_event, mark_skipped, mark_for_retry)."""

import json

import pytest

from src.state import operations as ops


class TestTransitionState:
    def test_updates_state_and_inserts_event(self, conn):
        vid = ops.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
        ops.transition_state(conn, vid, "queued")
        row = conn.execute("SELECT state FROM videos WHERE id=?", (vid,)).fetchone()
        assert row["state"] == "queued"
        events = ops.get_events(conn, vid)
        types = [e["event_type"] for e in events]
        assert "state_queued" in types

    def test_extra_details_in_event(self, conn):
        vid = ops.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
        ops.transition_state(conn, vid, "failed", extra_event_details={"reason": "stability_timeout"})
        events = ops.get_events(conn, vid)
        e = [e for e in events if e["event_type"] == "state_failed"][0]
        details = json.loads(e["details"])
        assert details["new_state"] == "failed"
        assert details["reason"] == "stability_timeout"


class TestRecordEvent:
    def test_inserts_event_without_state_change(self, conn):
        vid = ops.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
        ops.record_event(conn, vid, "stability_timeout", {"max_wait": 3600})
        events = ops.get_events(conn, vid)
        types = [e["event_type"] for e in events]
        assert "stability_timeout" in types
        row = conn.execute("SELECT state FROM videos WHERE id=?", (vid,)).fetchone()
        assert row["state"] == "detected"

    def test_supports_null_video_id_for_system_events(self, conn):
        ops.record_event(conn, None, "daemon_started")
        rows = conn.execute("SELECT * FROM events WHERE video_id IS NULL").fetchall()
        assert len(rows) == 1
        assert rows[0]["event_type"] == "daemon_started"


class TestMarkSkipped:
    def test_state_becomes_skipped(self, conn):
        vid = ops.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
        ops.mark_skipped(conn, vid, reason="user request")
        row = conn.execute("SELECT state FROM videos WHERE id=?", (vid,)).fetchone()
        assert row["state"] == "skipped"


class TestMarkForRetry:
    def test_resets_state_and_clears_terminal_fields(self, conn):
        vid = ops.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
        a = ops.start_attempt(conn, vid, "local")
        ops.fail_attempt(conn, a, vid, "boom", "transcribe")
        row = conn.execute("SELECT state, last_error, completed_at FROM videos WHERE id=?", (vid,)).fetchone()
        assert row["state"] == "failed"
        assert row["last_error"] == "boom"
        ops.mark_for_retry(conn, vid)
        row = conn.execute(
            "SELECT state, last_error, completed_at, current_stage, output_path FROM videos WHERE id=?",
            (vid,)
        ).fetchone()
        assert row["state"] == "detected"
        assert row["last_error"] is None
        assert row["completed_at"] is None
        assert row["current_stage"] is None
        assert row["output_path"] is None

    def test_inserts_retried_event(self, conn):
        vid = ops.record_video_seen(conn, "/tmp/v.mp4", 1000, 100, 10.0)
        ops.mark_for_retry(conn, vid)
        events = ops.get_events(conn, vid)
        assert any(e["event_type"] == "retried" for e in events)
