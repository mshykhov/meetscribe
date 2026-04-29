# ADR-0014: BLOB partial_data column for mid-pipeline crash recovery

Status: Accepted
Date: 2026-04-29

## Context

Phase 1 `docs/error-handling.md` зафиксировал known gap: при crash на стадии 2 или 3 (например, OOM при diarize) вся transcribe-работа теряется. На 60-минутном видео это 5+ минут wasted compute. Это особенно болезненно при местных моделях, где первая стадия самая дорогая.

Альтернативы рассмотрены: file-path approach (`partial_data_path` колонка указывает на JSON файл в `~/.cache/meetscribe/partials/{id}.json` - проще для inspection, но split state между db и FS, что осложняет atomicity), BLOB column в db (atomic с state update, но раздувает db). Размер 5 MB JSON для 60-минутной встречи; in-flight max обычно 1-2 видео = ~10 MB total - приемлемо. WAL mode SQLite (см. [ADR-0008](./0008-sqlite-as-state-authority.md)) хорошо handles BLOB writes до 5 MB на транзакцию.

## Decision

Мы храним промежуточные результаты pipeline в BLOB-колонке state.db для atomic recovery после crash.

Колонка `videos.partial_data BLOB` хранит JSON с `{segments, language}` после последнего успешно завершённого pipeline-шага. Колонка `videos.partial_stage TEXT` хранит имя последнего успешного шага: `'transcribe' | 'align' | 'diarize'`. Worker после каждой стадии: `UPDATE videos SET partial_data = ?, partial_stage = ?, progress = ? WHERE id = ?`. На done: `UPDATE videos SET partial_data = NULL, partial_stage = NULL, state = 'done', ...`. Resume logic worker: при старте, если найдено `state='processing'` (от crashed worker), transition к `state='queued'`. На последующем pickup, если `partial_stage IS NOT NULL` - skip соответствующие шаги pipeline и стартуем после `partial_stage`.

## Consequences

**Положительные:**
- 60-минутное видео упавшее на стадии 3 экономит ~3 минуты compute на retry.
- Resume полностью atomic с state update (одна транзакция).
- Никакого file management overhead, никаких orphaned partials.

**Отрицательные / Trade-offs:**
- ~5 MB BLOB writes на каждой stage transition (но всего 4 раза на видео, под WAL это ~10 ms).
- При corruption db теряется и partial state (mitigation: regular backup db file).

**Что становится возможным дальше:**
- Phase 3c (worker daemon) имплементирует partial_data writes и resume logic.
- Phase 3a (state.db parallel-write) пока этим не пользуется (handler как сейчас не resumable).
