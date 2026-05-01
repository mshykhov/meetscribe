"""OpenAI Whisper API transcription backend.

Replaces local whisperx-mlx transcribe + align steps with a single API call
that returns word-level timestamps directly.
"""

import os
import subprocess
import tempfile
import time
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

from openai import OpenAI, APIConnectionError, APITimeoutError, RateLimitError


class RateLimitedError(Exception):
    """Raised when API returns 429. Carries backend name and retry_after seconds."""

    def __init__(self, backend: str, retry_after_seconds: int, reason: str = ""):
        self.backend = backend
        self.retry_after_seconds = retry_after_seconds
        self.reason = reason
        super().__init__(
            f"Rate limited on {backend}: retry after {retry_after_seconds}s ({reason})"
        )


DEFAULT_RETRY_AFTER_SEC = 300


def _detect_backend(base_url: str | None) -> str:
    """Return 'groq' or 'openai' based on base URL."""
    if base_url and "groq" in base_url.lower():
        return "groq"
    return "openai"


def _parse_retry_after(value: str | None) -> int:
    """Parse Retry-After header. Returns seconds.

    Header may be:
    - integer seconds: '30'
    - HTTP date: 'Wed, 01 May 2026 12:00:00 GMT'
    """
    if not value:
        return DEFAULT_RETRY_AFTER_SEC
    value = value.strip()
    try:
        return max(1, int(value))
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=None)
            now = datetime.now()
        else:
            now = datetime.now(dt.tzinfo)
        delta = (dt - now).total_seconds()
        return max(1, int(delta))
    except (TypeError, ValueError):
        return DEFAULT_RETRY_AFTER_SEC


def extract_audio_to_opus(video_path: Path, output_path: Path) -> Path:
    """Extract audio from video as 32 kbps mono opus.

    Opus at 32 kbps mono fits ~108 minutes in 25 MB (OpenAI API file limit).
    Most meetings <2 hours fit without chunking.
    """
    result = subprocess.run(
        ["ffmpeg", "-i", str(video_path), "-vn",
         "-c:a", "libopus", "-b:a", "32k", "-ac", "1",
         "-y", str(output_path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed (exit {result.returncode}): {result.stderr[-500:]}")
    return output_path


OPENAI_FILE_LIMIT_BYTES = 25 * 1024 * 1024


def validate_audio_size(audio_path: Path) -> None:
    """Raise ValueError if audio exceeds OpenAI 25 MB limit."""
    size = audio_path.stat().st_size
    if size > OPENAI_FILE_LIMIT_BYTES:
        size_mb = size / (1024 * 1024)
        raise ValueError(
            f"Audio file {audio_path.name} is {size_mb:.1f} MB, "
            f"exceeds 25 MB OpenAI API limit. "
            f"At 32 kbps opus this means video is over ~2 hours. "
            f"Either split the video or switch TRANSCRIBE_BACKEND=local."
        )


def map_openai_to_whisperx(response: dict) -> dict:
    """Convert OpenAI verbose_json response to whisperx schema.

    OpenAI returns top-level `words` and `segments` lists. Whisperx schema
    nests `words` inside each segment.
    """
    api_segments = response.get("segments", [])
    api_words = response.get("words", [])
    language = response.get("language", "")

    segments = []
    word_idx = 0
    for seg in api_segments:
        seg_start = float(seg["start"])
        seg_end = float(seg["end"])
        seg_words = []
        # Walk forward through words while they belong to this segment.
        # Words sorted by start; assign by start time within segment bounds.
        while word_idx < len(api_words):
            w = api_words[word_idx]
            w_start = float(w["start"])
            if w_start >= seg_end:
                break
            if w_start >= seg_start:
                seg_words.append({
                    "word": w["word"],
                    "start": w_start,
                    "end": float(w["end"]),
                    "score": 1.0,
                })
            word_idx += 1
        segments.append({
            "start": seg_start,
            "end": seg_end,
            "text": seg["text"],
            "words": seg_words,
        })

    return {"segments": segments, "language": language}


MAX_RETRIES = 3
RETRY_BACKOFF_SEC = 2


def transcribe_via_openai(
    video_path: Path,
    api_key: str,
    model: str,
    language: str | None,
) -> dict:
    """Transcribe video via OpenAI Whisper API. Returns whisperx-shaped dict.

    Raises RateLimitedError on 429 with parsed Retry-After (no internal retry on 429).
    """
    if not api_key:
        raise ValueError("OPENAI_API_KEY is required when TRANSCRIBE_BACKEND=openai")

    backend = _detect_backend(os.environ.get("OPENAI_BASE_URL"))

    with tempfile.TemporaryDirectory(prefix="meetscribe-openai-") as tmp:
        audio_path = extract_audio_to_opus(video_path, Path(tmp) / "audio.ogg")
        validate_audio_size(audio_path)

        client = OpenAI(api_key=api_key)

        kwargs = {
            "model": model,
            "response_format": "verbose_json",
            "timestamp_granularities": ["word", "segment"],
        }
        if language:
            kwargs["language"] = language

        last_err: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                with audio_path.open("rb") as f:
                    response = client.audio.transcriptions.create(file=f, **kwargs)
                return map_openai_to_whisperx(response.model_dump())
            except RateLimitError as e:
                # 429: don't retry internally - propagate so worker can defer.
                retry_after_header = None
                resp = getattr(e, "response", None)
                if resp is not None:
                    headers = getattr(resp, "headers", None) or {}
                    retry_after_header = headers.get("retry-after") or headers.get("Retry-After")
                retry_after = _parse_retry_after(retry_after_header)
                raise RateLimitedError(backend, retry_after, str(e)[:200]) from e
            except (ConnectionError, TimeoutError, APIConnectionError, APITimeoutError) as e:
                last_err = e
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_BACKOFF_SEC * attempt)

        assert last_err is not None
        raise last_err
