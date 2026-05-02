# ADR-0024: First-class summary providers

## Status
Accepted (2026-05-02). Mirrors ADR-0023 (transcribe providers).

## Context
ADR-0023 introduced first-class transcribe providers. The summary stage
remained hardcoded to Claude Code CLI subprocess, with no fallback when
the subscription is exhausted and no cheaper/faster alternative for
casual recaps.

## Decision
`SUMMARY_BACKEND` is a first-class enum (`claude_code` | `openai` |
`groq`). Each provider has its own per-stage model env var
(`CLAUDE_MODEL`, `OPENAI_SUMMARY_MODEL`, `GROQ_SUMMARY_MODEL`). API keys
are shared across stages (`OPENAI_API_KEY`, `GROQ_API_KEY`) because a
provider account has one key regardless of stage.

`src/summarize.py` contains the dispatch table `_PROVIDERS` plus
`call_summary_provider(prompt, cfg, timeout)`. Each provider entry
declares `kind` (`subprocess` | `openai_sdk`); `claude_code` is the
only `subprocess` entry. `openai` and `groq` use the OpenAI SDK Chat
Completions API.

The shape of `_PROVIDERS` differs from the transcribe `_PROVIDERS`
(no `kind` field there) because transcribe never has a subprocess
provider - `local` (whisperx-mlx) is dispatched at the process.py level
rather than inside `transcribe_via_openai`. Summary's split between
subprocess and SDK happens inside one dispatcher to keep
`generate_summary`'s chunking logic backend-agnostic.

`max_transcript_chars` is per-backend because GPT-4o-mini and Llama
3.3 70B have ~128k token contexts vs Claude Sonnet's 200k. Russian
content packs ~0.55 tokens/char; switching to Groq with a long Russian
transcript would overflow if a single threshold were used.

## Consequences
- Switching to Groq for summary is one env var change + one new
  model name; reuses the Groq API key already set for transcribe.
- A 429 from any provider on either stage pauses just that provider
  (single `backend` row in `rate_limits`); both stages auto-resume
  when `until_ts` elapses.
- The existing `RateLimitedError` class is reused (imported from
  `src/openai_transcribe.py`); no isinstance changes in the
  process.py handler.
- Sidecar can pin a specific video to a different summary provider:
  `summary_backend = "groq"` + `groq_summary_model = "..."`.

## Alternatives considered
- Add `anthropic_api` as a fourth provider. Rejected as YAGNI;
  separate phase if Claude quality without subscription becomes
  necessary.
- Single global `MAX_TRANSCRIPT_CHARS` calibrated to the smallest
  context (128k tokens). Rejected: regresses Claude users on long
  meetings (forces chunking when a single-shot would fit).
- Hoist `RateLimitedError` to a shared `src/api_common.py`. Rejected:
  scope creep; the import-from-transcribe coupling is acceptable.
