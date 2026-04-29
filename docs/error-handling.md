# Error handling

## Три уровня retry

В системе три независимых уровня retry. Внешний (L1) - на уровне файла в shell handler-е: launchd запускает handler заново до `MAX_RETRIES` раз. Средний (L2) - в `process.py` для diarize: до 3 попыток подряд внутри одного запуска, при полном провале pipeline продолжается без speaker labels. Внутренний (L3) - в `openai_transcribe.py` для transient API errors: до 3 попыток с экспоненциальным backoff. Диаграмма ниже показывает их взаимодействие.

```mermaid
flowchart TD
    Start([Pipeline start])

    subgraph L1["Level 1 - File-level (handler)"]
        L1Run[handler runs python -m src.process]
        L1Exit{exit code}
        L1Append[append to .failed]
        L1Count{fail count >= MAX_RETRIES (3)?}
        L1Skip[skip permanently]
        L1Touch[touch WATCH_DIR -> launchd retrigger]
    end

    subgraph L2["Level 2 - Diarize (process.py)"]
        L2Run[_run_step diarize subprocess]
        L2Exit{exit code}
        L2Attempt{attempt < 3?}
        L2NoSpkr[continue without speakers]
    end

    subgraph L3["Level 3 - API (openai_transcribe.py)"]
        L3Call[client.audio.transcriptions.create]
        L3Catch{ConnectionError / APIConnectionError / APITimeoutError?}
        L3AttemptCheck{attempt < MAX_RETRIES (3)?}
        L3Sleep[sleep RETRY_BACKOFF_SEC * attempt]
        L3Raise[raise]
    end

    Start --> L1Run
    L1Run --> L1Exit
    L1Exit -->|0| Done([done])
    L1Exit -->|!=0| L1Append
    L1Append --> L1Count
    L1Count -->|yes| L1Skip
    L1Count -->|no| L1Touch
    L1Touch -.next FSEvent.-> L1Run

    L1Run --> L2Run
    L2Run --> L2Exit
    L2Exit -->|0| Done
    L2Exit -->|!=0| L2Attempt
    L2Attempt -->|yes| L2Run
    L2Attempt -->|no| L2NoSpkr
    L2NoSpkr --> Done

    L1Run --> L3Call
    L3Call --> L3Catch
    L3Catch -->|no, success| Done
    L3Catch -->|yes, retryable| L3AttemptCheck
    L3AttemptCheck -->|yes| L3Sleep
    L3Sleep --> L3Call
    L3AttemptCheck -->|no| L3Raise
    L3Raise --> L1Exit
```

## Failure modes

| Сбой | Где ловится | User-visible | Side effect |
|---|---|---|---|
| ffmpeg failure | RuntimeError в `extract_audio_to_opus` | error notification | строка в `.failed` |
| Audio > 25 MB | ValueError в `validate_audio_size` | error notification + подсказка про OPENAI_BASE_URL/local | строка в `.failed` |
| OpenAI/Groq 429 / 5xx | NOT currently handled | crash, шумная notification | строка в `.failed`, retry на L1 |
| Senko subprocess fail | RuntimeError, retry 3x в `transcribe()` | warning в логе | продолжаем без спикеров |
| Claude CLI fail | catch в `process_video` | warning в логе | summary файл с error message, transcript всё равно сохранён |
| Video > 4h | ValueError рано | error notification | строка в `.failed` |
| Disk full / write failure | uncaught | crash | partial output, manual cleanup |
| stability timeout (>1h) | shell continue | error notification | строка в `.failed` |
| recording timeout (>1h lsof) | shell continue | error notification | строка в `.failed` |

## Что не retry-ится

- `ValueError` (file too large, video too long): требует user action (split video, switch backend).
- ffmpeg failures: типично corrupted input, нет смысла retry-ить.
- File-system errors (disk full, permission denied): требуют user action.
- Claude CLI failures: один retry бесполезен, проблема обычно в prompt size или CLI auth.

## Известные пробелы (target Phase 3)

- **429 rate limit от OpenAI/Groq**: сейчас обрабатывается как обычная ошибка. Не парсится `Retry-After` header. Phase 3 добавит:
  1. Detection 429 в loop API retry.
  2. Sleep на `Retry-After` секунд (дополнительно к existing `RETRY_BACKOFF_SEC * attempt`).
  3. Notification "Groq rate limit hit, waiting Xm".
  4. SwiftBar dropdown показывает "Rate-limited until HH:MM".
- **Partial save при transcribe failure**: если падает в стадии 1 (transcribe), ничего не сохраняется. Phase 2/3 рассмотрит сохранение partial JSON в `OUTPUT_DIR/.partial/` для recovery.
- **No fallback chain**: при `TRANSCRIBE_BACKEND=openai` и API down, не падаем обратно на local. Phase 3 рассмотрит `BACKEND_FALLBACK_CHAIN=openai,local`.

См. [ADR-0003](adr/0003-openai-backend-base-url-for-groq-compat.md) для контекста где будет жить 429-handling.
