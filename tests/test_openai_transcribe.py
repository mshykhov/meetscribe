"""Tests for OpenAI transcribe backend."""

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest


class TestConfigLoading:
    def test_load_config_defaults_to_local_backend(self, monkeypatch):
        from src import process
        # Stub load_dotenv so the real .env on disk doesn't leak into the test.
        monkeypatch.setattr(process, "load_dotenv", lambda *a, **kw: None)
        with patch.dict(os.environ, {"HF_TOKEN": "hf_x"}, clear=True):
            cfg = process.load_config()
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
    def test_extract_audio_creates_ogg_file(self, tmp_path):
        from src.openai_transcribe import extract_audio_to_opus
        video = _make_test_video(tmp_path / "in.mp4", duration_sec=3)
        out = extract_audio_to_opus(video, tmp_path / "out.ogg")
        assert out.exists()
        assert out.suffix == ".ogg"

    def test_extract_audio_uses_mono_32kbps(self, tmp_path):
        from src.openai_transcribe import extract_audio_to_opus
        video = _make_test_video(tmp_path / "in.mp4", duration_sec=3)
        out = extract_audio_to_opus(video, tmp_path / "out.ogg")
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
            extract_audio_to_opus(tmp_path / "missing.mp4", tmp_path / "out.ogg")


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


from unittest.mock import MagicMock


class TestTranscribeViaOpenAI:
    def test_full_flow_calls_api_with_correct_params(self, tmp_path, monkeypatch):
        from src import openai_transcribe

        video = _make_test_video(tmp_path / "v.mp4", duration_sec=2)

        # Mock the OpenAI client
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {
            "language": "en",
            "duration": 2.0,
            "text": "Test.",
            "words": [{"word": "Test", "start": 0.1, "end": 0.5}],
            "segments": [{"start": 0.0, "end": 1.0, "text": "Test."}],
        }
        mock_client = MagicMock()
        mock_client.audio.transcriptions.create.return_value = mock_response
        monkeypatch.setattr(openai_transcribe, "OpenAI", lambda **kwargs: mock_client)

        out = openai_transcribe.transcribe_via_openai(
            video, backend="openai", api_key="sk-x", model="whisper-1", language=None,
        )

        # Assert call params
        call = mock_client.audio.transcriptions.create.call_args
        assert call.kwargs["model"] == "whisper-1"
        assert call.kwargs["response_format"] == "verbose_json"
        assert call.kwargs["timestamp_granularities"] == ["word", "segment"]

        # Assert output shape
        assert out["language"] == "en"
        assert len(out["segments"]) == 1
        assert out["segments"][0]["words"][0]["word"] == "Test"

    def test_passes_language_when_provided(self, tmp_path, monkeypatch):
        from src import openai_transcribe

        video = _make_test_video(tmp_path / "v.mp4", duration_sec=2)
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {"language": "ru", "segments": [], "words": []}
        mock_client = MagicMock()
        mock_client.audio.transcriptions.create.return_value = mock_response
        monkeypatch.setattr(openai_transcribe, "OpenAI", lambda **kwargs: mock_client)

        openai_transcribe.transcribe_via_openai(video, backend="openai", api_key="sk-x", model="whisper-1", language="ru")

        call = mock_client.audio.transcriptions.create.call_args
        assert call.kwargs["language"] == "ru"

    def test_omits_language_when_none(self, tmp_path, monkeypatch):
        from src import openai_transcribe

        video = _make_test_video(tmp_path / "v.mp4", duration_sec=2)
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {"language": "en", "segments": [], "words": []}
        mock_client = MagicMock()
        mock_client.audio.transcriptions.create.return_value = mock_response
        monkeypatch.setattr(openai_transcribe, "OpenAI", lambda **kwargs: mock_client)

        openai_transcribe.transcribe_via_openai(video, backend="openai", api_key="sk-x", model="whisper-1", language=None)

        call = mock_client.audio.transcriptions.create.call_args
        assert "language" not in call.kwargs

    def test_retries_on_transient_failure(self, tmp_path, monkeypatch):
        from src import openai_transcribe

        video = _make_test_video(tmp_path / "v.mp4", duration_sec=2)
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {"language": "en", "segments": [], "words": []}
        mock_client = MagicMock()
        mock_client.audio.transcriptions.create.side_effect = [
            ConnectionError("network"),
            ConnectionError("network"),
            mock_response,
        ]
        monkeypatch.setattr(openai_transcribe, "OpenAI", lambda **kwargs: mock_client)
        monkeypatch.setattr(openai_transcribe.time, "sleep", lambda _: None)

        out = openai_transcribe.transcribe_via_openai(video, backend="openai", api_key="sk-x", model="whisper-1", language=None)
        assert out["language"] == "en"
        assert mock_client.audio.transcriptions.create.call_count == 3

    def test_raises_after_max_retries(self, tmp_path, monkeypatch):
        from src import openai_transcribe

        video = _make_test_video(tmp_path / "v.mp4", duration_sec=2)
        mock_client = MagicMock()
        mock_client.audio.transcriptions.create.side_effect = ConnectionError("network")
        monkeypatch.setattr(openai_transcribe, "OpenAI", lambda **kwargs: mock_client)
        monkeypatch.setattr(openai_transcribe.time, "sleep", lambda _: None)

        with pytest.raises(ConnectionError):
            openai_transcribe.transcribe_via_openai(video, backend="openai", api_key="sk-x", model="whisper-1", language=None)

    def test_raises_on_missing_api_key(self, tmp_path):
        from src import openai_transcribe
        video = _make_test_video(tmp_path / "v.mp4", duration_sec=2)
        with pytest.raises(ValueError, match="API key"):
            openai_transcribe.transcribe_via_openai(video, backend="openai", api_key="", model="whisper-1", language=None)

    def test_retries_on_openai_api_connection_error(self, tmp_path, monkeypatch):
        from src import openai_transcribe
        from openai import APIConnectionError

        video = _make_test_video(tmp_path / "v.mp4", duration_sec=2)
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {"language": "en", "segments": [], "words": []}
        mock_client = MagicMock()

        # APIConnectionError requires a `request` kwarg; pass a stub.
        # Use a simple Mock for the request object.
        request_stub = MagicMock()
        api_err = APIConnectionError(request=request_stub)

        mock_client.audio.transcriptions.create.side_effect = [api_err, api_err, mock_response]
        monkeypatch.setattr(openai_transcribe, "OpenAI", lambda **kwargs: mock_client)
        monkeypatch.setattr(openai_transcribe.time, "sleep", lambda _: None)

        out = openai_transcribe.transcribe_via_openai(video, backend="openai", api_key="sk-x", model="whisper-1", language=None)
        assert out["language"] == "en"
        assert mock_client.audio.transcriptions.create.call_count == 3


