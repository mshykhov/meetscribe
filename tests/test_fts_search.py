"""Tests for FTS5 meeting search (migration 002 + upsert/search)."""

import pytest

from src.state import operations as ops


class TestMeetingFtsUpsert:
    def test_inserts_new_row(self, conn):
        ops.upsert_meeting_fts(
            conn, 1, "2026-05-13-release-process",
            transcript="[00:00] SPEAKER_00: release process walkthrough",
            summary="### Тема\nRelease process tutorial",
        )
        row = conn.execute(
            "SELECT folder_name, transcript, summary FROM meeting_fts WHERE video_id=?",
            (1,),
        ).fetchone()
        assert row["folder_name"] == "2026-05-13-release-process"
        assert "walkthrough" in row["transcript"]
        assert "tutorial" in row["summary"]

    def test_replaces_existing_row(self, conn):
        ops.upsert_meeting_fts(conn, 1, "f1", "transcript v1", "summary v1")
        ops.upsert_meeting_fts(conn, 1, "f1-renamed", "transcript v2", "summary v2")
        rows = conn.execute(
            "SELECT folder_name, transcript FROM meeting_fts WHERE video_id=?", (1,),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["folder_name"] == "f1-renamed"
        assert rows[0]["transcript"] == "transcript v2"


class TestMeetingFtsSearch:
    def _seed(self, conn):
        from src.state.operations import record_video_seen
        v1 = record_video_seen(conn, "/tmp/a.mov", 1000, 100, 10.0)
        v2 = record_video_seen(conn, "/tmp/b.mov", 2000, 100, 10.0)
        v3 = record_video_seen(conn, "/tmp/c.mov", 3000, 100, 10.0)
        conn.execute(
            "UPDATE videos SET output_path=?, state='done' WHERE id=?",
            ("/out/2026-05-13-release-process", v1),
        )
        conn.execute(
            "UPDATE videos SET output_path=?, state='done' WHERE id=?",
            ("/out/2026-05-12-sprint-review", v2),
        )
        conn.execute(
            "UPDATE videos SET output_path=?, state='done' WHERE id=?",
            ("/out/2026-05-11-retro", v3),
        )
        ops.upsert_meeting_fts(
            conn, v1, "2026-05-13-release-process",
            transcript="SPEAKER_00: today we walk through the release process for memberships",
            summary="Tutorial about releasing the membership backend",
        )
        ops.upsert_meeting_fts(
            conn, v2, "2026-05-12-sprint-review",
            transcript="SPEAKER_00: sprint review notes for last two weeks",
            summary="Sprint review covering velocity and roadmap",
        )
        ops.upsert_meeting_fts(
            conn, v3, "2026-05-11-retro",
            transcript="SPEAKER_00: retrospective meeting about onboarding issues",
            summary="Retro action items",
        )
        return v1, v2, v3

    def test_matches_by_transcript_word(self, conn):
        v1, v2, v3 = self._seed(conn)
        rows = ops.search_meeting_fts(conn, "release")
        ids = [r["id"] for r in rows]
        assert v1 in ids
        assert v2 not in ids

    def test_matches_by_summary_word(self, conn):
        v1, v2, v3 = self._seed(conn)
        rows = ops.search_meeting_fts(conn, "velocity")
        assert [r["id"] for r in rows] == [v2]

    def test_prefix_search_with_star(self, conn):
        v1, v2, v3 = self._seed(conn)
        rows = ops.search_meeting_fts(conn, "release*")
        assert any(r["id"] == v1 for r in rows)

    def test_empty_query_returns_empty(self, conn):
        rows = ops.search_meeting_fts(conn, "")
        assert rows == []

    def test_snippets_carry_match_markers(self, conn):
        v1, *_ = self._seed(conn)
        rows = ops.search_meeting_fts(conn, "release")
        assert any("<mark>release</mark>" in r["transcript_snippet"] for r in rows)

    def test_no_match_returns_empty(self, conn):
        self._seed(conn)
        assert ops.search_meeting_fts(conn, "nonexistentword") == []
