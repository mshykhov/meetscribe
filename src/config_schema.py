"""Shared config validation - used by both sidecar (.toml) and TUI (.env)."""

from __future__ import annotations

from pathlib import Path


_ALLOWED_TYPES: dict[str, type] = {
    "transcribe_backend": str, "language": str, "whisper_model": str,
    "openai_transcribe_model": str, "max_speakers": int, "claude_model": str,
    "hf_token": str, "openai_api_key": str, "claude_cli": str,
    "watch_dir": str, "output_dir": str,
}

ENV_KEYS: tuple[str, ...] = (
    "HF_TOKEN", "OPENAI_API_KEY", "CLAUDE_CLI", "WATCH_DIR", "OUTPUT_DIR",
    "TRANSCRIBE_BACKEND", "WHISPER_MODEL", "OPENAI_TRANSCRIBE_MODEL",
    "LANGUAGE", "MAX_SPEAKERS", "CLAUDE_MODEL",
)

SIDECAR_KEYS: frozenset[str] = frozenset({
    "transcribe_backend", "language", "whisper_model",
    "openai_transcribe_model", "max_speakers", "claude_model",
})

SIDECAR_FORBIDDEN: frozenset[str] = frozenset({
    "hf_token", "openai_api_key", "claude_cli", "output_dir", "WATCH_DIR",
})

_ENUMS: dict[str, frozenset[str]] = {
    "transcribe_backend": frozenset({"local", "openai"}),
    "whisper_model": frozenset({
        "tiny", "base", "small", "medium", "large-v2", "large-v3",
    }),
}


class ConfigError(ValueError):
    """One validation error. `str(err)` returns the message verbatim."""
    def __init__(self, key: str, message: str):
        self.key = key
        self.message = message
        super().__init__(message)


def _check_value(key: str, value, prefix: str = "sidecar") -> None:
    """Type / enum / range checks shared by sidecar and env validators.

    Raises ConfigError on failure. bool-is-int trap is rejected explicitly.
    Message format: "<prefix>: <key> <reason>".
    """
    expected = _ALLOWED_TYPES[key]
    if expected is int and isinstance(value, bool):
        raise ConfigError(key, f"{prefix}: {key} must be int, got bool")
    if not isinstance(value, expected):
        raise ConfigError(
            key,
            f"{prefix}: {key} must be {expected.__name__}, "
            f"got {type(value).__name__}",
        )
    if key in _ENUMS and value not in _ENUMS[key]:
        allowed = "', '".join(sorted(_ENUMS[key]))
        raise ConfigError(key, f"{prefix}: {key} must be one of '{allowed}'")
    if key == "max_speakers" and value < 0:
        raise ConfigError(key, f"{prefix}: max_speakers must be >= 0")


def validate_sidecar(data: dict) -> dict:
    """Validate a parsed sidecar TOML. Raises ConfigError on first problem."""
    out: dict = {}
    for key, value in data.items():
        if key in SIDECAR_FORBIDDEN:
            raise ConfigError(key, f"sidecar: forbidden key '{key}'")
        if key not in SIDECAR_KEYS:
            raise ConfigError(key, f"sidecar: unknown key '{key}'")
        _check_value(key, value, prefix="sidecar")
        out[key] = value
    return out


def _coerce_for_env(key_lower: str, value: str):
    """Coerce a string from .env into the expected type for _check_value."""
    expected = _ALLOWED_TYPES[key_lower]
    if expected is int:
        return int(value)  # may raise ValueError
    return value


def validate_env(data: dict[str, str]) -> list[ConfigError]:
    """Validate a complete .env dict (UPPERCASE keys). Returns list of errors.

    Unknown UPPERCASE keys are ignored (preserved by config_io).
    Cross-key rule: TRANSCRIBE_BACKEND='openai' requires OPENAI_API_KEY.
    """
    errors: list[ConfigError] = []

    for KEY in ENV_KEYS:
        raw = data.get(KEY, "")
        key_lower = KEY.lower()

        # Required-non-empty checks (LANGUAGE and OPENAI_API_KEY may be empty).
        if KEY in {"HF_TOKEN", "CLAUDE_CLI", "WATCH_DIR", "OUTPUT_DIR",
                   "TRANSCRIBE_BACKEND", "WHISPER_MODEL",
                   "OPENAI_TRANSCRIBE_MODEL", "MAX_SPEAKERS", "CLAUDE_MODEL"}:
            if raw == "":
                errors.append(ConfigError(KEY, f"{KEY}: required"))
                continue

        if raw == "":
            continue  # LANGUAGE / OPENAI_API_KEY may be blank

        # Type coercion (str→int for MAX_SPEAKERS).
        try:
            coerced = _coerce_for_env(key_lower, raw)
        except ValueError:
            errors.append(ConfigError(KEY, f"{KEY}: must be int"))
            continue

        # Type / enum / range checks shared with sidecar.
        try:
            _check_value(key_lower, coerced, prefix=KEY)
        except ConfigError as e:
            # Re-key to UPPERCASE so callers see the env-var name.
            errors.append(ConfigError(KEY, e.message))

    # HF_TOKEN format check (only when present).
    hf = data.get("HF_TOKEN", "")
    if hf and not hf.startswith("hf_"):
        errors.append(
            ConfigError("HF_TOKEN", "HF_TOKEN: must start with 'hf_'"),
        )

    # Path parents must exist.
    for KEY in ("WATCH_DIR", "OUTPUT_DIR"):
        raw = data.get(KEY, "")
        if not raw:
            continue
        p = Path(raw).expanduser()
        if not p.parent.exists():
            errors.append(
                ConfigError(KEY, f"{KEY}: parent directory '{p.parent}' does not exist"),
            )

    # Cross-key: openai backend requires api key.
    if data.get("TRANSCRIBE_BACKEND") == "openai" and not data.get("OPENAI_API_KEY"):
        errors.append(
            ConfigError("OPENAI_API_KEY",
                        "OPENAI_API_KEY: required when TRANSCRIBE_BACKEND=openai"),
        )

    return errors
