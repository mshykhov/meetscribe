"""Tests for src/config_schema.py: validate_env + reused validate_sidecar."""

from pathlib import Path

import pytest


def _base_env(tmp_path: Path) -> dict[str, str]:
    """Return the minimum-viable .env dict. Tests mutate copies to test failures."""
    return {
        "HF_TOKEN": "hf_abc",
        "OPENAI_API_KEY": "",
        "GROQ_API_KEY": "",
        "GROQ_TRANSCRIBE_MODEL": "whisper-large-v3",
        "CLAUDE_CLI": "claude",
        "WATCH_DIR": str(tmp_path),
        "OUTPUT_DIR": str(tmp_path),
        "TRANSCRIBE_BACKEND": "local",
        "WHISPER_MODEL": "medium",
        "OPENAI_TRANSCRIBE_MODEL": "whisper-1",
        "LANGUAGE": "",
        "MAX_SPEAKERS": "0",
        "CLAUDE_MODEL": "claude-sonnet-4-6",
        "SUMMARY_BACKEND": "claude_code",
        "OPENAI_SUMMARY_MODEL": "gpt-4o-mini",
        "GROQ_SUMMARY_MODEL": "llama-3.3-70b-versatile",
    }


def test_env_summary_backend_claude_code_ok(tmp_path):
    """summary_backend='claude_code' is the default and valid."""
    from src.config_schema import validate_env
    env = _base_env(tmp_path)
    env["SUMMARY_BACKEND"] = "claude_code"
    assert validate_env(env) == []


def test_env_summary_backend_openai_requires_api_key(tmp_path):
    from src.config_schema import validate_env
    env = _base_env(tmp_path)
    env["SUMMARY_BACKEND"] = "openai"
    env["OPENAI_API_KEY"] = ""
    errors = validate_env(env)
    assert any(e.key == "OPENAI_API_KEY" for e in errors)


def test_env_summary_backend_groq_requires_api_key(tmp_path):
    from src.config_schema import validate_env
    env = _base_env(tmp_path)
    env["SUMMARY_BACKEND"] = "groq"
    env["GROQ_API_KEY"] = ""
    errors = validate_env(env)
    assert any(e.key == "GROQ_API_KEY" for e in errors)


def test_env_summary_backend_groq_with_api_key_ok(tmp_path):
    from src.config_schema import validate_env
    env = _base_env(tmp_path)
    env["SUMMARY_BACKEND"] = "groq"
    env["GROQ_API_KEY"] = "gsk-abc"
    assert validate_env(env) == []


def test_env_summary_backend_invalid_value(tmp_path):
    from src.config_schema import validate_env
    env = _base_env(tmp_path)
    env["SUMMARY_BACKEND"] = "azure"
    errors = validate_env(env)
    assert any(e.key == "SUMMARY_BACKEND" for e in errors)


def test_env_shared_provider_key_message_format(tmp_path):
    """Cross-key error message says 'using openai provider' not stage-specific."""
    from src.config_schema import validate_env
    env = _base_env(tmp_path)
    env["TRANSCRIBE_BACKEND"] = "local"
    env["SUMMARY_BACKEND"] = "openai"
    env["OPENAI_API_KEY"] = ""
    errors = validate_env(env)
    msgs = [e.message for e in errors if e.key == "OPENAI_API_KEY"]
    assert len(msgs) == 1
    assert "openai provider" in msgs[0]


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
    """unknown enum value rejected (e.g. 'azure')."""
    from src.config_schema import validate_env
    env = _base_env(tmp_path)
    env["TRANSCRIBE_BACKEND"] = "azure"
    errors = validate_env(env)
    assert any(e.key == "TRANSCRIBE_BACKEND" for e in errors)


def test_env_groq_backend_in_enum(tmp_path):
    """transcribe_backend='groq' must be accepted by validate_env."""
    from src.config_schema import validate_env
    env = _base_env(tmp_path)
    env["TRANSCRIBE_BACKEND"] = "groq"
    env["GROQ_API_KEY"] = "gsk-abc"
    errors = validate_env(env)
    backend_errors = [e for e in errors if e.key == "TRANSCRIBE_BACKEND"]
    assert backend_errors == []


def test_env_groq_backend_requires_groq_api_key(tmp_path):
    from src.config_schema import validate_env
    env = _base_env(tmp_path)
    env["TRANSCRIBE_BACKEND"] = "groq"
    env["GROQ_API_KEY"] = ""
    errors = validate_env(env)
    assert any(e.key == "GROQ_API_KEY" for e in errors)


def test_env_groq_backend_with_api_key_ok(tmp_path):
    from src.config_schema import validate_env
    env = _base_env(tmp_path)
    env["TRANSCRIBE_BACKEND"] = "groq"
    env["GROQ_API_KEY"] = "gsk-abc"
    env["GROQ_TRANSCRIBE_MODEL"] = "whisper-large-v3"
    assert validate_env(env) == []


def test_env_local_backend_no_groq_key_ok(tmp_path):
    """local backend must not require GROQ_API_KEY."""
    from src.config_schema import validate_env
    env = _base_env(tmp_path)
    env["TRANSCRIBE_BACKEND"] = "local"
    env["GROQ_API_KEY"] = ""
    assert validate_env(env) == []
