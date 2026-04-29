# ADR-0002: Senko monkey-patch to use venv Python

Status: Accepted
Date: 2026-04-29

## Context

WhisperX-MLX подключает senko в роли backend для diarization. Senko, в свою очередь, запускает собственный subprocess для CoreML inference и hardcode-ит путь к интерпретатору как `/usr/bin/python3`.

В нашем проекте используется `.venv` со всеми зависимостями (pyannote, torch и пр.), а системный Python в `/usr/bin/python3` этих пакетов не имеет. Поэтому subprocess senko падает с ImportError ещё до начала diarization.

Хелпер `_patch_senko_python_path` (`src/process.py:25-59`) подменяет атрибут upstream-класса так, чтобы senko использовал `sys.executable` (Python из venv). Этот же патч продублирован внутри inline-скрипта diarize-шага (`src/process.py:267-294`), потому что после fork-а subprocess заново импортирует `senko_backend` и патч родителя в дочерний процесс не наследуется.

## Decision

На import time мы monkey-patch-им метод `senko_backend.SenkoDiarizationPipeline._run_senko_subprocess`, чтобы он использовал `sys.executable` вместо hardcoded `/usr/bin/python3`. Этот же патч повторяется в inline-скрипте, который выполняется в subprocess для diarize-стадии.

## Consequences

**Положительные:**
- Решение работает без необходимости форкать senko или whisperx-mlx и поддерживать собственные форки.
- Минимальный объём изменений - один метод подменён, поведение остального кода не затронуто.

**Отрицательные / Trade-offs:**
- Патч продублирован в двух местах, и легко забыть синхронизировать обе копии при изменении.
- Жёсткая связка с upstream class layout: переименование метода или класса в senko ломает интеграцию.
- Silent fail: блок `try/except (ImportError, AttributeError)` глотает ошибку, и при изменении upstream API мы получим неработающий diarize без явного сообщения.

**Что становится возможным дальше:**
- Phase 2 уберёт дублирование, вытащив helper в `src/_senko_patch.py`. Файл будет импортироваться и из родителя, и из inline-скрипта (либо из вынесенного `_step_diarize.py`).
