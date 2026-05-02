"""User-facing notification facade.

Single source of truth for terminal-notifier invocations. Caller passes an
event_type; the rules table decides whether to emit, with what sound, and
what URL to attach as the click target. Callers must never invoke
terminal-notifier directly.
"""

import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
ICON_PATH = PROJECT_ROOT / "assets" / "icon.png"


@dataclass(frozen=True)
class _Rule:
    sound: str
    title_template: str
    target: str  # one of: "parent_dir", "watch_dir", "output_md", "none"


_RULES: dict[str, _Rule] = {
    "stability_timeout": _Rule("Basso", "ОШИБКА: таймаут стабилизации: {name}", "parent_dir"),
    "invalid":           _Rule("Basso", "Пропущен битый/короткий файл: {name}", "parent_dir"),
    "failed":            _Rule("Basso", "ОШИБКА: {name}", "parent_dir"),
    "rate_limited":      _Rule("Funk",  "Rate-limited: {backend} ({retry_after}s)", "watch_dir"),
    "done":              _Rule("Glass", "Готово: {name}", "output_md"),
}


def notify_event(
    event_type: str,
    *,
    video_id: int | None = None,
    video_path: Path | None = None,
    output_path: Path | None = None,
    backend: str | None = None,
    retry_after: int | None = None,
) -> None:
    """Emit a notification for `event_type` if the rules table says so.

    Silent event types and unknown events return without side-effects.
    Subprocess errors are swallowed (best-effort).
    """
    if os.environ.get("MEETSCRIBE_DISABLE_NOTIFICATIONS") == "1":
        return
    rule = _RULES.get(event_type)
    if rule is None:
        return
    title = _format_title(rule.title_template, video_path, backend, retry_after)
    url = _resolve_target_url(rule.target, video_path, output_path)
    group = _resolve_group(event_type, video_id, backend)
    _invoke_terminal_notifier(title, rule.sound, group, url)


def _format_title(template: str, video_path: Path | None,
                  backend: str | None, retry_after: int | None) -> str:
    name = video_path.name if video_path else ""
    return template.format(
        name=name,
        backend=backend or "",
        retry_after=retry_after or 0,
    )


def _resolve_target_url(target: str, video_path: Path | None,
                        output_path: Path | None) -> str | None:
    if target == "parent_dir" and video_path:
        return f"file://{video_path.parent}/"
    if target == "output_md" and output_path:
        return f"file://{output_path}"
    if target == "watch_dir":
        watch_dir = Path(os.environ.get("WATCH_DIR", "~/Videos/OBS")).expanduser()
        return f"file://{watch_dir}/"
    return None


def _resolve_group(event_type: str, video_id: int | None,
                   backend: str | None) -> str:
    if event_type == "rate_limited" and backend:
        return f"meetscribe-rate-limit-{backend}"
    if video_id is not None:
        return f"meetscribe-{video_id}"
    return "meetscribe"


def _invoke_terminal_notifier(title: str, sound: str, group: str,
                              url: str | None) -> None:
    cmd = [
        "terminal-notifier", "-title", "Meetscribe",
        "-message", title, "-sound", sound, "-group", group,
        "-contentImage", str(ICON_PATH), "-appIcon", str(ICON_PATH),
    ]
    if url:
        cmd += ["-open", url]
    try:
        subprocess.run(cmd, timeout=5, capture_output=True)
    except Exception as e:
        log.debug("notify failed: %s", e)
