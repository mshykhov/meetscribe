# ADR-0019: Cancel via state.db state='cancelled' between pipeline stages

Status: Accepted
Date: 2026-04-30

## Context

Phase 3c добавляет `meetscribe cancel <id>` CLI команду. Pipeline (`src/process.py`) работает в worker subprocess; нужен механизм чтобы CLI команда могла остановить running pipeline.

Альтернативы рассмотрены:
- POSIX signal (SIGUSR1) от CLI к worker subprocess: требует tracking PID, fragile в presence of subprocess.run.
- Lock-файл "please cancel": дополнительный side-channel.
- IPC через named pipe: complex для personal tool.
- State.db сигнал: pipeline checks state at safe points; CLI просто пишет в db.

## Decision

`meetscribe cancel <id>` команда делает `UPDATE videos SET state='cancelled' WHERE id=?`. Pipeline в `src/process.py` между каждым шагом (`transcribe`, `align`, `diarize`, `summary`) вызывает `_check_cancelled(video_id)` который читает state.db и кидает `CancelledError` если state='cancelled'. Subprocess exits с non-zero. Worker видит final state='cancelled' и нотифицирует "Отменено".

Granularity: cancel срабатывает между шагами, не mid-stage. Latency до реакции = время текущего шага (макс 5-10 минут для длинного видео на медленном backend).

## Consequences

**Положительные:**
- Простой механизм: state.db уже single source of truth, одна точка cancel.
- Atomic: state transition в одной транзакции.
- Cancel + retry workflow: cancelled video можно retry через `meetscribe retry`, partial_data сохранён (см. [ADR-0020](./0020-partial-data-writes-in-process-py.md)) - resume с прошлого шага.
- Не нужно signal-handling в pipeline subprocess.

**Отрицательные / Trade-offs:**
- Latency: cancel срабатывает не моментально. Если user хочет немедленно убить - `meetscribe daemon stop` + force-kill subprocess. Это документировано как known limitation.
- Pipeline subprocess делает SQLite read на каждом stage transition - <1ms overhead.
- Если db unavailable, `_check_cancelled` тихо no-op-ит (логируется warning). Pipeline продолжается.

**Что становится возможным дальше:**
- Phase 3e может добавить SwiftBar [Cancel] button (вызывает `meetscribe cancel`).
- Если когда-нибудь захочется finer granularity - можно добавить `_check_cancelled` checks внутри `_run_step` subprocess scripts (для локального backend) или периодические checks в `transcribe_via_openai`.
