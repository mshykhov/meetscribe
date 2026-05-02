"""Tests for src/config_schema.py: validate_env + reused validate_sidecar."""

from pathlib import Path

import pytest


def _base_env(tmp_path: Path) -> dict[str, str]:
    """Return the minimum-viable .env dict. Tests mutate copies to test failures."""
    return {
        "HF_TOKEN": "hf_abc",
        "OPENAI_API_KEY": "",
        "CLAUDE_CLI": "claude",
        "WATCH_DIR": str(tmp_path),
        "OUTPUT_DIR": str(tmp_path),
        "TRANSCRIBE_BACKEND": "local",
        "WHISPER_MODEL": "medium",
        "OPENAI_TRANSCRIBE_MODEL": "whisper-1",
        "LANGUAGE": "",
        "MAX_SPEAKERS": "0",
        "CLAUDE_MODEL": "claude-sonnet-4-6",
    }


def test_env_minimal_valid(tmp_path):
    from src.config_schema import validate_env
    assert validate_env(_base_env(tmp_path)) == []


def test_env_missing_hf_token_raises(tmp_path):
    from src.config_schema import validate_env
    env = _base_env(tmp_path)
    env["HF_TOKEN"] = ""
    errors = validate_env(env)
    assert any(e.key == "HF_TOKEN" and "required" in e.message for e in errors)


def test_env_hf_token_wrong_prefix_raises(tmp_path):
    from src.config_schema import validate_env
    env = _base_env(tmp_path)
    env["HF_TOKEN"] = "abc"
    errors = validate_env(env)
    assert any(e.key == "HF_TOKEN" and "hf_" in e.message for e in errors)


def test_env_openai_backend_requires_api_key(tmp_path):
    from src.config_schema import validate_env
    env = _base_env(tmp_path)
    env["TRANSCRIBE_BACKEND"] = "openai"
    env["OPENAI_API_KEY"] = ""
    errors = validate_env(env)
    assert any(e.key == "OPENAI_API_KEY" for e in errors)


def test_env_openai_backend_with_api_key_ok(tmp_path):
    from src.config_schema import validate_env
    env = _base_env(tmp_path)
    env["TRANSCRIBE_BACKEND"] = "openai"
    env["OPENAI_API_KEY"] = "sk-abc"
    assert validate_env(env) == []


def test_env_local_backend_no_api_key_ok(tmp_path):
    from src.config_schema import validate_env
    env = _base_env(tmp_path)
    env["TRANSCRIBE_BACKEND"] = "local"
    env["OPENAI_API_KEY"] = ""
    assert validate_env(env) == []


def test_env_max_speakers_negative(tmp_path):
    from src.config_schema import validate_env
    env = _base_env(tmp_path)
    env["MAX_SPEAKERS"] = "-1"
    errors = validate_env(env)
    assert any(e.key == "MAX_SPEAKERS" and ">= 0" in e.message for e in errors)


def test_env_max_speakers_not_int(tmp_path):
    from src.config_schema import validate_env
    env = _base_env(tmp_path)
    env["MAX_SPEAKERS"] = "ten"
    errors = validate_env(env)
    assert any(e.key == "MAX_SPEAKERS" for e in errors)


def test_env_unknown_keys_ignored(tmp_path):
    from src.config_schema import validate_env
    env = _base_env(tmp_path)
    env["MY_CUSTOM"] = "value"
    assert validate_env(env) == []


def test_env_watch_dir_parent_missing(tmp_path):
    from src.config_schema import validate_env
    env = _base_env(tmp_path)
    env["WATCH_DIR"] = "/no/such/dir/sub"
    errors = validate_env(env)
    assert any(e.key == "WATCH_DIR" for e in errors)


def test_env_invalid_whisper_model(tmp_path):
    from src.config_schema import validate_env
    env = _base_env(tmp_path)
    env["WHISPER_MODEL"] = "huge-v9"
    errors = validate_env(env)
    assert any(e.key == "WHISPER_MODEL" and "must be one of" in e.message for e in errors)


def test_env_invalid_transcribe_backend(tmp_path):
    from src.config_schema import validate_env
    env = _base_env(tmp_path)
    env["TRANSCRIBE_BACKEND"] = "groq"
    errors = validate_env(env)
    assert any(e.key == "TRANSCRIBE_BACKEND" for e in errors)
