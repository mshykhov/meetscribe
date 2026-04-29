# Architecture Decision Records

Здесь хранятся короткие записи о значимых архитектурных решениях по проекту meetscribe. Каждая запись описана по формату Майкла Нигарда: Context / Decision / Consequences. Записи иммутабельны: если решение пересмотрено, создаётся новая ADR со ссылкой `Superseded by ADR-NNNN`, а у старой меняется только поле `Status`.

## Index

| ID | Title | Status | Date |
|---|---|---|---|
| [0001](0001-subprocess-isolation-for-pipeline-stages.md) | Subprocess isolation for pipeline stages | Accepted | 2026-04-29 |
| [0002](0002-senko-monkey-patch-for-venv-python.md) | Senko monkey-patch to use venv Python | Accepted | 2026-04-29 |
| [0003](0003-openai-backend-base-url-for-groq-compat.md) | Reuse OpenAI backend for Groq via OPENAI_BASE_URL | Accepted | 2026-04-29 |
| [0004](0004-mkdir-as-atomic-lock.md) | mkdir as atomic single-instance lock | Accepted | 2026-04-29 |
| [0005](0005-swiftbar-status-via-log-parsing.md) | SwiftBar plugin reads pipeline state via log parsing | Superseded by [0011](0011-swiftbar-url-scheme-refresh.md) | 2026-04-29 |
| [0006](0006-audio-format-ogg-not-opus-for-openai.md) | Audio extracted as Opus-in-Ogg with .ogg extension | Accepted | 2026-04-29 |
| [0007](0007-hf-token-required-for-local-diarization.md) | HF_TOKEN mandatory for diarization | Accepted | 2026-04-29 |
| [0008](0008-sqlite-as-state-authority.md) | SQLite as state authority | Accepted | 2026-04-29 |
| [0009](0009-two-daemon-architecture.md) | Two-daemon architecture (watcher + worker) | Accepted | 2026-04-29 |
| [0010](0010-launchctl-on-demand-worker.md) | launchctl-on-demand worker lifecycle | Accepted | 2026-04-29 |
| [0011](0011-swiftbar-url-scheme-refresh.md) | SwiftBar URL-scheme refresh trigger | Accepted | 2026-04-29 |
| [0012](0012-phased-migration-strategy.md) | Phased migration over big-bang | Accepted | 2026-04-29 |
| [0013](0013-path-only-video-identity.md) | Path-only video identity | Accepted | 2026-04-29 |
| [0014](0014-blob-partial-data-for-crash-recovery.md) | BLOB partial_data for crash recovery | Accepted | 2026-04-29 |
| [0015](0015-typer-as-cli-framework.md) | typer as CLI framework | Accepted | 2026-04-29 |
| [0016](0016-sql-file-migrations.md) | SQL-file migrations | Accepted | 2026-04-29 |
| [0017](0017-watchdog-library-and-threading-model.md) | watchdog library + threading | Accepted | 2026-04-29 |
| [0018](0018-no-processed-failed-migration.md) | No migration of .processed/.failed | Accepted | 2026-04-29 |

## Как добавить новую ADR

1. Скопируй последний номер из таблицы выше и прибавь 1.
2. Создай файл `NNNN-короткое-имя-в-kebab-case.md`.
3. Используй шаблон из любого существующего ADR (Status / Context / Decision / Consequences).
4. Добавь строку в таблицу выше.
5. Если новая ADR заменяет старую, в старой ADR обнови `Status: Superseded by ADR-NNNN` и при необходимости добавь короткий абзац с рационалом перехода.
