# ADR-0018: No migration of .processed / .failed files

Status: Accepted
Date: 2026-04-29

## Context

Phase 3a добавил state.db. Phase 3b делает state.db authoritative и retire-ит shell handler. На момент перехода у пользователя есть `.processed` (paths успешно обработанных видео) и `.failed` (paths failed attempts, дубликаты намеренные = count of fails).

Альтернативы рассмотрены:
- Auto-migration на startup: читать .processed/.failed, INSERT историю в state.db. Edge cases: paths что уже не существуют, mtime как detected_at, потерянная информация про backend/error.
- Manual `meetscribe migrate-history` команда: то же что auto, но явно. Лишний шаг для user.
- Daemon checks union state.db + .processed/.failed: dual sources, что-то одно lying.
- No migration: state.db starts fresh. .processed/.failed остаются на диске для reference.

Ключевое наблюдение: старый handler **moved** успешно обработанные видео из `WATCH_DIR` в `OUTPUT_DIR`. То есть .processed paths больше не в WATCH_DIR - daemon FSEvent их не увидит. .failed paths возможно ещё в WATCH_DIR - daemon retry-ит как новые. Это feature, не bug.

## Decision

Phase 3b НЕ мигрирует `.processed` и `.failed` в state.db. State.db инициализируется только с Phase 3a данными (или пустая, если Phase 3a database не существовала). Старые файлы остаются на диске как archive для reference. Удаление - manual when ready.

## Consequences

**Положительные:**
- Ноль migration code = ноль edge cases (что если path не существует, что если уже мигрирован, что если daemon рестартится посреди).
- State.db чистая - содержит только well-defined Phase 3a+ данные с полным контекстом (backend, error_message, attempts).
- Старая история не теряется - `.processed` и `.failed` archive на диске.

**Отрицательные / Trade-offs:**
- Pre-Phase-3b история не запросима через `meetscribe ls` или `meetscribe show`. User может `cat .processed`.
- Failed видео которые ещё в WATCH_DIR получают retry под новым daemon. Если pre-Phase-3b они хитнули MAX_RETRIES, теперь counter с 0 -> 3 retry-я. Side-effect - дополнительные attempts.
- Counter `.failed` count != `state.db.attempts.attempt_num` - расхождение в учёте.

**Что становится возможным дальше:**
- Если когда-нибудь захочется migration utility - можно добавить `meetscribe migrate-history` команду. Не блокер сейчас.
- Phase 3X где будем удалять `.processed.deprecated` / `.failed.deprecated` files (например Phase 3e после уверенности что daemon стабилен).
