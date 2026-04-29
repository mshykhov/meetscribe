# ADR-0015: typer as CLI framework

Status: Accepted
Date: 2026-04-29

## Context

Phase 3a вводит CLI `meetscribe` с командами `ls`, `show`, `migrate`, `process`. Phases 3b-3g планируют добавить ещё ~10 команд: `status`, `retry`, `skip`, `cancel`, `edit`, `redo`, `rename`, `health`, `config`. Нужен framework который масштабируется на 15+ subcommands без boilerplate-а на каждой команде.

Альтернативы рассмотрены:
- `argparse` (stdlib): ноль deps, но writing 15+ subcommand definitions через `argparse.add_subparsers` и manual handlers требует ~200 строк boilerplate. Type hints не используются автоматически.
- `click`: mature, decorator-based, ~80 KB. Гибкий для сложных command groups, но требует декораторов на каждую option/argument отдельно.
- `typer`: built on click, использует Python type hints как single source of truth для CLI args/options. Минимум boilerplate. ~15 KB сам + click underneath.

## Decision

Используем `typer` (>= 0.12) для всех CLI команд `meetscribe`. Type hints на parameters становятся CLI args/options автоматически. Структура: `src/cli.py` определяет `app = typer.Typer(...)` и регистрирует команды через `@app.command()`. Точка входа в `pyproject.toml`: `meetscribe = "src.cli:app"`.

## Consequences

**Положительные:**
- Минимум boilerplate на команду: `def show(id_or_path: str): ...` сразу становится `meetscribe show <id-or-path>`.
- IDE-friendly type hints используются и для CLI и для статического анализа.
- click underneath, поэтому есть полная экосистема плагинов и testing helpers (`typer.testing.CliRunner`).
- Help-сообщения генерируются из docstrings автоматически.

**Отрицательные / Trade-offs:**
- Один новый dep (typer + транзитивно click). Минимальный размер, но не zero deps.
- typer добавляет magic: для нестандартных edge cases (custom completion, complex types) приходится знать typer-specific patterns.
- Требует Python 3.7+ (нам не проблема - мы на 3.10+).

**Что становится возможным дальше:**
- Phase 3a добавляет 4 команды (ls, show, migrate, process). Phases 3b-3g будут добавлять команды через `@app.command()` без расширения framework.
- Если когда-нибудь понадобится shell completion - typer его генерирует одной командой `--install-completion`.
