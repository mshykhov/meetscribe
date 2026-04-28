"""Tests for OpenAI transcribe backend."""

import os
from unittest.mock import patch

import pytest


class TestConfigLoading:
    def test_load_config_defaults_to_local_backend(self):
        from src.process import load_config
        with patch.dict(os.environ, {"HF_TOKEN": "hf_x"}, clear=False):
            os.environ.pop("TRANSCRIBE_BACKEND", None)
            cfg = load_config()
        assert cfg["transcribe_backend"] == "local"

    def test_load_config_reads_openai_backend(self):
        from src.process import load_config
        env = {
            "HF_TOKEN": "hf_x",
            "TRANSCRIBE_BACKEND": "openai",
            "OPENAI_API_KEY": "sk-test",
            "OPENAI_TRANSCRIBE_MODEL": "whisper-1",
        }
        with patch.dict(os.environ, env, clear=False):
            cfg = load_config()
        assert cfg["transcribe_backend"] == "openai"
        assert cfg["openai_api_key"] == "sk-test"
        assert cfg["openai_transcribe_model"] == "whisper-1"

    def test_load_config_openai_backend_defaults_model(self):
        from src.process import load_config
        env = {"HF_TOKEN": "hf_x", "TRANSCRIBE_BACKEND": "openai", "OPENAI_API_KEY": "sk-x"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("OPENAI_TRANSCRIBE_MODEL", None)
            cfg = load_config()
        assert cfg["openai_transcribe_model"] == "whisper-1"
