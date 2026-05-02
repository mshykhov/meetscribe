"""Per-video sidecar config overrides - TOML reader on top of config_schema."""

from __future__ import annotations

import tomllib
from pathlib import Path

from src.config_schema import ConfigError, validate_sidecar


# Re-export for backward compat with `from src.sidecar import SidecarError`.
SidecarError = ConfigError


def sidecar_path(video_path: Path) -> Path:
    """Return the canonical sidecar path for a video file.

    `meeting.mp4` -> `meeting.meetscribe.toml` (video extension stripped).
    """
    return video_path.with_suffix(".meetscribe.toml")


def load_sidecar(video_path: Path) -> dict:
    """Load + validate sidecar overrides. Returns {} when no sidecar exists.

    Raises:
        SidecarError (= ConfigError): on parse failure or schema violation.
    """
    p = sidecar_path(video_path)
    if not p.exists():
        return {}
    try:
        with p.open("rb") as f:
            data = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError) as e:
        raise ConfigError("sidecar", f"sidecar parse error: {e}") from e
    return validate_sidecar(data)
