"""State tracking via SQLite for meetscribe pipeline.

Public API re-exports; implementation in db.py / runner.py / operations.py.
"""

from src.state import db, runner
from src.state.db import DB_PATH, connect, connection
from src.state.operations import (
    record_video_seen,
    start_attempt,
    set_current_stage,
    complete_attempt,
    fail_attempt,
    list_videos,
    get_video,
    get_attempts,
    get_events,
    transition_state,
    record_event,
    mark_skipped,
    mark_for_retry,
)

__all__ = [
    "db",
    "runner",
    "DB_PATH",
    "connect",
    "connection",
    "record_video_seen",
    "start_attempt",
    "set_current_stage",
    "complete_attempt",
    "fail_attempt",
    "list_videos",
    "get_video",
    "get_attempts",
    "get_events",
    "transition_state",
    "record_event",
    "mark_skipped",
    "mark_for_retry",
]
