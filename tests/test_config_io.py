"""Tests for src/config_io.py: read_env + write_env (preserves order/comments)."""

from pathlib import Path


def test_read_env_returns_dict(tmp_path):
    from src.config_io import read_env
    p = tmp_path / ".env"
    p.write_text("HF_TOKEN=hf_abc\nWHISPER_MODEL=medium\n")
    assert read_env(p) == {"HF_TOKEN": "hf_abc", "WHISPER_MODEL": "medium"}


def test_read_env_skips_comments_and_blanks(tmp_path):
    from src.config_io import read_env
    p = tmp_path / ".env"
    p.write_text(
        "# comment\n"
        "\n"
        "HF_TOKEN=hf_abc\n"
        "# another\n"
    )
    assert read_env(p) == {"HF_TOKEN": "hf_abc"}


def test_read_env_handles_missing_file(tmp_path):
    from src.config_io import read_env
    assert read_env(tmp_path / "no.env") == {}


def test_write_env_preserves_comments(tmp_path):
    from src.config_io import write_env
    p = tmp_path / ".env"
    p.write_text(
        "# top comment\n"
        "HF_TOKEN=hf_old\n"
        "# middle\n"
        "WHISPER_MODEL=medium\n"
    )
    write_env(p, {"HF_TOKEN": "hf_new"})
    text = p.read_text()
    assert "# top comment" in text
    assert "# middle" in text
    assert "HF_TOKEN=hf_new" in text
    assert "HF_TOKEN=hf_old" not in text
    assert "WHISPER_MODEL=medium" in text


def test_write_env_replaces_existing_value(tmp_path):
    from src.config_io import read_env, write_env
    p = tmp_path / ".env"
    p.write_text("HF_TOKEN=hf_old\n")
    write_env(p, {"HF_TOKEN": "hf_new"})
    assert read_env(p) == {"HF_TOKEN": "hf_new"}


def test_write_env_appends_new_keys(tmp_path):
    from src.config_io import read_env, write_env
    p = tmp_path / ".env"
    p.write_text("HF_TOKEN=hf_abc\n")
    write_env(p, {"HF_TOKEN": "hf_abc", "WHISPER_MODEL": "medium"})
    assert read_env(p) == {"HF_TOKEN": "hf_abc", "WHISPER_MODEL": "medium"}


def test_write_env_round_trip(tmp_path):
    from src.config_io import read_env, write_env
    p = tmp_path / ".env"
    original = {
        "HF_TOKEN": "hf_abc",
        "OPENAI_API_KEY": "sk-xyz",
        "WHISPER_MODEL": "medium",
        "MAX_SPEAKERS": "0",
    }
    p.write_text("\n".join(f"{k}={v}" for k, v in original.items()) + "\n")
    write_env(p, original)
    assert read_env(p) == original


def test_write_env_preserves_unknown_kv(tmp_path):
    from src.config_io import read_env, write_env
    p = tmp_path / ".env"
    p.write_text("HF_TOKEN=hf_abc\nMY_VAR=foo\n")
    write_env(p, {"HF_TOKEN": "hf_new"})
    assert read_env(p)["MY_VAR"] == "foo"


def test_parse_kv_rejects_lowercase_key(tmp_path):
    """Lowercase letters in key are not parsed as KV."""
    from src.config_io import read_env, write_env
    p = tmp_path / ".env"
    p.write_text("hf_token=abc\nHF_TOKEN=hf_real\n")
    parsed = read_env(p)
    assert "hf_token" not in parsed
    assert parsed["HF_TOKEN"] == "hf_real"


def test_write_env_creates_file_when_missing(tmp_path):
    from src.config_io import read_env, write_env
    p = tmp_path / ".env"
    write_env(p, {"HF_TOKEN": "hf_abc"})
    assert p.exists()
    assert read_env(p) == {"HF_TOKEN": "hf_abc"}
