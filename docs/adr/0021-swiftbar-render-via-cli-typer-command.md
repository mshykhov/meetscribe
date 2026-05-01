# ADR-0021: SwiftBar plugin rendering via `meetscribe swiftbar` CLI command

Status: Accepted
Date: 2026-04-30

## Context

[ADR-0011](./0011-swiftbar-url-scheme-refresh.md) зафиксировал что SwiftBar plugin будет читать state.db напрямую (вместо парсинга логов). Phase 3d имплементирует это. Открытый вопрос: как организовать code:
- Отдельный Python script `meetscribe-swiftbar.py` запускаемый из bash.
- Bash plugin с inline `sqlite3` CLI queries.
- typer subcommand `meetscribe swiftbar` который рендерит output, bash plugin просто `exec`-ит его.

## Decision

Hybrid подход: рендер логика в `src/swiftbar.py` (~150 строк Python), доступна через typer subcommand `meetscribe swiftbar`. Bash plugin `scripts/meetscribe.5s.sh` (5 строк) просто `exec`-ит CLI команду.

## Consequences

**Положительные:**
- DRY: переиспользуем существующую typer infrastructure (Phase 3a). CLI binary один.
- Тестируемо: `tests/test_swiftbar_render.py` юнит-тестирует `render()`; `tests/test_cli_swiftbar.py` integration через CliRunner.
- Bash wrapper тривиален - не надо писать SQL escaping в shell.

**Отрицательные / Trade-offs:**
- Python startup overhead ~200ms на каждый refresh. На 5-секундный poll = 2.4 sec/min CPU idle. На push refresh - тот же overhead за event. Acceptable для personal tool.
- Hardcoded путь к venv `.venv/bin/meetscribe` в `scripts/meetscribe.5s.sh` - portable только для нашего setup. Mitigation: документировано в spec.

**Что становится возможным дальше:**
- Phase 3e может расширить `render()` для notification action button output без переписывания plugin.
- Phase 3f web dashboard может делиться с `render()` общими query helpers.
