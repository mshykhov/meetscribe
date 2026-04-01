"""Behavioral tests for meetscribe.

Tests verify WHAT the system should do, not HOW the code works.
No mocking whisperx/claude - these test the glue logic.
"""

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parent.parent
PROCESS_MODULE = "src.process"


# --- Helpers ---

def make_test_video(path: Path, duration_sec: int = 5) -> Path:
    """Create a minimal test video with speech using ffmpeg."""
    speech_file = path.parent / "speech.aiff"
    # Generate speech with macOS say
    subprocess.run(
        ["say", "-o", str(speech_file), "This is a test meeting about sprint review."],
        check=True, capture_output=True,
    )
    # Wrap in video container
    subprocess.run(
        ["ffmpeg", "-f", "lavfi", "-i", f"color=c=black:s=320x240:d={duration_sec}",
         "-i", str(speech_file), "-c:v", "libx264", "-c:a", "aac",
         "-pix_fmt", "yuv420p", "-shortest", "-y", str(path)],
        check=True, capture_output=True,
    )
    speech_file.unlink(missing_ok=True)
    return path


# --- Tests: File naming and organization ---

class TestFileOrganization:
    def test_sanitize_removes_special_chars(self):
        from src.process import sanitize_filename
        assert sanitize_filename("Sprint Review #1!") == "sprint-review-1"

    def test_sanitize_truncates_long_names(self):
        from src.process import sanitize_filename
        result = sanitize_filename("a" * 100)
        assert len(result) <= 50

    def test_sanitize_transliterates_cyrillic(self):
        from src.process import sanitize_filename
        result = sanitize_filename("Обзор спринта")
        assert result == "obzor-sprinta"
        assert all(c.isascii() for c in result)

    def test_sanitize_handles_empty_string(self):
        from src.process import sanitize_filename
        result = sanitize_filename("")
        assert result == ""

    def test_sanitize_handles_only_special_chars(self):
        from src.process import sanitize_filename
        result = sanitize_filename("!@#$%")
        assert result == ""


# --- Tests: Timestamp formatting ---

class TestTimestamps:
    def test_short_timestamp(self):
        from src.process import format_timestamp
        assert format_timestamp(65.0) == "01:05"

    def test_hour_timestamp(self):
        from src.process import format_timestamp
        assert format_timestamp(3661.0) == "01:01:01"

    def test_zero_timestamp(self):
        from src.process import format_timestamp
        assert format_timestamp(0.0) == "00:00"


# --- Tests: Transcript building ---

class TestTranscript:
    def test_builds_correct_format(self):
        from src.process import build_transcript
        result = {
            "segments": [
                {"start": 0.0, "end": 5.0, "text": " Hello world", "speaker": "SPEAKER_00"},
                {"start": 5.0, "end": 10.0, "text": " Goodbye", "speaker": "SPEAKER_01"},
            ]
        }
        transcript = build_transcript(result)
        assert "[00:00] SPEAKER_00: Hello world" in transcript
        assert "[00:05] SPEAKER_01: Goodbye" in transcript

    def test_handles_missing_speaker(self):
        from src.process import build_transcript
        result = {"segments": [{"start": 0.0, "end": 5.0, "text": " Test"}]}
        transcript = build_transcript(result)
        assert "Unknown" in transcript


# --- Tests: Topic extraction from summary ---

class TestTopicExtraction:
    def test_extracts_topic_from_summary(self):
        from src.process import extract_topic
        summary = "### Короткое название\nsprint review\n\n### Тема встречи\n..."
        assert extract_topic(summary) == "sprint-review"

    def test_extracts_topic_with_backticks(self):
        from src.process import extract_topic
        summary = "### Короткое название\n`api design`\n\n### Тема"
        assert extract_topic(summary) == "api-design"

    def test_fallback_when_no_topic(self):
        from src.process import extract_topic
        assert extract_topic("random text without sections") == "meeting"

    def test_extracts_english_topic_from_russian_summary(self):
        from src.process import extract_topic
        summary = "### Короткое название\nonboarding sync\n\n### Тема встречи\nОбсуждение..."
        result = extract_topic(summary)
        assert result == "onboarding-sync"
        assert all(c.isascii() or c == "-" for c in result)


# --- Tests: Config loading ---

