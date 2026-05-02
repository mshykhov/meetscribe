"""Tests for src/sidecar.py: sidecar_path resolver and load_sidecar validator."""

from pathlib import Path

import pytest


def test_sidecar_path_strips_video_extension():
    from src.sidecar import sidecar_path
    assert sidecar_path(Path("/x/y.mp4")) == Path("/x/y.meetscribe.toml")


def test_sidecar_path_handles_uppercase_ext():
    from src.sidecar import sidecar_path
    assert sidecar_path(Path("/x/Y.MP4")) == Path("/x/Y.meetscribe.toml")


def test_sidecar_path_handles_mkv():
    from src.sidecar import sidecar_path
    assert sidecar_path(Path("/v/standup.mkv")) == Path("/v/standup.meetscribe.toml")


def test_no_sidecar_returns_empty_dict(tmp_path):
    from src.sidecar import load_sidecar
    video = tmp_path / "no-sidecar.mp4"
    video.touch()
    assert load_sidecar(video) == {}


def test_empty_sidecar_returns_empty_dict(tmp_path):
    from src.sidecar import load_sidecar
    video = tmp_path / "v.mp4"
    sidecar = tmp_path / "v.meetscribe.toml"
    sidecar.write_text("")
    assert load_sidecar(video) == {}


def test_comments_only_sidecar_returns_empty_dict(tmp_path):
    from src.sidecar import load_sidecar
    video = tmp_path / "v.mp4"
    sidecar = tmp_path / "v.meetscribe.toml"
    sidecar.write_text("# just a comment\n# another\n")
    assert load_sidecar(video) == {}


def test_parse_error_raises_SidecarError(tmp_path):
    from src.sidecar import load_sidecar, SidecarError
    video = tmp_path / "v.mp4"
    sidecar = tmp_path / "v.meetscribe.toml"
    sidecar.write_text("= = = =")
    with pytest.raises(SidecarError) as excinfo:
        load_sidecar(video)
    assert "parse error" in str(excinfo.value)


def test_full_sidecar_returns_all_keys(tmp_path):
    from src.sidecar import load_sidecar
    video = tmp_path / "v.mp4"
    sidecar = tmp_path / "v.meetscribe.toml"
    sidecar.write_text(
        'transcribe_backend = "local"\n'
        'language = "ru"\n'
        'whisper_model = "large-v2"\n'
        'openai_transcribe_model = "whisper-1"\n'
        'max_speakers = 2\n'
        'claude_model = "claude-haiku-4-5"\n'
    )
    result = load_sidecar(video)
    assert result == {
        "transcribe_backend": "local",
        "language": "ru",
        "whisper_model": "large-v2",
        "openai_transcribe_model": "whisper-1",
        "max_speakers": 2,
        "claude_model": "claude-haiku-4-5",
    }


def test_partial_sidecar_returns_only_present_keys(tmp_path):
    from src.sidecar import load_sidecar
    video = tmp_path / "v.mp4"
    sidecar = tmp_path / "v.meetscribe.toml"
    sidecar.write_text('language = "ru"\n')
    assert load_sidecar(video) == {"language": "ru"}


def test_max_speakers_zero_allowed(tmp_path):
    """Zero is auto - allowed."""
    from src.sidecar import load_sidecar
    video = tmp_path / "v.mp4"
    sidecar = tmp_path / "v.meetscribe.toml"
    sidecar.write_text("max_speakers = 0\n")
    assert load_sidecar(video) == {"max_speakers": 0}


def test_unknown_key_raises(tmp_path):
    from src.sidecar import load_sidecar, SidecarError
    video = tmp_path / "v.mp4"
    sidecar = tmp_path / "v.meetscribe.toml"
    sidecar.write_text("foo = 1\n")
    with pytest.raises(SidecarError) as excinfo:
        load_sidecar(video)
    assert "unknown key 'foo'" in str(excinfo.value)


