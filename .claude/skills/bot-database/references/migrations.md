# Alembic migrations

## Setup for async

```bash
alembic init -t async migrations
```

The `-t async` template is important — the default template uses a synchronous engine and will not work with `asyncpg`.

Point `migrations/env.py` at the models and the runtime config rather than hardcoding a URL in `alembic.ini`:

```python
from bot.config import settings
from bot.db.models import Base

config.set_main_option("sqlalchemy.url", settings.db_dsn)
target_metadata = Base.metadata
```

Import every model module in `env.py` (or in the package `__init__`). Autogenerate only sees tables registered on `Base.metadata`, so a model that is never imported is silently dropped from the migration — or worse, autogenerate emits a `DROP TABLE` for it.

## The workflow

```bash
alembic revision --autogenerate -m "add srs fields to user_cards"
# READ the generated file, edit it
alembic upgrade head
```

Autogenerate detects: new/dropped tables, new/dropped columns, nullability, index and unique-constraint changes, and (with `compare_type=True`) type changes.

It does **not** reliably detect:

- **Column renames** — it emits `drop_column` + `add_column`, which destroys the data. Replace with `op.alter_column(..., new_column_name=...)`.
- **Server default changes** — needs `compare_server_default=True` in `context.configure`, and even then is imperfect.
- **Constraint/check edits**, enum value additions, and anything inside `JSONB`.
- **Data**. Never. A migration that adds a `NOT NULL` column to a populated table will fail unless you add it nullable, backfill, then set `NOT NULL`.

This is why the migration file gets read every time. Treat autogenerate as a first draft written by a tool that cannot see intent.

## A data migration

Adding a column that must be populated from existing rows:

```python
def upgrade() -> None:
    op.add_column("users", sa.Column("timezone", sa.String(64), nullable=True))

    users = sa.table("users", sa.column("id"), sa.column("language_code"), sa.column("timezone"))
    op.execute(
        users.update()
        .where(users.c.language_code == "ru")
        .values(timezone="Europe/Moscow")
    )
    op.execute(users.update().where(users.c.timezone.is_(None)).values(timezone="UTC"))

    op.alter_column("users", "timezone", nullable=False)


def downgrade() -> None:
    op.drop_column("users", "timezone")
```

Use `sa.table()`/`sa.column()` lightweight constructs, not the ORM model. A migration must describe the schema *at that point in history*; importing the current model means old migrations break the day the model changes.

## Zero-downtime changes

If the bot keeps running during deploys, a change must be compatible with both the old and new code for one release. The expand/contract pattern:

1. **Expand** — add the new nullable column. Old code ignores it, new code writes it.
2. **Backfill** — populate in batches, outside the migration if the table is large.
3. **Migrate reads** — deploy code that reads the new column.
4. **Contract** — a later migration drops the old column.

Dropping a column in the same release that stops using it will break every request served by the old replica during the rollout.

On Postgres, watch the locks: `ALTER TABLE ... ADD COLUMN` with a non-volatile default is fast in modern versions, but adding an index is not — use `CREATE INDEX CONCURRENTLY`, which requires `op.execute` outside a transaction:

```python
def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("CREATE INDEX CONCURRENTLY ix_attempts_user_time ON attempts (user_id, created_at)")
```

A plain `CREATE INDEX` takes an exclusive lock and blocks writes for the duration — on a large `attempts` table, that is a visible outage.

## Running migrations on deploy

Run `alembic upgrade head` as a separate step before the new containers start serving:

```yaml
# docker-compose / CI deploy step
migrate:
  image: myapp:${TAG}
  command: alembic upgrade head
```

Not from inside the bot's startup: several replicas booting at once will race, and Alembic's version table does not protect against concurrent upgrades from a cold start.

Keep migrations in version control alongside the code that needs them, in the same commit. A model change without its migration is an incomplete change.

## Fixing a bad migration

- **Not yet deployed anywhere** → edit the file, `alembic downgrade -1`, re-run.
- **Already applied in production** → write a new forward migration. Never edit an applied migration; environments will silently diverge.
- **Branching heads** (two developers generated revisions from the same parent) → `alembic merge heads -m "merge"`, which creates a merge revision. Check the resulting order makes sense.
- **Database ahead of code** → `alembic stamp <rev>` marks a revision as applied without running it. Use only when you are certain the schema already matches, e.g. after restoring a dump.

## Checklist per migration

- Read the generated file end to end.
- Renames are `alter_column`, not drop + add.
- New `NOT NULL` columns: add nullable → backfill → set not null.
- `downgrade()` is written and would actually reverse the change.
- Large-table index creation is `CONCURRENTLY`.
- No ORM model imports inside the migration.
- Applied against a copy of production data before production.
