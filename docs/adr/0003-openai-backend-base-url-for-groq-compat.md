# ADR-0003: Reuse OpenAI backend for Groq via OPENAI_BASE_URL

> **Superseded by [ADR-0023](0023-first-class-transcribe-providers.md) (2026-05-02).** Variant A introduced `OPENAI_BASE_URL` as the Groq routing knob; in Phase 3g it was replaced with first-class `TRANSCRIBE_BACKEND=groq` + `GROQ_*` env vars. Reason: provider-specific names (Groq key in OPENAI_API_KEY, etc.) are confusing; additionally `OPENAI_BASE_URL` was never plumbed to the OpenAI SDK constructor so it had no runtime effect.

Status: Superseded
Date: 2026-04-29

## Context

Groq предоставляет OpenAI-compatible HTTP endpoint `/v1/audio/transcriptions`. Мы хотим добавить Groq в качестве дополнительного backend для transcribe-стадии: это бесплатная (на момент написания) альтернатива OpenAI Whisper API с сопоставимым качеством.

В коде уже есть рабочая функция `transcribe_via_openai()` (`src/openai_transcribe.py:93-130`) и одноразовый dispatch между local-бэкендом и OpenAI в `src/process.py:197-208`. Поскольку Groq шарит API-контракт с OpenAI, заводить отдельный клиентский класс или второй бэкенд-параметр избыточно.

Альтернативные варианты, которые рассматривались: добавить новое значение `TRANSCRIBE_BACKEND=groq` с собственной функцией-двойником; форкнуть `transcribe_via_openai` с заменой URL; создать отдельный класс `GroqClient`. Все три плодят дублирование без выигрыша.

## Decision

Variant A: единственный новый env var `OPENAI_BASE_URL`. Пустое или неустановленное значение - используется default OpenAI; `https://api.groq.com/openai/v1` - используется Groq. Никакого нового значения для `TRANSCRIBE_BACKEND` и никакого parallel client class.

Phase 3 имплементирует это так: добавит параметр `base_url: str | None = None` в `transcribe_via_openai`, который будет проброшен через `cfg["openai_base_url"]` из `process.py`.

## Consequences

**Положительные:**
- Ноль дублированного клиентского кода - один путь, одна функция, один тест.
- Переключение провайдера сводится к редактированию `.env` без перезапуска watcher или изменения скриптов.

**Отрицательные / Trade-offs:**
- Provider-specific особенности (rate limits, file-size cap, response shape variations) приходится параметризовать через ту же функцию.
- Сообщения об ошибках упоминают "OpenAI", даже когда фактически отправляются запросы в Groq. Это вводит в заблуждение при дебаге логов.

**Что становится возможным дальше:**
- Rate-limit handling и retry на 429 будут жить внутри `transcribe_via_openai` и применяться к обоим провайдерам автоматически. Если же в будущем расхождение response shape окажется существенным, эта ADR будет superseded новой ("Variant B: separate Groq adapter").
