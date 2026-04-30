# ADR-0020: partial_data BLOB writes at end of each pipeline stage in src/process.py

Status: Accepted
Date: 2026-04-30

## Context

[ADR-0014](./0014-blob-partial-data-for-crash-recovery.md) зафиксировал решение хранить partial pipeline output в `videos.partial_data` BLOB для crash recovery. Phase 3c имплементирует это в `src/process.py`.

Открытый вопрос: **где** делать partial_data writes - в process.py или в worker.py?

Альтернативы рассмотрены:
- В process.py между шагами в `transcribe()` функции: write после каждой стадии (transcribe, align, diarize). Прямая интеграция с уже существующими state writes (Phase 3a).
- В worker.py через парсинг stdout subprocess: worker наблюдает [N/4] markers и отдельно делает partial writes. Coupled to log format.
- В отдельном wrapper script вокруг process.py: лишний слой.

## Decision

`src/process.py` пишет partial_data в state.db после каждого успешно завершённого pipeline-шага (`transcribe`, `align`, `diarize`):
- Helper `_write_partial(video_id, data, partial_stage)` инкапсулирует UPDATE.
- При старте `transcribe()` функция вызывает `_load_partial(video_id)` чтобы определить с какого шага resume-иться.
- На done в `process_video()` partial_data + partial_stage очищаются (set NULL) - для успешно done больше не нужно.

Backend-specific логика:
- Local backend: после step 1 (transcribe) -> write partial_stage='transcribe'. После step 2 (align) -> 'align'. После step 3 (diarize) -> 'diarize'.
- OpenAI backend: stages 1+2 объединены в один API вызов, write partial_stage='align' напрямую (skipping 'transcribe' value).

Resume:
- partial_stage=None -> start from stage 1.
- partial_stage='transcribe' -> load partial_data, start from align.
- partial_stage='align' -> start from diarize.
- partial_stage='diarize' -> start from summary (stage 4 в process_video).

## Consequences

**Положительные:**
- 60-минутное видео crash в стадии 3 экономит ~3 минуты compute на retry (skip already-done transcribe + align).
- Atomic: partial_data + state writes в одной транзакции (через `state.connection()` context manager).
- Single source of truth - process.py владеет partial_data semantics, worker не знает про неё.
- Cancel + retry workflow: cancelled video resumes с last completed stage.

**Отрицательные / Trade-offs:**
- BLOB writes на каждой stage transition - но всего 3 раза на видео (transcribe + align + diarize). Под WAL это ~10ms каждый.
- ~5MB BLOB для 60-минутного видео; in-flight max ~10MB across queued.
- Code complexity в transcribe() возрастает (resume forking логика). Mitigated через unit tests с each resume path.

**Что становится возможным дальше:**
- Phase 3e может использовать partial_data для UI: "Last successful stage: align" в SwiftBar dropdown.
- Если когда-нибудь partial_data станет слишком большим - можно перейти на file-path approach (`videos.partial_data_path` указывает на JSON файл в `~/.cache/meetscribe/partials/{id}.json`). ADR будет superseded.
