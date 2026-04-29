# ADR-0011: SwiftBar plugin reads state.db with URL-scheme refresh trigger

Status: Accepted
Date: 2026-04-29

## Context

[ADR-0005](./0005-swiftbar-status-via-log-parsing.md) зафиксировал решение Phase 1: SwiftBar plugin парсит `pipeline.log` и `process-EPOCH.log` регэксами вроде `\[[1-4]/4\]` для определения текущего шага pipeline. Это работало, но за время эксплуатации проявились ограничения.

Проблемы выявленные в use: (1) любой рефакторинг print-statement-ов в `process.py` ломает SwiftBar незаметно - нет compile-time связи между логами и UI; (2) polling каждую секунду плюс grep по растущему файлу неэффективен, особенно когда лог уже в десятках МБ; (3) latency state changes до 1 секунды из-за интервала polling-а; (4) tight coupling UI-слоя к format логов делает рефакторинг логирования рискованной операцией.

Phase 2 переносит state в SQLite (см. [ADR-0008](./0008-sqlite-as-state-authority.md)). Это создаёт возможность читать структурированный state вместо парсинга логов и push-style уведомления о смене состояния.

## Decision

Мы используем SwiftBar plugin, читающий напрямую state.db, с push-уведомлениями через SwiftBar URL scheme.

SwiftBar plugin переименовывается в `meetscribe.5s.sh` (poll каждые 5 секунд как fallback). Plugin читает `state.db` напрямую SQL-запросами через `sqlite3` CLI или Python wrapper. Watcher и worker после каждой state-changing транзакции вызывают `open "swiftbar://refreshplugin?name=meetscribe"` - SwiftBar мгновенно перечитывает plugin (sub-second latency). Никакого custom Swift app, никакого socket - SwiftBar URL scheme это native API.

## Consequences

**Положительные:**
- Log format может рефакториться без страха сломать UI.
- Latency state change → menu bar update меньше 100 ms.
- Idle CPU около 0 (5-секундный poll читает 1-2 строки db).
- Чёткое разделение: pipeline пишет state, UI его читает.

**Отрицательные / Trade-offs:**
- Зависимость от наличия `swiftbar://refreshplugin` URL scheme в установленной версии SwiftBar (mitigation: Phase 3d task 0 проверяет на user's machine; fallback - 2-секундный poll если URL scheme не работает).
- На 5 секунд polling latency в idle если URL refresh пропустит call (acceptable для idle case).

**Что становится возможным дальше:**
- Phase 3d переписывает plugin shell-скрипт, добавляет refresh-trigger calls в watcher / worker, добавляет [Retry] / [Cancel] / [Skip] buttons вызывающие CLI команды.
