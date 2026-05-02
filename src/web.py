"""Minimal local-only web UI for meeting history search.

Stdlib http.server bound to 127.0.0.1. Two endpoints:
  GET /                serves a single HTML page with vanilla JS
  GET /api/videos      JSON list filtered by query params

Started by `meetscribe web`. Not a daemon - lives in the foreground;
Ctrl+C ends it. Reads state.db via the existing src.state.connection().
"""

from __future__ import annotations

import os
from pathlib import Path

from src import state


def _output_dir() -> Path:
    return Path(os.environ.get("OUTPUT_DIR", "~/docs/video")).expanduser()


def search_videos(
    conn,
    query: str = "",
    state_filter: str = "",
    from_ts: int | None = None,
    to_ts: int | None = None,
    limit: int = 200,
) -> list[dict]:
    """Run the history search SQL. Returns list of dicts (one per video).

    Sanitizes output_path: rows whose output_path lies outside OUTPUT_DIR
    have that field set to None so the UI hides the file:// link.
    """
    rows = conn.execute(
        """
        SELECT id, path, state, detected_at, completed_at,
               output_path, backend_used, duration_sec
        FROM videos
        WHERE (? = '' OR path LIKE ? OR output_path LIKE ?)
          AND (? = '' OR state = ?)
          AND (? IS NULL OR detected_at >= ?)
          AND (? IS NULL OR detected_at <= ?)
        ORDER BY detected_at DESC LIMIT ?
        """,
        (
            query, f"%{query}%", f"%{query}%",
            state_filter, state_filter,
            from_ts, from_ts,
            to_ts, to_ts,
            limit,
        ),
    ).fetchall()

    out_root = str(_output_dir())
    clean: list[dict] = []
    for row in rows:
        d = dict(row)
        op = d.get("output_path")
        if op is not None and not str(op).startswith(out_root):
            d["output_path"] = None
        clean.append(d)
    return clean


import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs


_HTML = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"/>
<title>meetscribe history</title>
<style>
body { font-family: -apple-system, sans-serif; margin: 2rem; max-width: 1100px; }
h1 { font-size: 1.4rem; }
.filters { display: flex; gap: 1rem; flex-wrap: wrap; margin: 1rem 0; }
.filters input, .filters select { padding: 0.4rem; font-size: 0.9rem; }
table { width: 100%; border-collapse: collapse; }
th, td { border-bottom: 1px solid #ddd; padding: 0.5rem 0.75rem;
         text-align: left; font-size: 0.9rem; }
th { background: #f7f7f7; font-weight: 600; }
tr:hover td { background: #fafafa; }
.state-done { color: #2a7; }
.state-failed { color: #c33; }
.state-queued, .state-processing { color: #888; }
a { color: #06c; text-decoration: none; }
a:hover { text-decoration: underline; }
.empty { text-align: center; color: #888; padding: 2rem; }
</style>
</head><body>
<h1>meetscribe history</h1>
<div class="filters">
  <input type="text" id="q" placeholder="Search filename..." style="flex: 1; min-width: 200px;"/>
  <select id="state">
    <option value="">All states</option>
    <option value="done">done</option>
    <option value="failed">failed</option>
    <option value="invalid">invalid</option>
    <option value="cancelled">cancelled</option>
    <option value="queued">queued</option>
    <option value="processing">processing</option>
  </select>
  <input type="date" id="from" title="From date"/>
  <input type="date" id="to" title="To date"/>
</div>
<table>
  <thead><tr>
    <th>Date</th><th>File</th><th>State</th>
    <th>Duration</th><th>Backend</th><th>Output</th>
  </tr></thead>
  <tbody id="results"><tr><td class="empty" colspan="6">Loading...</td></tr></tbody>
</table>
<script>
function fmtDate(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  return d.toISOString().slice(0, 16).replace("T", " ");
}
function fmtDuration(secs) {
  if (!secs) return "";
  const m = Math.floor(secs / 60);
  return m < 60 ? `${m}m` : `${Math.floor(m/60)}h ${m%60}m`;
}
function basename(p) {
  if (!p) return "";
  return p.split("/").pop();
}
async function refresh() {
  const params = new URLSearchParams();
  const q = document.getElementById("q").value.trim();
  const st = document.getElementById("state").value;
  const fr = document.getElementById("from").value;
  const to = document.getElementById("to").value;
  if (q) params.set("q", q);
  if (st) params.set("state", st);
  if (fr) params.set("from", Math.floor(new Date(fr).getTime() / 1000));
  if (to) params.set("to", Math.floor(new Date(to + "T23:59:59").getTime() / 1000));
  const resp = await fetch("/api/videos?" + params.toString());
  const data = await resp.json();
  const tbody = document.getElementById("results");
  if (data.length === 0) {
    tbody.innerHTML = '<tr><td class="empty" colspan="6">No videos match.</td></tr>';
    return;
  }
  tbody.innerHTML = data.map(v => `
    <tr>
      <td>${fmtDate(v.detected_at)}</td>
      <td>${basename(v.path)}</td>
      <td class="state-${v.state}">${v.state}</td>
      <td>${fmtDuration(v.duration_sec)}</td>
      <td>${v.backend_used || ""}</td>
      <td>${v.output_path
            ? `<a href="file://${v.output_path}" target="_blank">open</a>`
            : ""}</td>
    </tr>`).join("");
}
["q", "state", "from", "to"].forEach(id => {
  const el = document.getElementById(id);
  el.addEventListener("input", refresh);
  el.addEventListener("change", refresh);
});
refresh();
</script>
</body></html>
"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        url = urlparse(self.path)
        if url.path == "/":
            self._send(200, "text/html; charset=utf-8", _HTML.encode("utf-8"))
            return
        if url.path == "/api/videos":
            params = parse_qs(url.query)
            try:
                payload = self._search(params)
            except Exception as e:
                self._send(500, "application/json",
                           json.dumps({"error": str(e)}).encode("utf-8"))
                return
            self._send(200, "application/json",
                       json.dumps(payload).encode("utf-8"))
            return
        self._send(404, "text/plain", b"not found")

    def log_message(self, fmt: str, *args) -> None:  # silence default access log
        return

    def _send(self, status: int, ctype: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _search(self, params: dict[str, list[str]]) -> list[dict]:
        q = params.get("q", [""])[0]
        st = params.get("state", [""])[0]
        from_ts = params.get("from", [None])[0]
        to_ts = params.get("to", [None])[0]
        from_ts = int(from_ts) if from_ts else None
        to_ts = int(to_ts) if to_ts else None
        with state.connection() as conn:
            return search_videos(conn, q, st, from_ts, to_ts)


_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8123


def serve(host: str = _DEFAULT_HOST, port: int = _DEFAULT_PORT) -> None:
    """Block forever serving the dashboard. Ctrl+C exits cleanly."""
    from http.server import HTTPServer
    httpd = HTTPServer((host, port), _Handler)
    print(f"Open http://{host}:{port}/ in your browser. Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        httpd.server_close()
