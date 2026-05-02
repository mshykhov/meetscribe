"""Per-video sidecar config overrides.

Read `<stem>.meetscribe.toml` next to a video, validate against the allowed
schema, return a dict of overrides to merge on top of `load_config()`.
Returns {} when the sidecar is absent. Raises `SidecarError` on any problem
so the caller can mark the video as invalid.
"""

from __future__ import annotations

import tomllib
from pathlib import Path


class SidecarError(ValueError):
    """Raised when sidecar TOML is malformed or violates the schema."""


_ALLOWED: dict[str, type] = {
    "transcribe_backend": str,
    "language": str,
    "whisper_model": str,
    "openai_transcribe_model": str,
    "max_speakers": int,
    "claude_model": str,
}

_FORBIDDEN: set[str] = {
    "hf_token", "openai_api_key", "claude_cli", "output_dir", "WATCH_DIR",
}

_ENUMS: dict[str, set[str]] = {
    "transcribe_backend": {"local", "openai"},
    "whisper_model": {"tiny", "base", "small", "medium", "large-v2", "large-v3"},
}


def sidecar_path(video_path: Path) -> Path:
    """Return the canonical sidecar path for a video file.

    `meeting.mp4` -> `meeting.meetscribe.toml` (video extension stripped).
    """
    return video_path.with_suffix(".meetscribe.toml")


def load_sidecar(video_path: Path) -> dict:
    """Load + validate sidecar overrides. Returns {} when no sidecar exists.

    Raises:
        SidecarError: on parse failure, schema violation, or filesystem oddity.
    """
    p = sidecar_path(video_path)
    if not p.exists():
        return {}
    try:
        with p.open("rb") as f:
            data = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError) as e:
        raise SidecarError(f"sidecar parse error: {e}") from e
    return _validate(data)


def _validate(data: dict) -> dict:
    out: dict = {}
    for key, value in data.items():
        if key in _FORBIDDEN:
            raise SidecarError(f"sidecar: forbidden key '{key}'")
        if key not in _ALLOWED:
            raise SidecarError(f"sidecar: unknown key '{key}'")
        expected = _ALLOWED[key]
        # bool is a subclass of int - reject it explicitly when an int is expected.
        if expected is int and isinstance(value, bool):
            raise SidecarError(f"sidecar: {key} must be int, got bool")
        if not isinstance(value, expected):
            raise SidecarError(
                f"sidecar: {key} must be {expected.__name__}, "
                f"got {type(value).__name__}"
            )
        if key in _ENUMS and value not in _ENUMS[key]:
            allowed = "', '".join(sorted(_ENUMS[key]))
            raise SidecarError(f"sidecar: {key} must be one of '{allowed}'")
        if key == "max_speakers" and value < 0:
            raise SidecarError("sidecar: max_speakers must be >= 0")
        out[key] = value
    return out
