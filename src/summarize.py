"""Summary stage backend dispatch.

Resolves cfg['summary_backend'] to either a subprocess invocation
(claude_code via Claude Code CLI) or an OpenAI-compatible Chat
Completions call (openai / groq). Rate-limit semantics inherit from
src/openai_transcribe (same RateLimitedError class for isinstance
parity in the process.py handler).
"""

from __future__ import annotations

import subprocess
import time

from openai import OpenAI, APIConnectionError, APITimeoutError, RateLimitError

from src.openai_transcribe import RateLimitedError, _parse_retry_after


_PROVIDERS: dict[str, dict] = {
    "claude_code": {
        "kind": "subprocess",
        "max_transcript_chars": 600_000,
    },
    "openai": {
        "kind": "openai_sdk",
        "base_url": None,
        "api_key_cfg": "openai_api_key",
        "model_cfg": "openai_summary_model",
        "max_transcript_chars": 300_000,
    },
    "groq": {
        "kind": "openai_sdk",
        "base_url": "https://api.groq.com/openai/v1",
        "api_key_cfg": "groq_api_key",
        "model_cfg": "groq_summary_model",
        "max_transcript_chars": 300_000,
    },
}


MAX_RETRIES = 3
RETRY_BACKOFF_SEC = 2


def call_summary_provider(prompt: str, cfg: dict, timeout: int = 600) -> str:
    """Dispatch summary call by cfg['summary_backend']. Returns markdown string."""
    backend = cfg["summary_backend"]
    if backend not in _PROVIDERS:
        raise ValueError(f"Unknown summary backend: {backend!r}")
    kind = _PROVIDERS[backend]["kind"]
    if kind == "subprocess":
        return _call_claude_subprocess(prompt, cfg, timeout)
    if kind == "openai_sdk":
        return _call_openai_chat(prompt, backend, cfg, timeout)
    raise NotImplementedError(f"unknown provider kind: {kind}")


def max_transcript_chars(cfg: dict) -> int:
    """Return per-backend chunking threshold for generate_summary."""
    backend = cfg["summary_backend"]
    if backend not in _PROVIDERS:
        raise ValueError(f"Unknown summary backend: {backend!r}")
    return _PROVIDERS[backend]["max_transcript_chars"]


def _call_claude_subprocess(prompt: str, cfg: dict, timeout: int) -> str:
    result = subprocess.run(
        [cfg["claude_cli"], "-p", "-", "--model", cfg["claude_model"]],
        input=prompt, capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Claude CLI failed: {result.stderr}")
    return result.stdout.strip()


def _call_openai_chat(prompt: str, backend: str, cfg: dict, timeout: int) -> str:
    provider = _PROVIDERS[backend]
    api_key = cfg[provider["api_key_cfg"]]
    if not api_key:
        raise ValueError(f"API key is required when SUMMARY_BACKEND={backend}")
    model = cfg[provider["model_cfg"]]

    client = OpenAI(
        api_key=api_key,
        base_url=provider["base_url"],
        timeout=timeout,
    )

    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.choices[0].message.content.strip()
        except RateLimitError as e:
            retry_after_header = None
            resp = getattr(e, "response", None)
            if resp is not None:
                headers = getattr(resp, "headers", None) or {}
                retry_after_header = headers.get("retry-after") or headers.get("Retry-After")
            retry_after = _parse_retry_after(retry_after_header)
            raise RateLimitedError(backend, retry_after, str(e)[:200]) from e
        except (ConnectionError, TimeoutError, APIConnectionError, APITimeoutError) as e:
            last_err = e
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SEC * attempt)

    assert last_err is not None
    raise last_err
