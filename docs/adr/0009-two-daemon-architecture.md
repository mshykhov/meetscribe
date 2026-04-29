# ADR-0009: Two-daemon architecture (watcher + on-demand worker)

Status: Accepted
Date: 2026-04-29

## Context

Phase 1 использует один shell-handler `scripts/watch-handler.sh`, который запускается launchd-ом на FSEvent, делает stability check, lock, и сам же вызывает `python -m src.process`. Watch-логика и pipeline смешаны в одном скрипте плюс Python-процессе. Это работает, но coupling-ит две разные ответственности и затрудняет независимое тестирование.

Альтернативы рассмотрены: single Python daemon (FSEvent + pipeline в одном процессе - простой mental model, но любой crash в pipeline убивает watcher и теряются последующие FSEvent-ы), two-daemon (separation of concerns, но больше инфраструктуры в виде двух plist-ов), hybrid с shell handler + Python daemon только для UI (split логики между языками без выигрыша).

## Decision

Мы используем два Python-демона: `meetscribed-watcher` (always-alive) и `meetscribed-worker` (on-demand).

`meetscribed-watcher`: launchd `KeepAlive=true`, `RunAtLoad=true`. Слушает FSEvent, делает stability check inline, пишет в state.db, триггерит worker через `launchctl start`. `meetscribed-worker`: launchd `KeepAlive=false`, `RunAtLoad=false`. Запускается по требованию, дренирует записи `state='queued'`, обновляет state.db с progress, exits на пустой queue. Подробности lifecycle worker-а см. [ADR-0010](./0010-launchctl-on-demand-worker.md). Inter-daemon communication только через state.db: никакого socket, pipe или shared memory. Watcher signals worker через `launchctl start` (системный вызов, не IPC).

## Consequences

**Положительные:**
- Separation of concerns: watcher всегда жив, pipeline crash изолирован в worker.
- Обе компоненты можно тестировать независимо.
- Single source of truth для state - это state.db.
- Launchd берёт на себя restart logic для watcher-а.

**Отрицательные / Trade-offs:**
- Две точки отказа (но launchd рестартит watcher автоматически; worker on-demand - умер = launchd запустит на следующий сигнал).
- Короткая race window если watcher signals worker, который только что exit-ed (mitigation: `launchctl start` идемпотентен, а spurious worker wake-ups дёшевы - просто проверяет queue и сразу exits).

**Что становится возможным дальше:**
- Phase 3b создаёт watcher daemon, `scripts/watch-handler.sh` retired.
- Phase 3c создаёт worker daemon, replaces direct `process.py` invocation.
