# ADR-0007: HF_TOKEN is mandatory because diarization is always part of the pipeline

Status: Accepted
Date: 2026-04-29

## Context

Функция `load_config()` обращается к `os.environ["HF_TOKEN"]` (`src/process.py:114`) - индексирование вызывает `KeyError`, если переменная окружения не установлена. Pipeline стартует с этой проверки и падает fail-fast, если токена нет.

HF_TOKEN нужен для скачивания моделей pyannote с HuggingFace, которые senko делегирует под капотом для diarization. Diarization запускается всегда как стадия 3 pipeline, независимо от того, какой backend выбран для transcribe (local или openai/groq).

Сейчас в pipeline нет режима "только transcribe, без diarization". Финальный transcript всегда включает разметку говорящих, поэтому стадия 3 неотделима от остального flow.

## Decision

HF_TOKEN обязателен для текущего pipeline. Pipeline не поддерживает режим "transcribe-only, no diarization" - все вызовы проходят полный 4-стадийный flow.

## Consequences

**Положительные:**
- Простая validation - одно обращение к словарю, fail-fast на load_config до загрузки моделей.
- Нет hidden modes: один путь исполнения, который покрыт тестами.

**Отрицательные / Trade-offs:**
- Пользователи, которым нужна только OpenAI/Groq transcription без определения говорящих, всё равно обязаны зарегистрироваться на HuggingFace, принять license pyannote и сгенерировать токен.
- Trial friction для openai-only пути: новичок не может за 2 минуты прогнать первый файл, потому что блокируется на регистрации в HF.

**Что становится возможным дальше:**
- Phase 3 введёт env var `DIARIZATION=on|off`. При `off` стадия 3 пропускается, и HF_TOKEN становится опциональным. После релиза этой фичи текущая ADR станет `Status: Superseded by ADR-NNNN`.
