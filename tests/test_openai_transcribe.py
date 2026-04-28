"""Tests for OpenAI transcribe backend."""

import os
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
