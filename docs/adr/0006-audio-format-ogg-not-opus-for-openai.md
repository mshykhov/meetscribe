# ADR-0006: Audio extracted as Opus-in-Ogg with .ogg extension for OpenAI API

Status: Accepted
Date: 2026-04-29

## Context

OpenAI Whisper API принимает фиксированный whitelist расширений: `mp3`, `mp4`, `mpeg`, `mpga`, `m4a`, `wav`, `webm`, `ogg`, `flac`. Codec libopus как таковой поддерживается, но файл с расширением `.opus` API отклоняет на стадии валидации, не глядя на содержимое.

Нам нужен компактный codec, чтобы укладываться в 25 MB лимит на файл (OpenAI API per-file limit). Mono Opus при 32 kbps даёт примерно 240 KB/min, что позволяет уместить около 108 минут аудио в один файл - этого хватает для большинства встреч.

Реализация в `src/openai_transcribe.py:15-29` (`extract_audio_to_opus`) и `src/openai_transcribe.py:105` (использование `.ogg` при сохранении файла) показывает выбранный формат.

## Decision

Энкодим audio как Opus-in-Ogg через ffmpeg `-c:a libopus -b:a 32k -ac 1` и сохраняем с расширением `.ogg`. Codec тот же, расширение - из whitelist OpenAI.

## Consequences

**Положительные:**
- Около 108 минут аудио помещается в 25 MB при 32 kbps mono Opus - покрывает типичную встречу.
- Изменение - один флаг ffmpeg, не пришлось выбирать другой codec и сравнивать качество/размер.

**Отрицательные / Trade-offs:**
- Путает читателей кода: имя функции `extract_audio_to_opus` и расширение `.ogg` визуально конфликтуют, новичок ожидает `.opus`.
- Не решает 25 MB cap для видео > 2 часов - это отдельно обрабатывает `validate_audio_size`, который ошибается с понятным сообщением.

**Что становится возможным дальше:**
- Если Groq и/или OpenAI расширят whitelist accepted extensions до `.opus` - можно будет переименовать файлы и устранить визуальный конфликт. До тех пор `.ogg` стабильнее.
