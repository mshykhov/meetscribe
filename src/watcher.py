"""meetscribed-watcher daemon.

Single-instance Python daemon launched by launchd com.myron.meetscribe.watcher.
Listens FSEvent on WATCH_DIR via watchdog. Drains a serial queue: stability check,
state.db transitions, subprocess to src.process per video.

Phase 3b: subprocess.run is sync (blocks worker). Phase 3c switches to
launchctl-on-demand worker.
"""

import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from src import state
from src.notify import notify_event
from src.swiftbar import notify_swiftbar_refresh

log = logging.getLogger("meetscribed-watcher")

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".flv", ".avi"}
TERMINAL_STATES = {"done", "failed_max", "skipped", "processing"}


def _is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS


def _eligible_for_processing(path: Path) -> bool:
    """Return True if state.db says this file should be (re)processed.

    Eligible: never seen, OR in non-terminal state (detected, waiting_stable,
    queued, failed, cancelled, invalid).
    Not eligible: done, failed_max, skipped, processing.
    """
    abs_path = str(path.resolve())
    with state.connection() as conn:
        video = state.get_video(conn, abs_path)
    if video is None:
        return True
    return video["state"] not in TERMINAL_STATES


def _initial_scan(watch_dir: Path) -> list[str]:
    """Scan WATCH_DIR for eligible video files. Returns absolute paths."""
    if not watch_dir.exists():
        return []
    paths = []
    for entry in os.scandir(watch_dir):
        if not entry.is_file():
            continue
        path = Path(entry.path)
        if not _is_video(path):
            continue
        if _eligible_for_processing(path):
            paths.append(str(path.resolve()))
    return paths


STABILITY_INTERVAL = 10
STABILITY_REQUIRED = 3
LSOF_POLL_INTERVAL = 10
LSOF_TIMEOUT = 3600
SIZE_TIMEOUT = 3600

MIN_DURATION_SEC = 5
MAX_DURATION_SEC = 4 * 3600


