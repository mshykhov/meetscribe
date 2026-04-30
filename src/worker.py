"""meetscribed-worker daemon.

On-demand Python daemon launched by `launchctl start com.myron.meetscribe.worker`.
Drains state.db queue serially via subprocess to src.process. Exits when queue empty.

ProcessType=Interactive in plist for GPU/MLX scheduling priority. Single-instance
guaranteed by launchd (per Label).
"""

import logging
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from src import state

log = logging.getLogger("meetscribed-worker")

PROJECT_ROOT = Path(__file__).parent.parent


def notify(title: str, message: str = "", sound: str = "default") -> None:
    """Wrap terminal-notifier call. Best-effort, swallows errors."""
    icon = PROJECT_ROOT / "assets" / "icon.png"
    try:
        subprocess.run(
            ["terminal-notifier", "-title", "Meetscribe",
             "-message", title + (f": {message}" if message else ""),
             "-sound", sound, "-group", "meetscribe",
             "-contentImage", str(icon), "-appIcon", str(icon)],
            timeout=5, capture_output=True,
        )
    except Exception as e:
        log.debug("notify failed: %s", e)


def _recover_orphans() -> None:
    """Transition any state='processing' videos back to 'queued' (orphans from prev run)."""
    with state.connection() as conn:
        rows = conn.execute("SELECT id, path FROM videos WHERE state='processing'").fetchall()
        for row in rows:
            log.warning("orphan from previous run: %s", row["path"])
            state.transition_state(
                conn, row["id"], "queued",
                extra_event_details={"reason": "orphan_from_prev_run"},
            )


def _pick_next(shutdown: threading.Event) -> dict | None:
    """SELECT next eligible queued video. Returns None if queue empty."""
    if shutdown.is_set():
        return None
    with state.connection() as conn:
        row = conn.execute("""
            SELECT v.* FROM videos v
            LEFT JOIN rate_limits rl ON rl.backend = v.backend_used
            WHERE v.state = 'queued'
              AND (v.next_attempt_after IS NULL OR v.next_attempt_after < strftime('%s','now'))
              AND (rl.until_ts IS NULL OR rl.until_ts < strftime('%s','now'))
            ORDER BY v.detected_at LIMIT 1
        """).fetchone()
    return dict(row) if row else None


def _process_video(video: dict, shutdown: threading.Event) -> None:
    """Run pipeline subprocess for one video."""
    path = video["path"]
    video_id = video["id"]
    notify(f"Обработка {Path(path).name}", "", sound="Blow")

    try:
        result = subprocess.run(
            [sys.executable, "-m", "src.process",
             "--video-id", str(video_id), path],
            cwd=str(PROJECT_ROOT),
        )
    except Exception as e:
        log.exception("subprocess error for %s", path)
        with state.connection() as conn:
            state.transition_state(conn, video_id, "failed",
                                   extra_event_details={"reason": f"subprocess_error: {e}"})
        notify("ОШИБКА запуска pipeline", Path(path).name, sound="Basso")
        return

    if result.returncode == 0:
        notify(f"Готово: {Path(path).name}", "", sound="Glass")
    else:
        with state.connection() as conn:
            row = conn.execute(
                "SELECT state FROM videos WHERE id=?", (video_id,)
            ).fetchone()
        final_state = row["state"] if row else "unknown"
        if final_state == "cancelled":
            notify(f"Отменено: {Path(path).name}", "", sound="default")
        else:
            notify(f"ОШИБКА: {Path(path).name}", "", sound="Basso")


def main() -> None:
    """Daemon entry point."""
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    log.info("starting meetscribed-worker pid=%d", os.getpid())

    with state.connection() as conn:
        from src.state import runner
        runner.apply_migrations(conn)
        state.record_event(conn, None, "worker_started", {"pid": os.getpid()})

    shutdown = threading.Event()

    def _handle_signal(signum, frame):
        log.info("received signal %d, shutting down", signum)
        shutdown.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    _recover_orphans()

    while not shutdown.is_set():
        video = _pick_next(shutdown)
        if video is None:
            log.info("queue drained, exiting")
            break
        _process_video(video, shutdown)

    with state.connection() as conn:
        state.record_event(conn, None, "worker_exited")

    log.info("clean exit")


if __name__ == "__main__":
    main()
