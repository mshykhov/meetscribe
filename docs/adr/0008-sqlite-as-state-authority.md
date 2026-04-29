# ADR-0008: SQLite as state authority for video pipeline

Status: Accepted
Date: 2026-04-29

## Context

Текущее состояние pipeline хранится в двух flat-файлах: `.processed` и `.failed`, каждый из которых представляет собой список путей к видео по строкам. Подробности см. в Phase 1 документации `docs/watch-handler.md` и `docs/error-handling.md`. Эта схема была выбрана за простоту, но за время эксплуатации накопила ряд ограничений.

Проблемы текущего подхода: `.failed` растёт линейно (одна строка на каждую неудачную попытку, дубликаты намеренные), нет timestamps и контекста ошибок (приходится лезть в `.logs/process-*.log`), есть race-condition между cancel/skip и handler-ом из-за отсутствия транзакций. Аналитические запросы вроде "fail rate by backend last 30 days" просто невозможны - нет структуры для них.

Альтернативы рассмотрены: JSON-файл (нет atomicity, читать целиком на каждое чтение), per-video sidecar JSON (ок, но не даёт aggregate queries), полноценный Postgres (overkill для personal tool на одной машине).

## Decision

Мы используем SQLite в WAL mode по пути `~/.local/share/meetscribe/state.db` (XDG Base Directory) как единый источник правды о состоянии pipeline.

Таблицы: `videos` (master record per file), `attempts` (per-attempt log), `events` (audit trail), `rate_limits` (per-backend pause), `schema_version` (migrations). Полная схема приведена в Phase 2 spec (`docs/superpowers/specs/2026-04-29-target-architecture-design.md`, локальный gitignored файл).

## Consequences

**Положительные:**
- Atomic transactions для consistency между state changes.
- Structured queries для CLI, SwiftBar и web dashboard.
- Concurrent reads через WAL mode без блокировки writers.
- Один файл переносится между машинами при необходимости.
- История per-attempt с timestamps и backend context.

**Отрицательные / Trade-offs:**
- Введена зависимость от sqlite3 (входит в stdlib Python, риск минимальный).
- Migrations требуют дисциплины и `schema_version` tracking.
- Таблица `events` может пухнуть со временем (mitigation: cleanup policy описана в spec).

**Что становится возможным дальше:**
- Phase 3a добавляет state.db parallel-write поверх existing `.processed` / `.failed`.
- Phase 3b делает state.db authoritative и retire-ит flat-файлы.