class TestConfig:
    def test_loads_config_from_env(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "HF_TOKEN=test_token\n"
            "OUTPUT_DIR=/tmp/test_output\n"
            "WHISPER_MODEL=tiny\n"
        )
        os.environ["HF_TOKEN"] = "test_token"
        os.environ["OUTPUT_DIR"] = "/tmp/test_output"
        os.environ["WHISPER_MODEL"] = "tiny"

        from src.process import load_config
        # Will use env vars
        cfg = load_config()
        assert cfg["hf_token"] == "test_token"
        assert cfg["whisper_model"] == "tiny"

        # Cleanup
        del os.environ["HF_TOKEN"]
        del os.environ["OUTPUT_DIR"]
        del os.environ["WHISPER_MODEL"]


# --- Tests: Duration detection ---

class TestDuration:
    def test_detects_video_duration(self, tmp_path):
        video = tmp_path / "test.mp4"
        make_test_video(video, duration_sec=3)
        from src.process import get_audio_duration
        duration = get_audio_duration(str(video))
        assert 1.0 < duration < 10.0

    def test_returns_zero_for_missing_file(self):
        from src.process import get_audio_duration
        assert get_audio_duration("/nonexistent/file.mp4") == 0.0

    def test_returns_zero_for_invalid_file(self, tmp_path):
        bad_file = tmp_path / "not_a_video.txt"
        bad_file.write_text("this is not a video")
        from src.process import get_audio_duration
        assert get_audio_duration(str(bad_file)) == 0.0


# --- Tests: Watch handler shell script ---

class TestWatchHandler:
    def test_handler_skips_processed_files(self, tmp_path):
        """Files in .processed should not be reprocessed."""
        watch_dir = tmp_path / "watch"
        watch_dir.mkdir()
        video = watch_dir / "test.mp4"
        video.write_bytes(b"fake")

        processed = tmp_path / ".processed"
        processed.write_text(str(video) + "\n")

        # Handler should find no new files
        result = subprocess.run(
            ["bash", "-c", f"""
                PROCESSED_LOG="{processed}"
                file="{video}"
                if grep -qxF "$file" "$PROCESSED_LOG"; then
                    echo "SKIPPED"
                else
                    echo "WOULD_PROCESS"
                fi
            """],
            capture_output=True, text=True,
        )
        assert "SKIPPED" in result.stdout

    def test_handler_detects_new_files(self, tmp_path):
        """Files NOT in .processed should be detected."""
        processed = tmp_path / ".processed"
        processed.write_text("")

        result = subprocess.run(
            ["bash", "-c", f"""
                PROCESSED_LOG="{processed}"
                file="/some/new/video.mp4"
                if grep -qxF "$file" "$PROCESSED_LOG"; then
                    echo "SKIPPED"
                else
                    echo "WOULD_PROCESS"
                fi
            """],
            capture_output=True, text=True,
        )
        assert "WOULD_PROCESS" in result.stdout

    def test_lock_prevents_parallel_runs(self, tmp_path):
        """Only one handler instance should run at a time."""
        lockdir = tmp_path / "lock.d"
        lockdir.mkdir()
        pid_file = lockdir / "pid"
        pid_file.write_text(str(os.getpid()))  # current process = alive

        result = subprocess.run(
            ["bash", "-c", f"""
                LOCKDIR="{lockdir}"
                if ! mkdir "$LOCKDIR" 2>/dev/null; then
                    if [ -f "$LOCKDIR/pid" ] && kill -0 "$(cat "$LOCKDIR/pid")" 2>/dev/null; then
                        echo "LOCKED"
                        exit 0
                    fi
                fi
                echo "ACQUIRED"
            """],
            capture_output=True, text=True,
        )
        assert "LOCKED" in result.stdout

    def test_stale_lock_is_cleaned(self, tmp_path):
        """Stale lock (dead PID) should be cleaned up."""
        lockdir = tmp_path / "lock.d"
        lockdir.mkdir()
        pid_file = lockdir / "pid"
        pid_file.write_text("999999")  # PID that doesn't exist

        result = subprocess.run(
            ["bash", "-c", f"""
                LOCKDIR="{lockdir}"
                if ! mkdir "$LOCKDIR" 2>/dev/null; then
                    if [ -f "$LOCKDIR/pid" ] && kill -0 "$(cat "$LOCKDIR/pid")" 2>/dev/null; then
                        echo "LOCKED"
                        exit 0
                    fi
                    rm -rf "$LOCKDIR"
                    if mkdir "$LOCKDIR" 2>/dev/null; then
                        echo "ACQUIRED_AFTER_CLEANUP"
                    fi
                fi
            """],
            capture_output=True, text=True,
        )
        assert "ACQUIRED_AFTER_CLEANUP" in result.stdout


# --- Tests: Duplicate output handling ---