class TestProviderDispatch:
    def test_groq_backend_uses_groq_base_url(self, tmp_path, monkeypatch):
        """backend='groq' constructs OpenAI(base_url='https://api.groq.com/openai/v1')."""
        from src import openai_transcribe

        video = _make_test_video(tmp_path / "v.mp4", duration_sec=2)
        captured: dict = {}

        def fake_openai(**kwargs):
            captured.update(kwargs)
            client = MagicMock()
            client.audio.transcriptions.create.side_effect = RuntimeError("stop")
            return client

        monkeypatch.setattr(openai_transcribe, "OpenAI", fake_openai)

        with pytest.raises(RuntimeError, match="stop"):
            openai_transcribe.transcribe_via_openai(
                video, backend="groq", api_key="gsk-test", model="whisper-large-v3", language=None,
            )

        assert captured["api_key"] == "gsk-test"
        assert captured["base_url"] == "https://api.groq.com/openai/v1"

    def test_openai_backend_uses_default_base_url(self, tmp_path, monkeypatch):
        """backend='openai' constructs OpenAI(base_url=None) - SDK default."""
        from src import openai_transcribe

        video = _make_test_video(tmp_path / "v.mp4", duration_sec=2)
        captured: dict = {}

        def fake_openai(**kwargs):
            captured.update(kwargs)
            client = MagicMock()
            client.audio.transcriptions.create.side_effect = RuntimeError("stop")
            return client

        monkeypatch.setattr(openai_transcribe, "OpenAI", fake_openai)

        with pytest.raises(RuntimeError, match="stop"):
            openai_transcribe.transcribe_via_openai(
                video, backend="openai", api_key="sk-test", model="whisper-1", language=None,
            )

        assert captured["api_key"] == "sk-test"
        assert captured["base_url"] is None

    def test_unknown_backend_raises(self, tmp_path):
        from src import openai_transcribe
        video = _make_test_video(tmp_path / "v.mp4", duration_sec=2)
        with pytest.raises(ValueError, match="Unknown.*backend"):
            openai_transcribe.transcribe_via_openai(
                video, backend="azure", api_key="x", model="whisper-1", language=None,
            )