def _is_open(path: Path) -> bool:
    """Return True if any process holds path open (lsof returncode 0)."""
    try:
        result = subprocess.run(
            ["lsof", "--", str(path)], capture_output=True, timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _get_duration(path: Path) -> float:
    """Return duration in seconds via ffprobe; 0 on failure."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        return float(result.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError, FileNotFoundError):
        return 0.0


def _validate(path: Path) -> tuple[bool, str | None]:
    """Check duration is within bounds. Returns (ok, reason)."""
    if not path.exists():
        return False, "file does not exist"
    duration = _get_duration(path)
    if duration < MIN_DURATION_SEC:
        return False, f"too short ({duration:.1f}s, min {MIN_DURATION_SEC}s)"
    if duration > MAX_DURATION_SEC:
        return False, f"too long ({duration:.0f}s, max {MAX_DURATION_SEC}s)"
    return True, None


def _wait_for_stable(path: Path, video_id: int, shutdown: threading.Event) -> bool:
    """Wait until file is closed (lsof) AND size stable for 3 samples.

    Marks state='waiting_stable' on entry. Returns True if stable, False on
    timeout or shutdown.
    """
    with state.connection() as conn:
        state.transition_state(conn, video_id, "waiting_stable")
    notify_swiftbar_refresh()

    deadline = time.time() + LSOF_TIMEOUT
    closed = False
    while time.time() < deadline and not shutdown.is_set():
        if not _is_open(path):
            closed = True
            break
        time.sleep(LSOF_POLL_INTERVAL)
    if not closed or shutdown.is_set():
        return False

    prev_size = -1
    stable_count = 0
    deadline = time.time() + SIZE_TIMEOUT
    while stable_count < STABILITY_REQUIRED and time.time() < deadline and not shutdown.is_set():
        cur_size = path.stat().st_size if path.exists() else 0
        if cur_size == prev_size and cur_size > 0:
            stable_count += 1
        else:
            stable_count = 0
        prev_size = cur_size
        if stable_count < STABILITY_REQUIRED:
            time.sleep(STABILITY_INTERVAL)
    return stable_count >= STABILITY_REQUIRED and not shutdown.is_set()


def _process_one(path_str: str, shutdown: threading.Event) -> None:
    """Per-video orchestrator: dedup, stability, validate, dispatch subprocess."""
    path = Path(path_str)
    if not _eligible_for_processing(path):
        log.info("skipping (not eligible): %s", path_str)
        return

    abs_path = str(path.resolve())
    with state.connection() as conn:
        size_bytes = path.stat().st_size if path.exists() else None
        video_id = state.record_video_seen(
            conn, path=abs_path, detected_at=int(time.time()),
            size_bytes=size_bytes, duration_sec=None,
        )

    if not _wait_for_stable(path, video_id, shutdown):
        with state.connection() as conn:
            state.transition_state(conn, video_id, "failed",
                                   extra_event_details={"reason": "stability_timeout"})
        notify_swiftbar_refresh()
        notify_event("stability_timeout", video_id=video_id, video_path=path)
        return

    if shutdown.is_set():
        return

    ok, reason = _validate(path)
    if not ok:
        with state.connection() as conn:
            state.transition_state(conn, video_id, "invalid",
                                   extra_event_details={"reason": reason})
        notify_swiftbar_refresh()
        notify_event("invalid", video_id=video_id, video_path=path)
        return

    with state.connection() as conn:
        state.transition_state(conn, video_id, "queued")
    notify_swiftbar_refresh()

    try:
        subprocess.run(
            ["launchctl", "start", "com.myron.meetscribe.worker"],
            capture_output=True, timeout=5,
        )
    except Exception as e:
        log.warning("failed to launchctl start worker: %s", e)


import queue as queue_module
import signal

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


class WatchHandler(FileSystemEventHandler):
    """watchdog event handler. Enqueues eligible video paths."""

    def __init__(self, queue: queue_module.Queue, watch_dir: Path) -> None:
        super().__init__()
        self._queue = queue
        self._watch_dir = watch_dir

    def _enqueue_if_eligible(self, src_path: str) -> None:
        path = Path(src_path)
        if not _is_video(path):
            return
        if not _eligible_for_processing(path):
            return
        self._queue.put(str(path.resolve()))
        log.info("enqueued: %s", src_path)

    def on_created(self, event) -> None:
        if event.is_directory:
            return
        self._enqueue_if_eligible(event.src_path)

    def on_moved(self, event) -> None:
        if event.is_directory:
            return
        self._enqueue_if_eligible(event.dest_path)


def _worker_loop(q: queue_module.Queue, shutdown: threading.Event) -> None:
    """Drain the queue serially. One video at a time."""
    while not shutdown.is_set():
        try:
            path = q.get(timeout=1.0)
        except queue_module.Empty:
            continue
        try:
            _process_one(path, shutdown)
        except Exception:
            log.exception("worker error on %s", path)
        finally:
            q.task_done()


def _resolve_watch_dir() -> Path:
    raw = os.environ.get("WATCH_DIR", "~/Videos/OBS")
    return Path(raw).expanduser()


def main() -> None:
    """Daemon entry point."""
    from dotenv import load_dotenv
    project_root = Path(__file__).parent.parent
    load_dotenv(project_root / ".env")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    watch_dir = _resolve_watch_dir()
    log.info("starting meetscribed-watcher; watch_dir=%s", watch_dir)
    watch_dir.mkdir(parents=True, exist_ok=True)

    with state.connection() as conn:
        from src.state import runner
        runner.apply_migrations(conn)
        state.record_event(conn, None, "watcher_started", {"watch_dir": str(watch_dir)})

    shutdown = threading.Event()

    def _handle_signal(signum, frame):
        log.info("received signal %d, shutting down", signum)
        shutdown.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    q: queue_module.Queue = queue_module.Queue()

    for path in _initial_scan(watch_dir):
        q.put(path)
        log.info("initial scan enqueued: %s", path)

    observer = Observer()
    observer.schedule(WatchHandler(q, watch_dir), str(watch_dir), recursive=False)
    observer.start()
    log.info("observer started")

    worker_thread = threading.Thread(target=_worker_loop, args=(q, shutdown), daemon=False)
    worker_thread.start()
    log.info("worker started")

    while not shutdown.is_set():
        time.sleep(1)

    log.info("shutdown signal received; stopping observer")
    observer.stop()
    observer.join(timeout=10)

    log.info("waiting for worker to finish current task (may take minutes)")
    worker_thread.join(timeout=900)

    with state.connection() as conn:
        state.record_event(conn, None, "watcher_stopped")

    log.info("clean exit")


if __name__ == "__main__":
    main()