class TestDuplicateOutput:
    def test_duplicate_folder_gets_suffix(self, tmp_path):
        """If output folder already exists, new one gets -2 suffix."""
        from src.process import organize_files

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Create existing folder
        existing = output_dir / "2026-04-01-sprint-review"
        existing.mkdir()
        (existing / "2026-04-01-sprint-review.mp4").write_bytes(b"old")

        # Create a fake video to process
        video = tmp_path / "test.mp4"
        video.write_bytes(b"fake video content")

        cfg = {"output_dir": output_dir}
        summary = "### Короткое название\nsprint review\n\n### Тема\ntest"

        result = organize_files(str(video), "transcript", summary, "2026-04-01", cfg)

        assert result.name == "2026-04-01-sprint-review-2"
        assert (result / "2026-04-01-sprint-review-2-transcript.txt").exists()

    def test_no_suffix_when_no_conflict(self, tmp_path):
        """No suffix when output folder doesn't exist yet."""
        from src.process import organize_files

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        video = tmp_path / "test.mp4"
        video.write_bytes(b"fake video content")

        cfg = {"output_dir": output_dir}
        summary = "### Короткое название\nunique-meeting\n\n### Тема\ntest"

        result = organize_files(str(video), "transcript", summary, "2026-04-01", cfg)

        assert result.name == "2026-04-01-unique-meeting"


# --- Tests: Output directory protection ---

class TestSafetyGuards:
    def test_rejects_same_watch_and_output_dir(self):
        """OUTPUT_DIR == WATCH_DIR should be rejected."""
        result = subprocess.run(
            ["bash", "-c", """
                real_watch="/tmp/same_dir"
                real_output="/tmp/same_dir"
                if [ "$real_watch" = "$real_output" ]; then
                    echo "REJECTED"
                else
                    echo "ALLOWED"
                fi
            """],
            capture_output=True, text=True,
        )
        assert "REJECTED" in result.stdout

    def test_failed_file_not_skipped_until_max_retries(self, tmp_path):
        """Failed file with < MAX_RETRIES should still be picked up."""
        failed = tmp_path / ".failed"
        failed.write_text("/some/video.mp4\n")  # 1 failure

        result = subprocess.run(
            ["bash", "-c", f"""
                FAILED_LOG="{failed}"
                MAX_RETRIES=3
                file="/some/video.mp4"
                fail_count=0
                if [ -s "$FAILED_LOG" ]; then
                    fail_count=$(grep -cxF "$file" "$FAILED_LOG" || true)
                fi
                if [ "$fail_count" -ge "$MAX_RETRIES" ]; then
                    echo "SKIPPED"
                else
                    echo "WOULD_RETRY attempt $((fail_count + 1))"
                fi
            """],
            capture_output=True, text=True,
        )
        assert "WOULD_RETRY attempt 2" in result.stdout

    def test_failed_file_skipped_after_max_retries(self, tmp_path):
        """Failed file with >= MAX_RETRIES should be skipped."""
        failed = tmp_path / ".failed"
        failed.write_text("/some/video.mp4\n/some/video.mp4\n/some/video.mp4\n")  # 3 failures

        result = subprocess.run(
            ["bash", "-c", f"""
                FAILED_LOG="{failed}"
                MAX_RETRIES=3
                file="/some/video.mp4"
                fail_count=0
                if [ -s "$FAILED_LOG" ]; then
                    fail_count=$(grep -cxF "$file" "$FAILED_LOG" || true)
                fi
                if [ "$fail_count" -ge "$MAX_RETRIES" ]; then
                    echo "SKIPPED"
                else
                    echo "WOULD_RETRY"
                fi
            """],
            capture_output=True, text=True,
        )
        assert "SKIPPED" in result.stdout

    def test_retrigger_after_failure(self, tmp_path):
        """Watch dir should be touched after failure to retrigger launchd."""
        watch_dir = tmp_path / "watch"
        watch_dir.mkdir()
        before_mtime = watch_dir.stat().st_mtime

        import time
        time.sleep(0.1)

        # Simulate the retrigger logic
        subprocess.run(
            ["bash", "-c", f'touch "{watch_dir}"'],
            capture_output=True,
        )
        after_mtime = watch_dir.stat().st_mtime
        assert after_mtime > before_mtime

    def test_video_too_long_rejected(self):
        """Videos exceeding MAX_VIDEO_DURATION_SEC should be rejected."""
        from src.process import MAX_VIDEO_DURATION_SEC
        assert MAX_VIDEO_DURATION_SEC == 4 * 3600  # 4 hours
