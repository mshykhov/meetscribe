"""OpenAI Whisper API transcription backend.

Replaces local whisperx-mlx transcribe + align steps with a single API call
that returns word-level timestamps directly.
"""

import subprocess
import tempfile
import time
from pathlib import Path

from openai import OpenAI, APIConnectionError, APITimeoutError


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
    """Transcribe video via OpenAI Whisper API. Returns whisperx-shaped dict."""
    if not api_key:
        raise ValueError("OPENAI_API_KEY is required when TRANSCRIBE_BACKEND=openai")

    with tempfile.TemporaryDirectory(prefix="meetscribe-openai-") as tmp:
        audio_path = extract_audio_to_opus(video_path, Path(tmp) / "audio.opus")
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
            except (ConnectionError, TimeoutError, APIConnectionError, APITimeoutError) as e:
                last_err = e
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_BACKOFF_SEC * attempt)

        assert last_err is not None
        raise last_err
