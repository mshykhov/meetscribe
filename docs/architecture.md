# Архитектура

## Цель и контекст

`meetscribe` - это персональный automation-инструмент: видео-запись OBS превращается в транскрипт и AI-саммари с action items без ручных шагов. Целевая платформа - только macOS Apple Silicon (требования инференса MLX и CoreML). Запускается фоном через launchd: пользователь дропает видео в `WATCH_DIR`, через несколько минут получает готовый результат в `OUTPUT_DIR`.

## Компоненты

Диаграмма ниже показывает физическое разделение системы: launchd подхватывает FSEvent на каталог, спавнит shell-handler, тот - Python pipeline, а pipeline уже ходит к локальным моделям или внешним API. Параллельно SwiftBar читает логи раз в секунду и отрисовывает текущий статус в menu bar.

```mermaid
flowchart TD
    User[("User drops video<br/>into WATCH_DIR")]
    Launchd[launchd<br/>com.myron.meetscribe.plist]
    Handler[watch-handler.sh<br/>find + lock + dispatch]
    Process[process.py<br/>4-stage pipeline]
    OpenAI[openai_transcribe.py<br/>OpenAI/Groq API]
    WhisperX[whisperx-mlx<br/>local transcribe + align]
    Senko[senko subprocess<br/>CoreML diarization]
    Claude[claude CLI<br/>summary]
    SwiftBar[swiftbar-plugin.1s.sh<br/>menu bar UI]
    Notifier[terminal-notifier]
    PipelineLog[(.logs/pipeline.log)]
    ProcessLog[(.logs/process-EPOCH.log)]
    Processed[(.processed)]
    Failed[(.failed)]
    Output[("OUTPUT_DIR<br/>{date}-{topic}/<br/>video + transcript + summary")]

    User -.FSEvent.-> Launchd
    Launchd -->|spawns| Handler
    Handler -->|spawns| Process
    Process -->|backend=local| WhisperX
    Process -->|backend=openai| OpenAI
    Process --> Senko
    Process --> Claude
    Process --> Output
    Process -.writes.-> ProcessLog
    Handler -.writes.-> PipelineLog
    PipelineLog -.read once/sec.-> SwiftBar
    ProcessLog -.read once/sec.-> SwiftBar
    Handler -.notify.-> Notifier
    Handler --> Processed
    Handler --> Failed

    classDef external fill:#2196F3,color:#fff
    classDef infra fill:#888888,color:#fff
    classDef success fill:#4CAF50,color:#fff
    class Launchd,Handler,Process,SwiftBar infra
    class OpenAI,WhisperX,Senko,Claude,Notifier external
    class Output success
```

## Точки расширения

**Backend dispatch**: env-переменная `TRANSCRIBE_BACKEND=local|openai` переключает реализацию первых двух шагов pipeline. Local-вариант гоняет два subprocess с MLX-моделями, openai-вариант заменяет их на один HTTP-запрос. См. [ADR-0003](adr/0003-openai-backend-base-url-for-groq-compat.md) - тот же openai-клиент через `OPENAI_BASE_URL` направляется на Groq без изменения кода.

**Diarization retry**: senko запускается до 3 раз подряд, и если все попытки провалились - pipeline продолжается без speaker labels (транскрипт сохраняется без `[Speaker N]` тегов). См. [ADR-0007](adr/0007-hf-token-required-for-local-diarization.md) о том, почему `HF_TOKEN` сейчас обязателен и план Phase 3 сделать его опциональным с автоматическим fallback.

## Что читать дальше

| Я хочу понять... | Открой |
|---|---|
| Как работает 4-stage pipeline | [pipeline.md](pipeline.md) |
| Как handler детектит и обрабатывает файлы | [watch-handler.md](watch-handler.md) |
| Что происходит при ошибках, как retry устроен | [error-handling.md](error-handling.md) |
| Почему такие технические решения | [adr/README.md](adr/README.md) |
| Куда движется архитектура (Phase 2+) | [roadmap.md](roadmap.md) |
