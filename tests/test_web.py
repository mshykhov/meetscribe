"""Tests for src/web.py: search_videos pure function + HTTP smoke tests."""

import json
import threading
import urllib.request
import urllib.error
from http.server import HTTPServer
from pathlib import Path

import pytest


def _seed(conn, *, output_dir: str):
    """Insert 4 sample rows covering the search dimensions.

    Schema note: videos table uses `detected_at` (first-seen time) and
    `completed_at`. There is no `created_at`.
    """
    base = output_dir.rstrip("/")
    rows = [
        # (path, output, state, detected_at, completed_at, backend, duration)
        ("/v/standup-2026-04-01.mp4", f"{base}/standup-2026-04-01-summary.md",
         "done", 1711929600, 1711930000, "groq", 600.0),
        ("/v/all-hands-2026-04-15.mp4", f"{base}/all-hands-2026-04-15-summary.md",
         "done", 1713139200, 1713142800, "claude_code", 3600.0),
        ("/v/broken-2026-04-20.mkv", None,
         "failed", 1713571200, 1713571300, "openai", 0.0),
        ("/v/strange-2026-04-25.mp4", "/tmp/elsewhere.md",
         "done", 1714003200, 1714003500, "local", 1200.0),
    ]
    for path, output, st, detected, completed, backend, dur in rows:
        conn.execute(
            "INSERT INTO videos (path, detected_at, state, output_path, "
            "completed_at, backend_used, duration_sec, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (path, detected, st, output, completed, backend, dur, completed),
        )
    conn.commit()


def test_search_returns_all_when_no_filter(conn, tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    _seed(conn, output_dir=str(tmp_path))
    from src.web import search_videos
    rows = search_videos(conn)
    assert len(rows) == 4


def test_search_filters_by_query_substring(conn, tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    _seed(conn, output_dir=str(tmp_path))
    from src.web import search_videos
    rows = search_videos(conn, query="standup")
    paths = [r["path"] for r in rows]
    assert paths == ["/v/standup-2026-04-01.mp4"]


def test_search_filters_by_state(conn, tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    _seed(conn, output_dir=str(tmp_path))
    from src.web import search_videos
    rows = search_videos(conn, state_filter="failed")
    assert len(rows) == 1
    assert rows[0]["state"] == "failed"


def test_search_filters_by_date_range(conn, tmp_path, monkeypatch):
    """from_ts inclusive lower; to_ts inclusive upper."""
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    _seed(conn, output_dir=str(tmp_path))
    from src.web import search_videos
    rows = search_videos(conn, from_ts=1713000000, to_ts=1713600000)
    paths = sorted(r["path"] for r in rows)
    assert paths == ["/v/all-hands-2026-04-15.mp4", "/v/broken-2026-04-20.mkv"]


def test_search_query_matches_output_path(conn, tmp_path, monkeypatch):
    """Query 'all-hands' matches output_path filename of all-hands video."""
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    _seed(conn, output_dir=str(tmp_path))
    from src.web import search_videos
    rows = search_videos(conn, query="all-hands")
    assert len(rows) == 1
    assert "all-hands" in rows[0]["path"]


def test_search_orders_by_created_at_desc(conn, tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    _seed(conn, output_dir=str(tmp_path))
    from src.web import search_videos
    rows = search_videos(conn)
    timestamps = [r["detected_at"] for r in rows]
    assert timestamps == sorted(timestamps, reverse=True)


def test_search_respects_limit(conn, tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    _seed(conn, output_dir=str(tmp_path))
    from src.web import search_videos
    rows = search_videos(conn, limit=2)
    assert len(rows) == 2


def test_search_hides_output_path_outside_output_dir(conn, tmp_path, monkeypatch):
    """Row with output_path=/tmp/elsewhere.md must have output_path=None
    in the response because /tmp is outside OUTPUT_DIR."""
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    _seed(conn, output_dir=str(tmp_path))
    from src.web import search_videos
    rows = search_videos(conn)
    strange = [r for r in rows if r["path"] == "/v/strange-2026-04-25.mp4"]
    assert len(strange) == 1
    assert strange[0]["output_path"] is None


class _LiveServer:
    """Spin up _Handler on a random port for smoke tests."""
    def __init__(self):
        from src.web import _Handler
        self.httpd = HTTPServer(("127.0.0.1", 0), _Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(
            target=self.httpd.serve_forever, daemon=True,
        )
        self.thread.start()

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)


@pytest.fixture
def live_server(conn, tmp_path, monkeypatch):
    """Live server with seeded data and OUTPUT_DIR pointing at tmp_path."""
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    _seed(conn, output_dir=str(tmp_path))
    s = _LiveServer()
    yield s
    s.close()


def test_handler_serves_html_on_root(live_server):
    resp = urllib.request.urlopen(live_server.url("/"))
    assert resp.status == 200
    assert resp.headers.get("Content-Type", "").startswith("text/html")
    body = resp.read().decode("utf-8")
    assert "meetscribe history" in body
    assert "<table>" in body


def test_handler_serves_json_on_api_videos(live_server):
    resp = urllib.request.urlopen(live_server.url("/api/videos"))
    assert resp.status == 200
    assert resp.headers.get("Content-Type", "").startswith("application/json")
    payload = json.loads(resp.read().decode("utf-8"))
    assert isinstance(payload, list)
    assert len(payload) == 4
    assert all("state" in row for row in payload)


def test_handler_serves_404_on_unknown_path(live_server):
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(live_server.url("/unknown"))
    assert excinfo.value.code == 404


def test_handler_filters_via_query_string(live_server):
    resp = urllib.request.urlopen(live_server.url("/api/videos?q=standup"))
    payload = json.loads(resp.read().decode("utf-8"))
    assert len(payload) == 1
    assert "standup" in payload[0]["path"]
