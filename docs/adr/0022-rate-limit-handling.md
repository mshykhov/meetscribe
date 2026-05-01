# ADR-0022: Rate-limit handling via state.db + worker auto-resume

Status: Accepted
Date: 2026-05-01

## Context

OpenAI и Groq Whisper APIs возвращают HTTP 429 при превышении rate limit с `Retry-After` header. Phase 1-3d не handlили это - 429 propagated как обычный exception, видео помечалось `failed`, MAX_RETRIES exhaust-ились в течение секунд (potential ban от провайдера).

Известный gap, отмеченный в Phase 1 `error-handling.md` и Phase 2 spec.

## Decision

Многослойная схема через state.db:

1. `src/openai_transcribe.py`:
   - Catch `openai.RateLimitError`.
   - Parse `Retry-After` header: integer seconds OR HTTP-date format. Default 300s если нет header.
   - Detect backend name из `OPENAI_BASE_URL` (`groq.com` → `"groq"`, else `"openai"`).
   - Raise typed `RateLimitedError(backend, retry_after_seconds, reason)`.

2. `src/process.py`:
   - Catch `RateLimitedError` отдельно от `Exception`.
   - `state.set_rate_limit(backend, until_ts, reason)` - INSERT OR REPLACE в `rate_limits`.
   - `state.set_video_next_attempt(video_id, until_ts)` - delay этого конкретного video.
   - Transition video back to `queued` (НЕ `failed`).
   - Mark attempt with exit_code=2 + error_message=`rate_limited:<backend>`.
   - Re-raise чтобы worker subprocess вышел non-zero.

3. Worker `_pick_next` уже фильтрует по `next_attempt_after` AND `rate_limits.until_ts > now()` (Phase 3a/3c).
   - Worker exits cleanly (queue "пуст" с т.з. eligibility).
   - launchd сам перезапустит worker через polling? Нет - worker on-demand. Нужен trigger.
   - Phase 3a-1 follow-up: SwiftBar 5s polling + watcher на новые FSEvents может re-trigger worker. Если `until_ts` уже прошёл и нет новых events - видео stale.
   - Mitigation: simple cron-like wake-up или re-trigger в watcher на FSEvent. Подробности в Phase 3e-2/3e-3 если станет проблема. Пока - acceptable, user может `meetscribe daemon restart` или `launchctl start worker`.

## Consequences

**Положительные:**
- 429 не сжигает MAX_RETRIES за секунды.
- Backend-wide pause: ВСЕ видео с `backend_used='groq'` ждут unblock.
- SwiftBar UI (Phase 3d) уже читает `rate_limits` table - показывает "Rate-limited until HH:MM" автоматически.
- Идиомaтическая обработка 429: ровно по spec API провайдера.

**Отрицательные / Trade-offs:**
- Auto-resume relies на следующем worker trigger. Если `until_ts` прошёл и нет FSEvent / restart - видео висит queued (acceptable, user может manually trigger).
- Default 300s для отсутствующего Retry-After conservative; может задержать legitimate retry. OK trade-off.
- `RateLimitError` типа openai-sdk - другие провайдеры (Claude, future ones) могут вернуть 429 другим путём. Текущий код handlит только OpenAI-compatible.

**Что становится возможным дальше:**
- Phase 3g (Groq integration) полностью работает - 429 detected, paused, auto-resumes.
- Phase 3e-2 может добавить notification action button "Resume now" (force `until_ts=now()`).
- Future scheduling: cron task `meetscribe wake` чтобы re-trigger worker когда rate-limit window прошёл.
