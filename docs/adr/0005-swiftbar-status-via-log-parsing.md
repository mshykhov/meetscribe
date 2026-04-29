# ADR-0005: SwiftBar plugin reads pipeline state via log parsing

Status: Accepted
Date: 2026-04-29

## Context

SwiftBar plugin для menu bar реализован как shell-скрипт `*.1s.sh`, который SwiftBar запускает раз в секунду для refresh содержимого иконки и dropdown. Plugin-у нужно знать, на какой стадии сейчас находится pipeline (или idle), чтобы показать прогресс.

Возможные подходы: настоящий IPC через named pipe / Unix socket / shared memory; писать current state в отдельный status-файл; парсить уже существующие логи pipeline-а. IPC требует, чтобы pipeline и plugin одинаково корректно работали с lifecycle сокета и cleanup-ом - лишняя сложность для personal-tool.

Текущая реализация в `scripts/swiftbar-plugin.1s.sh:11-70` парсит `pipeline.log` и `.logs/process-<epoch>.log` через grep и sed по предсказуемым маркерам, которые pipeline уже эмитит для пользователя.

## Decision

Plugin парсит `pipeline.log` и `.logs/process-<epoch>.log` через grep/sed по известным маркерам. Используются: `[N/4] Step name` для текущего шага, `Detected language: X`, `Transcript: N segments`, `Transcription progress: X%`, `Summarizing chunk N/M`, `Backend: senko`. Никакого IPC: pipeline пишет structured-enough log lines, plugin их scrape-ит.

## Consequences

**Положительные:**
- Ноль coupling: plugin крашится - pipeline ничего не замечает; pipeline или handler крашатся - последний log читаем для дебага руками.
- Не нужны сетевые сокеты, дополнительные файловые права или cleanup при сбоях.

**Отрицательные / Trade-offs:**
- Изменение формата лога незаметно ломает plugin. Mitigation в Phase 2 - regression test, который проверяет, что `[N/4]` маркеры эмитятся в `print()` внутри `transcribe()`.
- Per-second `grep` по растущему файлу неэффективен. Это приемлемо при ротации до 20 файлов и обычной длине лога, но не масштабируется.

**Что становится возможным дальше:**
- Phase 2 пометит `[N/4]` как stable contract и добавит test, чтобы рефакторинг (вытаскивание шагов в модули, переименование функций) не сломал SwiftBar незаметно.
