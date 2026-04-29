-- Phase 3a initial schema for meetscribe state tracking.
-- Defines all tables and columns used across phases 3a-3f.
-- Phase 3a writes only a subset; later phases use the rest without further migrations.

PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE schema_version (version INTEGER PRIMARY KEY);
INSERT INTO schema_version VALUES (1);

CREATE TABLE videos (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    path                TEXT NOT NULL UNIQUE,
    detected_at         INTEGER NOT NULL,
    size_bytes          INTEGER,
    duration_sec        REAL,

    state               TEXT NOT NULL CHECK (state IN (
                            'detected', 'waiting_stable', 'queued', 'processing',
                            'done', 'failed', 'failed_max', 'skipped',
                            'cancelled', 'invalid'
                        )),
    current_stage       TEXT CHECK (current_stage IN ('transcribe','align','diarize','summary')),
    progress            REAL CHECK (progress IS NULL OR (progress >= 0 AND progress <= 1)),

    backend_used        TEXT,
    output_path         TEXT,
    attempts_count      INTEGER DEFAULT 0,
    last_error          TEXT,
    started_at          INTEGER,
    completed_at        INTEGER,
    updated_at          INTEGER NOT NULL,

    partial_data        BLOB,
    partial_stage       TEXT CHECK (partial_stage IN ('transcribe','align','diarize')),

    summary_edited_at   INTEGER,
    next_attempt_after  INTEGER
);

CREATE INDEX idx_videos_state           ON videos(state);
CREATE INDEX idx_videos_updated         ON videos(updated_at DESC);
CREATE INDEX idx_videos_next_attempt    ON videos(next_attempt_after) WHERE next_attempt_after IS NOT NULL;

CREATE TABLE attempts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id        INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    attempt_num     INTEGER NOT NULL,
    backend         TEXT NOT NULL,
    started_at      INTEGER NOT NULL,
    completed_at    INTEGER,
    exit_code       INTEGER,
    stage_reached   TEXT,
    error_message   TEXT,
    log_path        TEXT,
    UNIQUE(video_id, attempt_num)
);

CREATE INDEX idx_attempts_video     ON attempts(video_id);
CREATE INDEX idx_attempts_started   ON attempts(started_at DESC);

CREATE TABLE events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id        INTEGER REFERENCES videos(id) ON DELETE CASCADE,
    ts              INTEGER NOT NULL,
    event_type      TEXT NOT NULL,
    details         TEXT
);

CREATE INDEX idx_events_video_ts    ON events(video_id, ts DESC);
CREATE INDEX idx_events_ts          ON events(ts DESC);

CREATE TABLE rate_limits (
    backend     TEXT PRIMARY KEY,
    until_ts    INTEGER NOT NULL,
    reason      TEXT
);
