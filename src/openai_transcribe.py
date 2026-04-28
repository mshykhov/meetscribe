"""OpenAI Whisper API transcription backend.

Replaces local whisperx-mlx transcribe + align steps with a single API call
that returns word-level timestamps directly.
"""

import subprocess
from pathlib import Path


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
