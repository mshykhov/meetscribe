# Sidecar `.meetscribe.toml` per-video config

Drop a `<stem>.meetscribe.toml` next to a video in `WATCH_DIR` to override
config for that video only. No sidecar = use `.env` defaults.

## Allowed keys

| Key | Type | Allowed values |
|-----|------|----------------|
| `transcribe_backend` | string | `"local"` (whisperx-mlx) or `"openai"` (OpenAI/Groq via OPENAI_BASE_URL) |
| `language` | string | `"ru"`, `"en"`, `""` (auto), or any whisper-supported tag |
| `whisper_model` | string | `"tiny"`, `"base"`, `"small"`, `"medium"`, `"large-v2"`, `"large-v3"` |
| `openai_transcribe_model` | string | passed through (e.g. `"whisper-1"`, `"whisper-large-v3"`) |
| `max_speakers` | int >= 0 | `0` = auto-detect |
| `claude_model` | string | passed through (e.g. `"claude-sonnet-4-6"`, `"claude-haiku-4-5"`) |

## Forbidden keys

`hf_token`, `openai_api_key` (secrets - keep in `.env`),
`claude_cli`, `output_dir`, `WATCH_DIR` (system paths).

Any unknown key, type mismatch, or forbidden key marks the video as
`state='invalid'` and shows an error notification.

## Examples

### Short Russian standup with cheap summary

```toml
# standup-2026-05-02.meetscribe.toml
language = "ru"
whisper_model = "small"
claude_model = "claude-haiku-4-5"
max_speakers = 5
```

### Long English all-hands with best Sonnet summary

```toml
# all-hands-2026-05-15.meetscribe.toml
language = "en"
whisper_model = "large-v2"
claude_model = "claude-sonnet-4-6"
max_speakers = 12
```

### 1-on-1 forcing OpenAI transcribe

```toml
# 1-on-1-anna-2026-05-03.meetscribe.toml
transcribe_backend = "openai"
language = "en"
max_speakers = 2
```

## When sidecar is read

The sidecar is read once when the worker starts processing the video. If
you create or edit the sidecar after the video is already done, run
`meetscribe retry <id>` to re-process with the new settings.
