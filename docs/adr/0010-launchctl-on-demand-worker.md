# ADR-0010: launchctl-on-demand for worker lifecycle

Status: Accepted
Date: 2026-04-29

## Context

Решение из [ADR-0009](./0009-two-daemon-architecture.md) определяет worker как отдельный daemon, но оставляет открытым вопрос: всегда жив или on-demand. Каждый вариант имеет свой профиль ресурсов и сложности.

Always-alive worker реализуется бесконечным loop с polling state.db (latency vs CPU trade-off на интервал) или с unix socket от watcher-а (добавляет IPC и кастомный протокол). Idle = один процесс держит память (для Python с импортами около 30-50 МБ). On-demand worker: launchctl запускает по требованию, worker дренирует queue и exits. Idle = ноль процессов, ноль памяти. Это идиоматичный для macOS pattern - launchd is the lifecycle manager.

## Decision

Мы используем on-demand worker через launchctl.

Worker plist `com.myron.meetscribe.worker` с `KeepAlive=false` и `RunAtLoad=false`. Watcher после `INSERT INTO videos ... state='queued'` вызывает `launchctl start com.myron.meetscribe.worker` (идемпотентен - launchd no-op если worker уже жив). Worker loop: `SELECT id FROM videos WHERE state='queued' AND (next_attempt_after IS NULL OR next_attempt_after < strftime('%s','now')) ORDER BY detected_at LIMIT 1` → проверяет `rate_limits` по backend → обрабатывает → repeats. Empty result → `sys.exit(0)`. Crash recovery: при старте worker делает `SELECT FROM videos WHERE state='processing'` - если найдено, значит предыдущий worker упал; transition к `state='queued'` и продолжаем (с `partial_data` / `partial_stage` если они есть, см. [ADR-0014](./0014-blob-partial-data-for-crash-recovery.md)).

## Consequences

**Положительные:**
- Idle = ноль ресурсов, ноль памяти.
- Simple lifecycle: run-to-completion, никаких бесконечных loops.
- Launchd handles крэши автоматически.
- Не нужен daemon-specific monitoring.

**Отрицательные / Trade-offs:**
- Latency на запуск worker-а (~100-200 ms для launchd activation).
- Процесс startup overhead на каждое видео (model loading через subprocess - всё ещё применимо per [ADR-0001](./0001-subprocess-isolation-for-pipeline-stages.md)).

**Что становится возможным дальше:**
- Phase 3c создаёт worker daemon plist, заменяет прямой вызов `process.py` из shell handler-а.
