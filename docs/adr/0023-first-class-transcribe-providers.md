# ADR-0023: First-class transcribe providers

## Status
Accepted (2026-05-02). Supersedes ADR-0003 (Variant A).

## Context
ADR-0003 chose "OpenAI-compatible umbrella" (`OPENAI_BASE_URL`) for Groq
support. In practice this means putting Groq's API key into
`OPENAI_API_KEY` and Groq's URL into `OPENAI_BASE_URL` - names that lie
about which provider is being used. Additionally `OPENAI_BASE_URL` was
read for rate-limit grouping but never passed to `OpenAI(base_url=...)`,
so it never actually rerouted requests.

## Decision
Each transcribe provider is a first-class `TRANSCRIBE_BACKEND` enum
value (`local`, `openai`, `groq`) with its own provider-named env vars
(`OPENAI_API_KEY` / `OPENAI_TRANSCRIBE_MODEL`,
`GROQ_API_KEY` / `GROQ_TRANSCRIBE_MODEL`). Implementation routes
through the OpenAI SDK with a hard-coded `base_url` per provider via
an internal `_PROVIDERS` dict in `src/openai_transcribe.py`. The SDK
choice is hidden from the user.

## Consequences
- Names are honest: `GROQ_API_KEY` holds a Groq key, `OPENAI_API_KEY`
  holds an OpenAI key.
- Adding a new compatible host (Together, DeepInfra) is two lines in
  `_PROVIDERS` + an enum entry.
- `OPENAI_BASE_URL` retired (it never worked).
- Sidecar `transcribe_backend = "groq"` becomes legal automatically.
- Validation gains a symmetric cross-key rule: groq backend requires
  `GROQ_API_KEY` (mirrors openai requires `OPENAI_API_KEY`).

## Alternatives considered
- Variant A (ADR-0003): kept the umbrella. Rejected: lying names.
- Single `BACKEND_API_KEY` shared field. Rejected: switching backends
  forces re-pasting the key.
- Separate `_transcribe.py` module per provider. Rejected: the OpenAI
  SDK genuinely handles both - duplicating the upload / response /
  retry logic would multiply the maintenance surface for no gain.
