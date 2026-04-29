# Architecture Decision Records

Здесь хранятся короткие записи о значимых архитектурных решениях по проекту meetscribe. Каждая запись описана по формату Майкла Нигарда: Context / Decision / Consequences. Записи иммутабельны: если решение пересмотрено, создаётся новая ADR со ссылкой `Superseded by ADR-NNNN`, а у старой меняется только поле `Status`.

## Index

| ID | Title | Status | Date |
|---|---|---|---|
| [0001](0001-subprocess-isolation-for-pipeline-stages.md) | Subprocess isolation for pipeline stages | Accepted | 2026-04-29 |
| [0002](0002-senko-monkey-patch-for-venv-python.md) | Senko monkey-patch to use venv Python | Accepted | 2026-04-29 |
| [0003](0003-openai-backend-base-url-for-groq-compat.md) | Reuse OpenAI backend for Groq via OPENAI_BASE_URL | Accepted | 2026-04-29 |
| [0004](0004-mkdir-as-atomic-lock.md) | mkdir as atomic single-instance lock | Accepted | 2026-04-29 |
| [0005](0005-swiftbar-status-via-log-parsing.md) | SwiftBar plugin reads pipeline state via log parsing | Accepted | 2026-04-29 |
| [0006](0006-audio-format-ogg-not-opus-for-openai.md) | Audio extracted as Opus-in-Ogg with .ogg extension | Accepted | 2026-04-29 |
| [0007](0007-hf-token-required-for-local-diarization.md) | HF_TOKEN mandatory for diarization | Accepted | 2026-04-29 |

## Как добавить новую ADR

1. Скопируй последний номер из таблицы выше и прибавь 1.
2. Создай файл `NNNN-короткое-имя-в-kebab-case.md`.
3. Используй шаблон из любого существующего ADR (Status / Context / Decision / Consequences).
4. Добавь строку в таблицу выше.
5. Если новая ADR заменяет старую, в старой ADR обнови `Status: Superseded by ADR-NNNN` и при необходимости добавь короткий абзац с рационалом перехода.