class TestTranscribeDispatcher:
    def test_dispatches_to_openai_when_backend_openai(self, tmp_path, monkeypatch):
        """When TRANSCRIBE_BACKEND=openai, transcribe() must call openai_transcribe.transcribe_via_openai
        for steps 1+2 (skipping local whisperx) and still run diarize via _run_step."""
        from src import process, openai_transcribe

        video = _make_test_video(tmp_path / "v.mp4", duration_sec=2)

        openai_called = {"v": False}
        def fake_openai(video_path, *, backend, api_key, model, language):
            openai_called["v"] = True
            return {
                "segments": [{"start": 0.0, "end": 1.0, "text": "Hi", "words": []}],
                "language": "en",
            }

        run_step_scripts = []
        def fake_run_step(script, tmp_dir, timeout=3600):
            import json
            run_step_scripts.append(script)
            # Simulate diarize: read existing data, add speaker, write back.
            data_file = tmp_dir / "pipeline_data.json"
            data = json.loads(data_file.read_text())
            for seg in data["segments"]:
                seg["speaker"] = "SPEAKER_00"
            data_file.write_text(json.dumps(data))

        monkeypatch.setattr(openai_transcribe, "transcribe_via_openai", fake_openai)
        monkeypatch.setattr(process, "_run_step", fake_run_step)

        cfg = {
            "transcribe_backend": "openai",
            "openai_api_key": "sk-x",
            "openai_transcribe_model": "whisper-1",
            "language": None,
            "whisper_model": "medium",
            "hf_token": "hf_x",
            "max_speakers": None,
        }
        result = process.transcribe(str(video), cfg)

        assert openai_called["v"] is True, "openai backend was not invoked"
        # When backend=openai, _run_step is called ONLY for diarize (1 call), not transcribe+align (which would be 3 total)
        assert len(run_step_scripts) == 1, (
            f"_run_step called {len(run_step_scripts)} times; expected 1 (diarize only). "
            f"This means the local transcribe/align path was wrongly invoked."
        )
        assert "DiarizationPipeline" in run_step_scripts[0], "the single _run_step call wasn't diarize"
        assert result["language"] == "en"
        assert result["segments"][0]["speaker"] == "SPEAKER_00"

    def test_uses_local_path_when_backend_local(self, tmp_path, monkeypatch):
        """When backend=local (default), transcribe() must NOT call transcribe_via_openai."""
        from src import process, openai_transcribe

        video = _make_test_video(tmp_path / "v.mp4", duration_sec=2)

        openai_called = {"v": False}
        def fake_openai(*args, **kwargs):
            openai_called["v"] = True
            raise AssertionError("openai backend was called when backend=local")

        run_step_scripts = []
        def fake_run_step(script, tmp_dir, timeout=3600):
            import json
            run_step_scripts.append(script)
            data_file = tmp_dir / "pipeline_data.json"
            # Simulate any of the 3 _run_step calls writing minimal data
            data_file.write_text(json.dumps({
                "segments": [{"start": 0.0, "end": 1.0, "text": "Hi", "speaker": "SPEAKER_00"}],
                "language": "en",
            }))

        monkeypatch.setattr(openai_transcribe, "transcribe_via_openai", fake_openai)
        monkeypatch.setattr(process, "_run_step", fake_run_step)

        cfg = {
            "transcribe_backend": "local",
            "openai_api_key": "",
            "openai_transcribe_model": "whisper-1",
            "language": None,
            "whisper_model": "medium",
            "hf_token": "hf_x",
            "max_speakers": None,
        }
        result = process.transcribe(str(video), cfg)

        assert openai_called["v"] is False
        # Local path runs: transcribe + align + diarize = 3 _run_step calls
        assert len(run_step_scripts) == 3, f"expected 3 _run_step calls (transcribe + align + diarize), got {len(run_step_scripts)}"
        assert result["language"] == "en"
