"""SwiftBar plugin support: refresh trigger + state.db render."""

import logging
import os
import subprocess

log = logging.getLogger(__name__)

REFRESH_URL = "swiftbar://refreshplugin?name=meetscribe"


def notify_swiftbar_refresh() -> None:
    """Trigger SwiftBar to re-execute the meetscribe plugin immediately.

    Best-effort: if SwiftBar isn't installed or `open` fails, log warning.
    Set MEETSCRIBE_DISABLE_SWIFTBAR=1 to skip (used in tests).
    """
    if os.environ.get("MEETSCRIBE_DISABLE_SWIFTBAR") == "1":
        return
    try:
        subprocess.run(
            ["open", REFRESH_URL],
            capture_output=True, timeout=2,
        )
    except Exception as e:
        log.debug("swiftbar refresh failed: %s", e)


import shlex
import time
from datetime import datetime
from pathlib import Path

from src import state

STAGE_ICONS = {
    "transcribe": "waveform",
    "align": "text.alignleft",
    "diarize": "person.2.wave.2",
    "summary": "sparkles",
}

PROJECT_ROOT = Path(__file__).parent.parent
MEETSCRIBE_BIN = str(PROJECT_ROOT / ".venv" / "bin" / "meetscribe")


def _fmt_elapsed(start_ts):
    if start_ts is None:
        return "-"
    elapsed = int(time.time()) - start_ts
    return f"{elapsed // 60}m {elapsed % 60}s"


def render() -> str:
    """Render SwiftBar plugin output by reading state.db."""
    lines = []
    with state.connection() as conn:
        active = conn.execute(
            "SELECT * FROM videos WHERE state = 'processing' "
            "ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        queued_count = conn.execute(
            "SELECT COUNT(*) FROM videos WHERE state = 'queued'"
        ).fetchone()[0]
        queued_list = conn.execute(
            "SELECT id, path FROM videos WHERE state = 'queued' "
            "ORDER BY detected_at LIMIT 5"
        ).fetchall()
        failed_count = conn.execute(
            "SELECT COUNT(*) FROM videos WHERE state = 'failed'"
        ).fetchone()[0]
        failed_list = conn.execute(
            "SELECT id, path, last_error FROM videos WHERE state = 'failed' "
            "ORDER BY updated_at DESC LIMIT 5"
        ).fetchall()
        done_list = conn.execute(
            "SELECT id, path, output_path FROM videos WHERE state = 'done' "
            "ORDER BY completed_at DESC LIMIT 5"
        ).fetchall()
        rate_limited = conn.execute(
            "SELECT backend, until_ts FROM rate_limits "
            "WHERE until_ts > strftime('%s','now') ORDER BY until_ts DESC LIMIT 1"
        ).fetchone()
        total_done = conn.execute(
            "SELECT COUNT(*) FROM videos WHERE state = 'done'"
        ).fetchone()[0]

    if active is not None:
        stage = active["current_stage"] or "transcribe"
        icon = STAGE_ICONS.get(stage, "waveform")
        step_map = {"transcribe": 1, "align": 2, "diarize": 3, "summary": 4}
        step = step_map.get(stage, 1)
        lines.append(f"{step}/4 | sfimage={icon} color=#4CAF50")
    elif rate_limited is not None:
        until = datetime.fromtimestamp(rate_limited["until_ts"]).strftime("%H:%M")
        lines.append(f"Rate-limited {until} | sfimage=clock color=#FF9800")
    elif queued_count > 0:
        lines.append(f"{queued_count} queued | sfimage=clock color=#FFC107")
    elif failed_count > 0:
        lines.append(f"{failed_count} failed | sfimage=exclamationmark.triangle color=#F44336")
    else:
        lines.append("| sfimage=text.alignleft color=#888888")

    lines.append("---")

    if active is not None:
        lines.append("Meetscribe - Processing | size=14 color=#4CAF50")
        lines.append(f"{Path(active['path']).name} | size=12")
        lines.append(f"Stage: {active['current_stage'] or '?'} | size=12 color=#4CAF50")
        if active["started_at"]:
            lines.append(f"Elapsed: {_fmt_elapsed(active['started_at'])} | size=11 color=#888888")
        lines.append(
            f"Cancel | bash={MEETSCRIBE_BIN} param1=cancel param2={active['id']} "
            f"terminal=false refresh=true color=#FF6B6B"
        )
    else:
        lines.append("Meetscribe (idle) | size=14 color=#888888")

    if rate_limited is not None:
        until = datetime.fromtimestamp(rate_limited["until_ts"]).strftime("%H:%M")
        lines.append("---")
        lines.append(f"Rate-limited: {rate_limited['backend']} until {until} | color=#FF9800 size=11")

    if queued_count > 0:
        lines.append("---")
        lines.append(f"Queue ({queued_count}) | size=12 color=#FFC107")
        for row in queued_list:
            name = Path(row["path"]).name
            lines.append(f"  {name} | size=10 color=#888888")
            lines.append(
                f"  -- Skip | bash={MEETSCRIBE_BIN} param1=skip param2={row['id']} "
                f"terminal=false refresh=true alternate=true"
            )

    if failed_count > 0:
        lines.append("---")
        lines.append(f"Failed ({failed_count}) | size=12 color=#F44336")
        for row in failed_list:
            name = Path(row["path"]).name
            err = (row["last_error"] or "")[:40]
            lines.append(f"  {name}: {err} | size=10 color=#888888")
            lines.append(
                f"  Retry | bash={MEETSCRIBE_BIN} param1=retry param2={row['id']} "
                f"terminal=false refresh=true"
            )

    if done_list:
        lines.append("---")
        lines.append("Recent done | size=11 color=#888888")
        for row in done_list:
            name = Path(row["path"]).name
            lines.append(f"  {name} | size=10 color=#888888")
            if row["output_path"]:
                lines.append(
                    f"  Open | bash=open param1={shlex.quote(row['output_path'])} terminal=false"
                )

    lines.append("---")
    lines.append(f"Total processed: {total_done} | size=11 color=#888888")
    lines.append("---")
    lines.append(
        f"Restart watcher | bash={MEETSCRIBE_BIN} param1=daemon param2=restart "
        f"terminal=false refresh=true"
    )
    log_path = PROJECT_ROOT / ".logs" / "watcher.log"
    if log_path.exists():
        lines.append(f"Open watcher.log | bash=open param1=-a param2=Console param3={log_path} terminal=false")
    worker_log = PROJECT_ROOT / ".logs" / "worker.log"
    if worker_log.exists():
        lines.append(f"Open worker.log | bash=open param1=-a param2=Console param3={worker_log} terminal=false")

    return "\n".join(lines) + "\n"
