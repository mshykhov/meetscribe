"""Tests for src/summarize.py: dispatch + claude_code subprocess + openai_sdk Chat Completions."""

from unittest.mock import MagicMock, patch

import pytest


def test_max_transcript_chars_per_backend():
    from src.summarize import max_transcript_chars
    assert max_transcript_chars({"summary_backend": "claude_code"}) == 600_000
    assert max_transcript_chars({"summary_backend": "openai"}) == 300_000
    assert max_transcript_chars({"summary_backend": "groq"}) == 300_000


def test_unknown_backend_raises():
    from src.summarize import call_summary_provider
    with pytest.raises(ValueError, match="Unknown summary backend"):
        call_summary_provider("hi", {"summary_backend": "azure"})


def test_claude_code_subprocess_path():
    """backend=claude_code shells out to cfg['claude_cli']."""
    from src.summarize import call_summary_provider

    cfg = {
        "summary_backend": "claude_code",
        "claude_cli": "claude",
        "claude_model": "claude-sonnet-4-6",
    }
    fake_result = MagicMock(returncode=0, stdout="summary text\n", stderr="")

    with patch("src.summarize.subprocess.run", return_value=fake_result) as mock_run:
        out = call_summary_provider("test prompt", cfg)

    assert out == "summary text"
    args = mock_run.call_args.args[0]
    assert args[0] == "claude"
    assert "--model" in args and args[args.index("--model") + 1] == "claude-sonnet-4-6"


def test_claude_code_raises_on_nonzero_exit():
    from src.summarize import call_summary_provider

    cfg = {
        "summary_backend": "claude_code",
        "claude_cli": "claude",
        "claude_model": "claude-sonnet-4-6",
    }
    fake_result = MagicMock(returncode=1, stdout="", stderr="quota exhausted")

    with patch("src.summarize.subprocess.run", return_value=fake_result):
        with pytest.raises(RuntimeError, match="Claude CLI failed"):
            call_summary_provider("test", cfg)


def test_openai_sdk_groq_path(monkeypatch):
    """backend=groq uses OpenAI SDK with groq base_url + Groq API key."""
    from src import summarize

    cfg = {
        "summary_backend": "groq",
        "groq_api_key": "gsk-abc",
        "groq_summary_model": "llama-3.3-70b-versatile",
    }

    captured: dict = {}

    def fake_openai(**kwargs):
        captured.update(kwargs)
        client = MagicMock()
        client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="groq summary"))]
        )
        return client

    monkeypatch.setattr(summarize, "OpenAI", fake_openai)

    out = summarize.call_summary_provider("test prompt", cfg)

    assert out == "groq summary"
    assert captured["api_key"] == "gsk-abc"
    assert captured["base_url"] == "https://api.groq.com/openai/v1"


def test_openai_sdk_openai_path(monkeypatch):
    """backend=openai uses OpenAI SDK with default base_url + OpenAI API key."""
    from src import summarize

    cfg = {
        "summary_backend": "openai",
        "openai_api_key": "sk-abc",
        "openai_summary_model": "gpt-4o-mini",
    }

    captured: dict = {}

    def fake_openai(**kwargs):
        captured.update(kwargs)
        client = MagicMock()
        client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="openai summary"))]
        )
        return client

    monkeypatch.setattr(summarize, "OpenAI", fake_openai)

    out = summarize.call_summary_provider("test prompt", cfg)

    assert out == "openai summary"
    assert captured["api_key"] == "sk-abc"
    assert captured["base_url"] is None


def test_openai_sdk_missing_api_key_raises(monkeypatch):
    """backend=openai with empty key raises ValueError before any network call."""
    from src import summarize

    cfg = {
        "summary_backend": "openai",
        "openai_api_key": "",
        "openai_summary_model": "gpt-4o-mini",
    }
    monkeypatch.setattr(summarize, "OpenAI", lambda **k: MagicMock())

    with pytest.raises(ValueError, match="API key is required"):
        summarize.call_summary_provider("test", cfg)


def test_openai_sdk_429_raises_rate_limited_error(monkeypatch):
    """429 from chat.completions raises RateLimitedError(backend, retry_after)."""
    import importlib
    from src import openai_transcribe, summarize
    # Other tests reload openai_transcribe; reload both so RateLimitedError
    # identity matches between summarize and the import below.
    importlib.reload(openai_transcribe)
    importlib.reload(summarize)
    from src.openai_transcribe import RateLimitedError
    from openai import RateLimitError

    cfg = {
        "summary_backend": "groq",
        "groq_api_key": "gsk-abc",
        "groq_summary_model": "llama-3.3-70b-versatile",
    }

    mock_response = MagicMock()
    mock_response.headers = {"retry-after": "30"}
    err = RateLimitError("rate limited", response=mock_response, body=None)
    client = MagicMock()
    client.chat.completions.create.side_effect = err
    monkeypatch.setattr(summarize, "OpenAI", lambda **k: client)

    with pytest.raises(RateLimitedError) as excinfo:
        summarize.call_summary_provider("test", cfg)

    assert excinfo.value.backend == "groq"
    assert excinfo.value.retry_after_seconds == 30


def test_groq_413_tpm_rate_limit_raises_rate_limited_error(monkeypatch):
    """Groq returns HTTP 413 + body.error.code='rate_limit_exceeded' for TPM throttling.

    OpenAI SDK wraps 413 in APIStatusError (subclass of BadRequestError, NOT RateLimitError).
    Without explicit handling these were swallowed by process.py's generic except and
    replaced with a 'meeting' placeholder summary instead of being retried.
    """
    import importlib
    from src import openai_transcribe, summarize
    importlib.reload(openai_transcribe)
    importlib.reload(summarize)
    from src.openai_transcribe import RateLimitedError
    from openai import APIStatusError

    cfg = {
        "summary_backend": "groq",
        "groq_api_key": "gsk-abc",
        "groq_summary_model": "llama-3.3-70b-versatile",
    }

    mock_response = MagicMock()
    mock_response.headers = {}
    mock_response.status_code = 413
    body = {
        "error": {
            "message": "Request too large for model `llama-3.3-70b-versatile`",
            "type": "tokens",
            "code": "rate_limit_exceeded",
        }
    }
    err = APIStatusError("request too large", response=mock_response, body=body)
    client = MagicMock()
    client.chat.completions.create.side_effect = err
    monkeypatch.setattr(summarize, "OpenAI", lambda **k: client)

    with pytest.raises(RateLimitedError) as excinfo:
        summarize.call_summary_provider("test", cfg)

    assert excinfo.value.backend == "groq"
    assert excinfo.value.retry_after_seconds == 60


def test_groq_other_400_errors_propagate(monkeypatch):
    """Non-rate-limit 4xx errors (e.g. invalid model) must NOT be wrapped as rate-limit."""
    import importlib
    from src import openai_transcribe, summarize
    importlib.reload(openai_transcribe)
    importlib.reload(summarize)
    from openai import APIStatusError

    cfg = {
        "summary_backend": "groq",
        "groq_api_key": "gsk-abc",
        "groq_summary_model": "invalid-model",
    }

    mock_response = MagicMock()
    mock_response.headers = {}
    mock_response.status_code = 404
    body = {"error": {"message": "model not found", "code": "model_not_found"}}
    err = APIStatusError("not found", response=mock_response, body=body)
    client = MagicMock()
    client.chat.completions.create.side_effect = err
    monkeypatch.setattr(summarize, "OpenAI", lambda **k: client)

    with pytest.raises(APIStatusError):
        summarize.call_summary_provider("test", cfg)
