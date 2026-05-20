-- Full-text search index over meeting transcripts and summaries.
-- video_id is UNINDEXED so it can be filtered/joined without participating in the FTS scan.
-- folder_name keeps a copy of the output folder basename for prefix queries
-- (helps finding meetings even when only a fragment of the date or topic is known).

CREATE VIRTUAL TABLE meeting_fts USING fts5(
    video_id UNINDEXED,
    folder_name,
    transcript,
    summary,
    tokenize = 'unicode61'
);

INSERT INTO schema_version VALUES (2);
