# ADR-0012: Phased migration over big-bang refactor

Status: Accepted
Date: 2026-04-29

## Context

Phase 2 фиксирует target architecture (см. [ADR-0008](./0008-sqlite-as-state-authority.md), [ADR-0009](./0009-two-daemon-architecture.md), [ADR-0011](./0011-swiftbar-url-scheme-refresh.md)). Открытый вопрос: как мигрировать с current state, не сломав ежедневный workflow.

Альтернативы рассмотрены: big-bang (один большой PR заменяет всё, оценка ~3-5K строк), phased (6 small PRs, каждый меняет один слой), hybrid (один core PR + mini PRs для add-ons). meetscribe это personal automation tool, который пользователь использует ежедневно. Pipeline на паузе на месяц (пока big-bang ревьюится) - blocker. Phased подход требует, чтобы каждая фаза оставляла систему рабочей, и это его главное преимущество.

## Decision

Мы используем phased migration через 6 phases (3a через 3f), каждая в своём brainstorm → spec → plan → PR cycle. Опциональный 3g для Groq integration.

Phase 3a: state.db parallel-write (writes only, reads still through `.processed` / `.failed`). Phase 3b: meetscribed-watcher daemon (replaces shell handler, state.db становится authoritative). Phase 3c: meetscribed-worker on-demand (wraps `process.py`, добавляет partial_data crash recovery). Phase 3d: SwiftBar reads state.db + URL-scheme push (per [ADR-0011](./0011-swiftbar-url-scheme-refresh.md)). Phase 3e: notifications + sidecar configs + TUI + rate-limit handling. Phase 3f: optional web dashboard. Phase 3g (если нужно): Groq integration (теперь light, потому что rate-limit handling уже в 3e). Каждая phase успешна по criteria из Phase 2 spec.

## Consequences

**Положительные:**
- Каждая phase ~200-500 строк, mergeable за день.
- Pipeline работает в каждый момент времени между phases.
- Rollback возможен per-phase (reverting один PR).
- Reviewer cognitive load умеренный, ревью фокусировано.

**Отрицательные / Trade-offs:**
- Больше overhead на координацию (каждая phase = brainstorm / spec / plan / PR cycle).
- Общее время больше, чем big-bang (но zero downtime компенсирует).
- Promotional pressure на phases чтобы не застрять между, оставляя half-migrated state.

**Что становится возможным дальше:**
- Каждая Phase 3X пишет свой ADR(s) при необходимости (например, при выборе CLI framework, daemon concurrency model).
- `docs/roadmap.md` обновляется в каждой phase для отслеживания прогресса.