def test_forbidden_key_hf_token(tmp_path):
    from src.sidecar import load_sidecar, SidecarError
    video = tmp_path / "v.mp4"
    sidecar = tmp_path / "v.meetscribe.toml"
    sidecar.write_text('hf_token = "abc"\n')
    with pytest.raises(SidecarError) as excinfo:
        load_sidecar(video)
    assert "forbidden" in str(excinfo.value)
    assert "hf_token" in str(excinfo.value)


def test_forbidden_key_openai_api_key(tmp_path):
    from src.sidecar import load_sidecar, SidecarError
    video = tmp_path / "v.mp4"
    sidecar = tmp_path / "v.meetscribe.toml"
    sidecar.write_text('openai_api_key = "abc"\n')
    with pytest.raises(SidecarError) as excinfo:
        load_sidecar(video)
    assert "forbidden" in str(excinfo.value)


def test_forbidden_key_output_dir(tmp_path):
    from src.sidecar import load_sidecar, SidecarError
    video = tmp_path / "v.mp4"
    sidecar = tmp_path / "v.meetscribe.toml"
    sidecar.write_text('output_dir = "/tmp"\n')
    with pytest.raises(SidecarError):
        load_sidecar(video)


def test_type_mismatch_raises_max_speakers(tmp_path):
    from src.sidecar import load_sidecar, SidecarError
    video = tmp_path / "v.mp4"
    sidecar = tmp_path / "v.meetscribe.toml"
    sidecar.write_text('max_speakers = "ten"\n')
    with pytest.raises(SidecarError) as excinfo:
        load_sidecar(video)
    assert "max_speakers must be int" in str(excinfo.value)


def test_type_mismatch_raises_language(tmp_path):
    from src.sidecar import load_sidecar, SidecarError
    video = tmp_path / "v.mp4"
    sidecar = tmp_path / "v.meetscribe.toml"
    sidecar.write_text("language = 42\n")
    with pytest.raises(SidecarError) as excinfo:
        load_sidecar(video)
    assert "language must be str" in str(excinfo.value)


def test_bool_rejected_for_int_field(tmp_path):
    """bool is subclass of int - must be rejected explicitly."""
    from src.sidecar import load_sidecar, SidecarError
    video = tmp_path / "v.mp4"
    sidecar = tmp_path / "v.meetscribe.toml"
    sidecar.write_text("max_speakers = true\n")
    with pytest.raises(SidecarError) as excinfo:
        load_sidecar(video)
    assert "max_speakers must be int" in str(excinfo.value)


def test_enum_invalid_transcribe_backend(tmp_path):
    from src.sidecar import load_sidecar, SidecarError
    video = tmp_path / "v.mp4"
    sidecar = tmp_path / "v.meetscribe.toml"
    sidecar.write_text('transcribe_backend = "groq"\n')
    with pytest.raises(SidecarError) as excinfo:
        load_sidecar(video)
    assert "transcribe_backend" in str(excinfo.value)
    assert "must be one of" in str(excinfo.value)


def test_enum_invalid_whisper_model(tmp_path):
    from src.sidecar import load_sidecar, SidecarError
    video = tmp_path / "v.mp4"
    sidecar = tmp_path / "v.meetscribe.toml"
    sidecar.write_text('whisper_model = "huge-v9"\n')
    with pytest.raises(SidecarError):
        load_sidecar(video)


def test_max_speakers_negative_raises(tmp_path):
    from src.sidecar import load_sidecar, SidecarError
    video = tmp_path / "v.mp4"
    sidecar = tmp_path / "v.meetscribe.toml"
    sidecar.write_text("max_speakers = -1\n")
    with pytest.raises(SidecarError) as excinfo:
        load_sidecar(video)
    assert ">= 0" in str(excinfo.value)


def test_enum_valid_transcribe_backend_openai(tmp_path):
    from src.sidecar import load_sidecar
    video = tmp_path / "v.mp4"
    sidecar = tmp_path / "v.meetscribe.toml"
    sidecar.write_text('transcribe_backend = "openai"\n')
    assert load_sidecar(video) == {"transcribe_backend": "openai"}
