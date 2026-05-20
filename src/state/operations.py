"""CRUD operations on state.db (videos, attempts, events tables)."""

import json
import sqlite3
import time


def _now() -> int:
    return int(time.time())


def record_video_seen(
    conn: sqlite3.Connection,
    path: str,
    detected_at: int,
    size_bytes: int | None,
    duration_sec: float | None,
) -> int:
    """INSERT OR IGNORE the video, return its id.

    On duplicate path, returns the existing video_id without modifying detected_at.
    """
    cursor = conn.execute(
        "INSERT OR IGNORE INTO videos (path, detected_at, size_bytes, duration_sec, "
        "state, updated_at) VALUES (?, ?, ?, ?, 'detected', ?)",
        (path, detected_at, size_bytes, duration_sec, _now()),
    )
    if cursor.rowcount > 0:
        video_id = cursor.lastrowid
    else:
        row = conn.execute("SELECT id FROM videos WHERE path = ?", (path,)).fetchone()
        video_id = row["id"]
    conn.execute(
        "INSERT INTO events (video_id, ts, event_type, details) VALUES (?, ?, 'detected', ?)",
        (video_id, _now(), json.dumps({"path": path})),
    )
    return video_id


def start_attempt(conn: sqlite3.Connection, video_id: int, backend: str) -> int:
    """INSERT into attempts; UPDATE videos to processing.

    attempt_num auto-derived from existing attempts for this video.
    """
    row = conn.execute(
        "SELECT COALESCE(MAX(attempt_num), 0) + 1 AS next_num FROM attempts WHERE video_id = ?",
        (video_id,),
    ).fetchone()
    attempt_num = row["next_num"]
    now = _now()
    cursor = conn.execute(
        "INSERT INTO attempts (video_id, attempt_num, backend, started_at) VALUES (?, ?, ?, ?)",
        (video_id, attempt_num, backend, now),
    )
    attempt_id = cursor.lastrowid
    conn.execute(
        "UPDATE videos SET state = 'processing', current_stage = 'transcribe', "
        "backend_used = ?, attempts_count = attempts_count + 1, "
        "started_at = COALESCE(started_at, ?), updated_at = ? "
        "WHERE id = ?",
        (backend, now, now, video_id),
    )
    conn.execute(
        "INSERT INTO events (video_id, ts, event_type, details) VALUES (?, ?, 'processing_started', ?)",
        (video_id, now, json.dumps({"backend": backend, "attempt_num": attempt_num})),
    )
    return attempt_id


def set_current_stage(conn: sqlite3.Connection, video_id: int, stage: str) -> None:
    """UPDATE videos.current_stage and INSERT a stage_change event."""
    now = _now()
    conn.execute(
        "UPDATE videos SET current_stage = ?, updated_at = ? WHERE id = ?",
        (stage, now, video_id),
    )
    conn.execute(
        "INSERT INTO events (video_id, ts, event_type, details) VALUES (?, ?, 'stage_change', ?)",
        (video_id, now, json.dumps({"stage": stage})),
    )


def complete_attempt(
    conn: sqlite3.Connection, attempt_id: int, video_id: int, output_path: str
) -> None:
    """Mark attempt and video as done."""
    now = _now()
    conn.execute(
        "UPDATE attempts SET completed_at = ?, exit_code = 0, stage_reached = 'summary' "
        "WHERE id = ?",
        (now, attempt_id),
    )
    conn.execute(
        "UPDATE videos SET state = 'done', output_path = ?, completed_at = ?, "
        "current_stage = NULL, progress = NULL, updated_at = ? WHERE id = ?",
        (output_path, now, now, video_id),
    )
    conn.execute(
        "INSERT INTO events (video_id, ts, event_type, details) VALUES (?, ?, 'completed', ?)",
        (video_id, now, json.dumps({"output_path": output_path})),
    )


def fail_attempt(
    conn: sqlite3.Connection,
    attempt_id: int,
    video_id: int,
    error_message: str,
    stage_reached: str,
) -> None:
    """Mark attempt and video as failed."""
    now = _now()
    conn.execute(
        "UPDATE attempts SET completed_at = ?, exit_code = 1, error_message = ?, "
        "stage_reached = ? WHERE id = ?",
        (now, error_message, stage_reached, attempt_id),
    )
    conn.execute(
        "UPDATE videos SET state = 'failed', last_error = ?, completed_at = ?, "
        "current_stage = NULL, updated_at = ? WHERE id = ?",
        (error_message, now, now, video_id),
    )
    conn.execute(
        "INSERT INTO events (video_id, ts, event_type, details) VALUES (?, ?, 'failed', ?)",
        (video_id, now, json.dumps({"error": error_message, "stage_reached": stage_reached})),
    )


def transition_state(
    conn: sqlite3.Connection,
    video_id: int,
    new_state: str,
    extra_event_details: dict | None = None,
) -> None:
    """UPDATE videos.state and INSERT a state-change event."""
    now = _now()
    conn.execute(
        "UPDATE videos SET state = ?, updated_at = ? WHERE id = ?",
        (new_state, now, video_id),
    )
    details = {"new_state": new_state}
    if extra_event_details:
        details.update(extra_event_details)
    conn.execute(
        "INSERT INTO events (video_id, ts, event_type, details) VALUES (?, ?, ?, ?)",
        (video_id, now, f"state_{new_state}", json.dumps(details)),
    )


