"""Tests for src/notify.py: rules, sounds, click URLs, groups, kill-switch."""

from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def enable_notify(monkeypatch):
    """Counteract autouse fixture so we can test the real subprocess path."""
    monkeypatch.delenv("MEETSCRIBE_DISABLE_NOTIFICATIONS", raising=False)


@pytest.mark.parametrize("event_type", [
    "queued", "processing_started", "stage_change", "cancelled", "unknown_event",
])
def test_silent_events_do_not_call_subprocess(enable_notify, event_type):
    from src.notify import notify_event
    with patch("src.notify.subprocess.run") as mock_run:
        notify_event(event_type, video_path=Path("/x/y.mp4"))
    mock_run.assert_not_called()


def test_disable_env_var_skips_subprocess(monkeypatch):
    """When MEETSCRIBE_DISABLE_NOTIFICATIONS=1, no subprocess invocation."""
    monkeypatch.setenv("MEETSCRIBE_DISABLE_NOTIFICATIONS", "1")
    from src.notify import notify_event
    with patch("src.notify.subprocess.run") as mock_run:
        # Even an event that *would* notify must be suppressed.
        notify_event("done", video_path=Path("/x/y.mp4"),
                     output_path=Path("/out/y.md"), video_id=1)
    mock_run.assert_not_called()


def _captured_argv(mock_run):
    """Extract the argv passed to the most recent subprocess.run call."""
    assert mock_run.call_count == 1, f"expected 1 call, got {mock_run.call_count}"
    args, kwargs = mock_run.call_args
    return args[0]


def test_done_uses_glass_sound_and_md_url(enable_notify):
    from src.notify import notify_event
    with patch("src.notify.subprocess.run") as mock_run:
        notify_event(
            "done",
            video_id=42,
            video_path=Path("/v/meeting.mp4"),
            output_path=Path("/out/2026-05-02-meeting/transcript.md"),
        )
    argv = _captured_argv(mock_run)
    assert argv[0] == "terminal-notifier"
    assert "-sound" in argv and argv[argv.index("-sound") + 1] == "Glass"
    assert "-open" in argv
    url = argv[argv.index("-open") + 1]
    assert url == "file:///out/2026-05-02-meeting/transcript.md"
    assert "-group" in argv and argv[argv.index("-group") + 1] == "meetscribe-42"


def test_done_title_includes_video_name(enable_notify):
    from src.notify import notify_event
    with patch("src.notify.subprocess.run") as mock_run:
        notify_event("done", video_id=1, video_path=Path("/v/meeting.mp4"),
                     output_path=Path("/o/m.md"))
    argv = _captured_argv(mock_run)
    msg = argv[argv.index("-message") + 1]
    assert "meeting.mp4" in msg


@pytest.mark.parametrize("event_type, expected_title_fragment", [
    ("failed", "ОШИБКА"),
    ("invalid", "Пропущен"),
    ("stability_timeout", "таймаут"),
])
def test_failure_events_use_basso_and_parent_dir(
    enable_notify, event_type, expected_title_fragment
):
    from src.notify import notify_event
    with patch("src.notify.subprocess.run") as mock_run:
        notify_event(event_type, video_id=7, video_path=Path("/v/meeting.mp4"))
    argv = _captured_argv(mock_run)
    assert argv[argv.index("-sound") + 1] == "Basso"
    assert argv[argv.index("-open") + 1] == "file:///v/"
    assert argv[argv.index("-group") + 1] == "meetscribe-7"
    msg = argv[argv.index("-message") + 1]
    assert expected_title_fragment in msg
    assert "meeting.mp4" in msg


def test_rate_limited_uses_funk_and_watch_dir(enable_notify, monkeypatch, tmp_path):
    monkeypatch.setenv("WATCH_DIR", str(tmp_path))
    from src.notify import notify_event
    with patch("src.notify.subprocess.run") as mock_run:
        notify_event("rate_limited", backend="groq", retry_after=45)
    argv = _captured_argv(mock_run)
    assert argv[argv.index("-sound") + 1] == "Funk"
    assert argv[argv.index("-open") + 1] == f"file://{tmp_path}/"
    assert argv[argv.index("-group") + 1] == "meetscribe-rate-limit-groq"


def test_rate_limited_title_includes_backend_and_retry(enable_notify, tmp_path, monkeypatch):
    monkeypatch.setenv("WATCH_DIR", str(tmp_path))
    from src.notify import notify_event
    with patch("src.notify.subprocess.run") as mock_run:
        notify_event("rate_limited", backend="groq", retry_after=45)
    argv = _captured_argv(mock_run)
    msg = argv[argv.index("-message") + 1]
    assert "groq" in msg
    assert "45" in msg


def test_subprocess_failure_swallowed(enable_notify):
    """terminal-notifier missing or crashing must not break the daemon."""
    from src.notify import notify_event
    with patch("src.notify.subprocess.run", side_effect=FileNotFoundError):
        # Must not raise.
        notify_event("done", video_id=1, video_path=Path("/v/x.mp4"),
                     output_path=Path("/o/x.md"))


def test_done_without_output_path_omits_open_arg(enable_notify):
    """If output_path is None, no -open URL is attached but banner still emits."""
    from src.notify import notify_event
    with patch("src.notify.subprocess.run") as mock_run:
        notify_event("done", video_id=1, video_path=Path("/v/x.mp4"),
                     output_path=None)
    argv = _captured_argv(mock_run)
    assert "-open" not in argv
    # Banner still has title + sound.
    assert argv[argv.index("-sound") + 1] == "Glass"


def test_failed_without_video_path_omits_open_arg(enable_notify):
    from src.notify import notify_event
    with patch("src.notify.subprocess.run") as mock_run:
        notify_event("failed", video_id=1, video_path=None)
    argv = _captured_argv(mock_run)
    assert "-open" not in argv


def test_group_falls_back_to_generic_when_no_video_or_backend(enable_notify):
    from src.notify import notify_event
    with patch("src.notify.subprocess.run") as mock_run:
        # 'failed' with no video_id, no backend → group "meetscribe"
        notify_event("failed", video_path=Path("/v/x.mp4"))
    argv = _captured_argv(mock_run)
    assert argv[argv.index("-group") + 1] == "meetscribe"
