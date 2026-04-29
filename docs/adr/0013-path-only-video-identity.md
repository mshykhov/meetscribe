# ADR-0013: Path-only video identity (no content hashing)

Status: Accepted
Date: 2026-04-29

## Context

В новой schema (см. [ADR-0008](./0008-sqlite-as-state-authority.md)) `videos.path TEXT UNIQUE` идентифицирует запись. Это поднимает вопрос: достаточно ли пути или нужен content hash для устойчивости к rename / move.

Альтернативы рассмотрены: sha256 of full content (robust к rename / move, но 10 секунд hash на 2 GB видео в watch loop - неприемлемая latency на FSEvent), hybrid path + sha256 заполняемый при first attempt (сложнее implementation, marginal benefit для personal use), first-4MB fingerprint (~50 ms hash, но fragile к identical headers from same source - false positives). Use case: rename / move видео после processing - rare. Watch dir обычно не двигается. User знает где `OUTPUT_DIR`.

## Decision

Мы используем path как единственный identity для записей о видео.

Identity = `videos.path` (TEXT UNIQUE). Если файл переименован или перемещён - это "новая" запись с т.з. db. Старая запись остаётся (state указывает на текущее). Для merge истории при ручном move предусмотрена CLI команда `meetscribe rename <old-path> <new-path>`, которая обновляет path в db и сохраняет attempts / events связанные со старым путём.

## Consequences

**Положительные:**
- Ноль hash computation в watch loop (важно при 2 GB файлах).
- Простой identity model, легко reasoning.
- Обычный SQL `UNIQUE` constraint, никаких custom checks.

**Отрицательные / Trade-offs:**
- Rename без `meetscribe rename` команды теряет history (новая запись, старая orphaned).
- Duplicate detection невозможен по content (но и не нужен в личном workflow - один источник записи).

**Что становится возможным дальше:**
- Phase 3a создаёт schema с этим UNIQUE constraint.
- Phase 3e добавляет `meetscribe rename` команду в CLI.
- Если когда-нибудь понадобится duplicate detection - можно добавить optional `sha256` колонку без ломки existing identity (path остаётся authoritative).
