# ADR-0017: watchdog library + sync threading queue worker

Status: Accepted
Date: 2026-04-29

## Context

Phase 3b daemon (`meetscribed-watcher`) должен слушать FSEvent на `WATCH_DIR` и обрабатывать видео по одному (resource-intensive ML pipeline, нельзя параллельно). Нужен FSEvent listener плюс concurrency model.

Альтернативы рассмотрены:
- `watchdog` library + threading: pure Python, кроссплатформенно, на macOS использует FSEvents API под капотом. Standard pattern.
- `watchdog` + asyncio: async event loop с очередью. Сложнее для N=1 worker.
- Polling: `os.scandir(WATCH_DIR)` каждые 5 сек. Без deps, но latency и CPU.
- `fswatch` CLI subprocess: external dep, надо `brew install fswatch`.

## Decision

Используем `watchdog>=4.0` для FSEvent listener-а. Threading model: один Observer thread (создан watchdog-ом), один worker thread, главный thread ждёт shutdown.

- `WatchHandler(FileSystemEventHandler)` enqueues paths в `queue.Queue`.
- Worker thread: `while not shutdown.is_set(): path = queue.get(timeout=1); _process_one(path)`.
- `_process_one` блокирует на `subprocess.run([python, -m, src.process, path])` (~5-15 мин per video).
- Single-instance гарантирован launchd-ом (`KeepAlive=true`), не через `mkdir` lock.

## Consequences

**Положительные:**
- Стандартная Python схема, минимум сюрпризов.
- watchdog handles macOS FSEvents API нативно.
- Один queue, один worker = простая дедупликация (state.db query на enqueue).
- Signal handling простой: `shutdown.Event` flag, threads проверяют.

**Отрицательные / Trade-offs:**
- subprocess.run в worker блокирует. SIGTERM mid-pipeline не cancellable - launchd SIGKILL после timeout, видео остаётся в state='processing'. Phase 3c исправит через launchctl-on-demand worker.
- watchdog adds dep (но кроссплатформенный, well-maintained).
- 1 thread overhead для observer (~ничего).

**Что становится возможным дальше:**
- Phase 3c заменит subprocess.run прямой вызов на `launchctl start worker`. Worker станет on-demand, watcher не блокирует.
- Phase 3e может конфигурировать `MAX_PARALLEL_VIDEOS` для multi-worker сценариев (если когда-то понадобится).
