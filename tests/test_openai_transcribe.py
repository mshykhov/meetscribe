"""Tests for OpenAI transcribe backend."""

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest


class TestConfigLoading:
    def test_load_config_defaults_to_local_backend(self):
        from src.process import load_config
        with patch.dict(os.environ, {"HF_TOKEN": "hf_x"}, clear=True):
            cfg = load_config()
        assert cfg["transcribe_backend"] == "local"

    def test_load_config_reads_openai_backend(self):
        from src.process import load_config
        env = {
            "HF_TOKEN": "hf_x",
            "TRANSCRIBE_BACKEND": "openai",
            "OPENAI_API_KEY": "sk-test",
            "OPENAI_TRANSCRIBE_MODEL": "gpt-4o-transcribe",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = load_config()
        assert cfg["transcribe_backend"] == "openai"
        assert cfg["openai_api_key"] == "sk-test"
        assert cfg["openai_transcribe_model"] == "gpt-4o-transcribe"

    def test_load_config_openai_backend_defaults_model(self):
        from src.process import load_config
        env = {"HF_TOKEN": "hf_x", "TRANSCRIBE_BACKEND": "openai", "OPENAI_API_KEY": "sk-x"}
        with patch.dict(os.environ, env, clear=True):
            cfg = load_config()
        assert cfg["openai_api_key"] == "sk-x"
        assert cfg["openai_transcribe_model"] == "whisper-1"


def _make_test_video(path: Path, duration_sec: int = 3) -> Path:
    """Create a minimal silent test video with audio track."""
    subprocess.run(
        ["ffmpeg", "-f", "lavfi", "-i", f"color=c=black:s=160x120:d={duration_sec}",
         "-f", "lavfi", "-i", f"anullsrc=channel_layout=mono:sample_rate=16000:d={duration_sec}",
         "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", "-shortest", "-y", str(path)],
        check=True, capture_output=True,
    )
    return path


class TestAudioExtraction:
    def test_extract_audio_creates_opus_file(self, tmp_path):
        from src.openai_transcribe import extract_audio_to_opus
        video = _make_test_video(tmp_path / "in.mp4", duration_sec=3)
        out = extract_audio_to_opus(video, tmp_path / "out.opus")
        assert out.exists()
        assert out.suffix == ".opus"

    def test_extract_audio_uses_mono_32kbps(self, tmp_path):
        from src.openai_transcribe import extract_audio_to_opus
        video = _make_test_video(tmp_path / "in.mp4", duration_sec=3)
        out = extract_audio_to_opus(video, tmp_path / "out.opus")
        # Probe the output
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_streams", "-select_streams", "a:0",
             "-of", "default=noprint_wrappers=1", str(out)],
            capture_output=True, text=True, check=True,
        )
        assert "channels=1" in result.stdout
        assert "codec_name=opus" in result.stdout

    def test_extract_audio_raises_on_missing_input(self, tmp_path):
        from src.openai_transcribe import extract_audio_to_opus
        with pytest.raises(RuntimeError, match="ffmpeg failed"):
            extract_audio_to_opus(tmp_path / "missing.mp4", tmp_path / "out.opus")


class TestSizeValidation:
    def test_accepts_file_under_limit(self, tmp_path):
        from src.openai_transcribe import validate_audio_size
        f = tmp_path / "audio.opus"
        f.write_bytes(b"\x00" * 1000)
        validate_audio_size(f)  # No exception

    def test_rejects_file_over_25mb(self, tmp_path):
        from src.openai_transcribe import validate_audio_size
        f = tmp_path / "audio.opus"
        f.write_bytes(b"\x00" * (26 * 1024 * 1024))
        with pytest.raises(ValueError, match="exceeds 25 MB"):
            validate_audio_size(f)

    def test_error_message_suggests_chunking(self, tmp_path):
        from src.openai_transcribe import validate_audio_size
        f = tmp_path / "audio.opus"
        f.write_bytes(b"\x00" * (30 * 1024 * 1024))
        with pytest.raises(ValueError, match="2 hour"):
            validate_audio_size(f)


class TestResponseMapping:
    def _sample_response(self):
        return {
            "task": "transcribe",
            "language": "en",
            "duration": 5.0,
            "text": "Hello world. How are you?",
            "words": [
                {"word": "Hello", "start": 0.10, "end": 0.50},
                {"word": "world", "start": 0.60, "end": 1.00},
                {"word": "How",   "start": 2.50, "end": 2.70},
                {"word": "are",   "start": 2.80, "end": 2.95},
                {"word": "you",   "start": 3.00, "end": 3.30},
            ],
            "segments": [
                {"id": 0, "start": 0.0, "end": 1.5, "text": "Hello world."},
                {"id": 1, "start": 2.4, "end": 4.0, "text": "How are you?"},
            ],
        }

    def test_maps_top_level_language(self):
        from src.openai_transcribe import map_openai_to_whisperx
        out = map_openai_to_whisperx(self._sample_response())
        assert out["language"] == "en"

    def test_returns_segments_list(self):
        from src.openai_transcribe import map_openai_to_whisperx
        out = map_openai_to_whisperx(self._sample_response())
        assert len(out["segments"]) == 2
        assert out["segments"][0]["text"] == "Hello world."
        assert out["segments"][0]["start"] == 0.0
        assert out["segments"][0]["end"] == 1.5

    def test_distributes_words_to_segments_by_time(self):
        from src.openai_transcribe import map_openai_to_whisperx
        out = map_openai_to_whisperx(self._sample_response())
        seg0_words = [w["word"] for w in out["segments"][0]["words"]]
        seg1_words = [w["word"] for w in out["segments"][1]["words"]]
        assert seg0_words == ["Hello", "world"]
        assert seg1_words == ["How", "are", "you"]

    def test_word_entries_have_score_field(self):
        from src.openai_transcribe import map_openai_to_whisperx
        out = map_openai_to_whisperx(self._sample_response())
        word = out["segments"][0]["words"][0]
        assert "score" in word
        assert "start" in word
        assert "end" in word

    def test_handles_response_without_words(self):
        from src.openai_transcribe import map_openai_to_whisperx
        resp = {"language": "en", "segments": [{"start": 0, "end": 1, "text": "Hi"}]}
        out = map_openai_to_whisperx(resp)
        assert out["segments"][0]["words"] == []

    def test_handles_empty_segments(self):
        from src.openai_transcribe import map_openai_to_whisperx
        resp = {"language": "en", "segments": [], "words": []}
        out = map_openai_to_whisperx(resp)
        assert out == {"segments": [], "language": "en"}