def record_event(
    conn: sqlite3.Connection,
    video_id: int | None,
    event_type: str,
    details: dict | None = None,
) -> None:
    """Standalone event row insertion; for events that don't change state."""
    conn.execute(
        "INSERT INTO events (video_id, ts, event_type, details) VALUES (?, ?, ?, ?)",
        (video_id, _now(), event_type, json.dumps(details) if details else None),
    )


def mark_skipped(conn: sqlite3.Connection, video_id: int, reason: str | None = None) -> None:
    """Mark video as skipped (daemon will not process again)."""
    extras = {"reason": reason} if reason else None
    transition_state(conn, video_id, "skipped", extra_event_details=extras)


def set_rate_limit(
    conn: sqlite3.Connection,
    backend: str,
    until_ts: int,
    reason: str = "",
) -> None:
    """INSERT OR REPLACE rate_limits row. Sets backend-wide pause until until_ts."""
    conn.execute(
        "INSERT OR REPLACE INTO rate_limits (backend, until_ts, reason) VALUES (?, ?, ?)",
        (backend, until_ts, reason),
    )
    conn.execute(
        "INSERT INTO events (video_id, ts, event_type, details) VALUES (NULL, ?, 'rate_limited', ?)",
        (_now(), json.dumps({"backend": backend, "until_ts": until_ts, "reason": reason})),
    )


def set_video_next_attempt(
    conn: sqlite3.Connection,
    video_id: int,
    next_attempt_after: int,
) -> None:
    """UPDATE videos.next_attempt_after for delayed retry."""
    conn.execute(
        "UPDATE videos SET next_attempt_after=?, updated_at=strftime('%s','now') WHERE id=?",
        (next_attempt_after, video_id),
    )


def mark_for_retry(conn: sqlite3.Connection, video_id: int) -> None:
    """Reset state to 'detected' so daemon picks up. Clears terminal fields."""
    now = _now()
    conn.execute(
        "UPDATE videos SET state = 'detected', last_error = NULL, completed_at = NULL, "
        "current_stage = NULL, progress = NULL, output_path = NULL, updated_at = ? "
        "WHERE id = ?",
        (now, video_id),
    )
    conn.execute(
        "INSERT INTO events (video_id, ts, event_type, details) VALUES (?, ?, 'retried', ?)",
        (video_id, now, json.dumps({"by": "user"})),
    )


def list_videos(
    conn: sqlite3.Connection,
    state: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """SELECT videos, optionally filtered by state, ordered by updated_at DESC."""
    if state is None:
        rows = conn.execute(
            "SELECT * FROM videos ORDER BY updated_at DESC LIMIT ?", (limit,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM videos WHERE state = ? ORDER BY updated_at DESC LIMIT ?",
            (state, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_video(conn: sqlite3.Connection, id_or_path: str) -> dict | None:
    """SELECT one video by numeric id or path. Returns dict or None."""
    if id_or_path.isdigit():
        row = conn.execute("SELECT * FROM videos WHERE id = ?", (int(id_or_path),)).fetchone()
    else:
        row = conn.execute("SELECT * FROM videos WHERE path = ?", (id_or_path,)).fetchone()
    return dict(row) if row else None


def get_attempts(conn: sqlite3.Connection, video_id: int) -> list[dict]:
    """SELECT all attempts for a video, ordered by attempt_num."""
    rows = conn.execute(
        "SELECT * FROM attempts WHERE video_id = ? ORDER BY attempt_num", (video_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_events(conn: sqlite3.Connection, video_id: int, limit: int = 100) -> list[dict]:
    """SELECT recent events for a video, most recent first."""
    rows = conn.execute(
        "SELECT * FROM events WHERE video_id = ? ORDER BY ts DESC, id DESC LIMIT ?",
        (video_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def upsert_meeting_fts(
    conn: sqlite3.Connection,
    video_id: int,
    folder_name: str,
    transcript: str,
    summary: str,
) -> None:
    """Replace the FTS row for video_id (delete-then-insert)."""
    conn.execute("DELETE FROM meeting_fts WHERE video_id = ?", (video_id,))
    conn.execute(
        "INSERT INTO meeting_fts (video_id, folder_name, transcript, summary) "
        "VALUES (?, ?, ?, ?)",
        (video_id, folder_name, transcript, summary),
    )


def search_meeting_fts(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 50,
) -> list[dict]:
    """Run FTS5 MATCH against meeting_fts, return rows joined with videos.

    Each row includes video columns plus snippet() excerpts and bm25 rank.
    Empty query returns []. Uses FTS5 'NEAR' relevance via bm25.
    """
    if not query.strip():
        return []
    rows = conn.execute(
        """
        SELECT v.id, v.path, v.state, v.detected_at, v.completed_at,
               v.output_path, v.backend_used, v.duration_sec,
               snippet(meeting_fts, 2, '<mark>', '</mark>', '...', 12) AS transcript_snippet,
               snippet(meeting_fts, 3, '<mark>', '</mark>', '...', 12) AS summary_snippet,
               bm25(meeting_fts) AS rank
        FROM meeting_fts
        JOIN videos v ON v.id = meeting_fts.video_id
        WHERE meeting_fts MATCH ?
        ORDER BY rank LIMIT ?
        """,
        (query, limit),
    ).fetchall()
    return [dict(r) for r in rows]
