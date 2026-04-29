# ADR-0016: Schema migrations as SQL files in src/state/migrations/

Status: Accepted
Date: 2026-04-29

## Context

state.db (см. [ADR-0008](./0008-sqlite-as-state-authority.md)) будет эволюционировать через phases 3b-3f: добавление колонок, новых таблиц, индексов. Нужен механизм migrations который простой, transparent, и не требует тяжёлых ORM зависимостей.

Альтернативы рассмотрены:
- Inline schema в Python string в `state.py`: один файл, но при N версиях schema = N+1 if-веток. Уродливо, тяжело review-ить SQL.
- alembic (SQLAlchemy migrations): full ORM-aware tool, но мы не используем SQLAlchemy. Overkill.
- Yoyo, dbmate, etc.: external tools, добавляют dep и инфраструктуру.

## Decision

Migrations - это `.sql` файлы в `src/state/migrations/` с именами `NNN_description.sql` (трёхзначный номер с префиксом). Phase 3a содержит `001_initial.sql` с полной начальной схемой.

Runner (`src/state/runner.py`):
- `current_version(conn)`: SELECT MAX(version) FROM schema_version (или 0 если таблицы нет).
- `pending_migrations(conn)`: возвращает .sql файлы с номером > current_version, отсортированные.
- `apply_migrations(conn)`: применяет каждый файл через `executescript()`, каждый в своей транзакции.

Каждый migration .sql файл сам отвечает за обновление `schema_version` (через INSERT). Runner не меняет version самостоятельно.

## Consequences

**Положительные:**
- SQL файлы прямо reviewable - схема видна без чтения Python кода.
- Каждый migration self-contained, можно тестировать индивидуально.
- ~30 строк runner кода, ноль внешних deps.
- Легко добавлять новый migration в Phase 3b/3c: создать `002_*.sql`, runner подхватывает автоматически.

**Отрицательные / Trade-offs:**
- Нет автоматической data migration (типичный alembic feature). Если нужно перевести данные из старой schema в новую - SQL должен быть явный.
- Нет downgrade migrations (one-way). Acceptable для personal tool - если ошибся, восстанавливаем из бэкапа.
- Race condition если два процесса одновременно стартуют migrations на пустой db (mitigation: WAL mode + первый migration применяется в одной транзакции - второй процесс увидит уже applied, no-op).

**Что становится возможным дальше:**
- Phase 3b/3c добавляют новые migration файлы по мере введения новых таблиц/колонок.
- Если когда-нибудь schema станет настолько сложной что захочется alembic - можно мигрировать на него, но текущий simple подход should hold.
