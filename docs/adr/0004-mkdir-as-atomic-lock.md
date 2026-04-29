# ADR-0004: mkdir as atomic single-instance lock

Status: Accepted
Date: 2026-04-29

## Context

`watch-handler.sh` запускается hammerspoon-watcher-ом каждый раз, когда в каталоге появляется новый видеофайл. Если два события прилетят почти одновременно (или watcher продублирует одно событие), без синхронизации запустятся два pipeline-а на одном файле.

macOS не поставляется с `flock(1)` из коробки. Подключать `flock(2)` через C-код или зависимость на coreutils от Homebrew - overkill для shell-скрипта в personal-проекте. PID-файлы имеют классический TOCTOU gap: читаем PID из файла, проверяем `kill -0`, а в этот момент другой процесс уже стартует и проходит ту же проверку.

Реализация в `scripts/watch-handler.sh:36-50` использует `mkdir` как примитив: POSIX гарантирует, что mkdir атомарен и эксклюзивен - либо создаёт директорию, либо возвращает EEXIST.

## Decision

Используем `mkdir /tmp/com.myron.meetscribe.lock.d` как atomic lock primitive. Внутри директории пишем PID владельца (для diagnostics и detection of stale lock). При неудачном acquisition: проверяем PID через `kill -0`; если процесс мёртв - удаляем `rm -rf` старую директорию и retry-им один раз. Cleanup при выходе через `trap 'rm -rf "$LOCKDIR"' EXIT`.

## Consequences

**Положительные:**
- Один syscall, atomic, portable - работает на любой POSIX-системе без зависимостей.
- Нет TOCTOU gap-а: либо создали директорию, либо нет.
- Stale lock при чистом завершении не остаётся за счёт trap EXIT.

**Отрицательные / Trade-offs:**
- SIGKILL (или kernel panic) оставит stale lock до следующего запуска handler-а, который его и почистит. Между этими событиями новые файлы не обработаются.
- Lock работает только в пределах одной машины - inode-уровневая семантика mkdir не покрывает сетевые FS корректно.

**Что становится возможным дальше:**
- Ничего планового. Если когда-нибудь захотим cross-machine lock (например, watcher на удалённой машине) - перейдём на NFS-friendly механизм или внешнюю очередь, и эта ADR будет superseded.
