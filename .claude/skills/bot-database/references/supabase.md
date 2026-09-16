# Supabase as the bot's database

Supabase is managed PostgreSQL plus a set of services around it. For a Telegram bot the useful parts are the database itself, Storage (audio files), and pgvector. Auth, RLS and PostgREST are mostly designed for browser clients and matter less here — a bot is a trusted server.

**Everything in the main skill and in `sqlalchemy-async.md` applies unchanged**: it is real Postgres, so SQLAlchemy 2.0 async + asyncpg + Alembic is the stack. The differences are in connection handling and in a few managed-platform behaviours that will surprise you at the worst moment.

## Connecting: pick the right port

Supabase offers three endpoints, and choosing wrong produces failures that look like bugs in your code.

| Endpoint | Port | Prepared statements | Use for |
|---|---|---|---|
| Direct (`db.<ref>.supabase.co`) | 5432 | yes | Migrations; IPv6-only unless you have the IPv4 add-on |
| Supavisor **session** mode | 5432 | yes | **A long-running bot — this is your default** |
| Supavisor **transaction** mode | 6543 | **no** | Serverless/short-lived functions |

The pooler host looks like `aws-0-<region>.pooler.supabase.com` and the username carries the project ref: `postgres.<project-ref>`.

```python
# Session mode — the right default for a persistent bot process
DB_DSN = "postgresql+asyncpg://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres"

engine = create_async_engine(
    DB_DSN,
    pool_size=5,
    max_overflow=5,
    pool_pre_ping=True,
)
```

Keep the pool small. Supabase's free and small paid tiers cap total connections (tens, not hundreds), and the pooler counts your pool against that budget. A bot with `pool_size=20` across three replicas will exhaust the project's connection limit and start refusing connections — which surfaces as random `TooManyConnectionsError` under load, not as anything pointing at the pool size.

### If you must use transaction mode (port 6543)

Transaction mode hands you a different backend connection per transaction, so **prepared statements break**. asyncpg caches prepared statements by default, which produces `prepared statement "__asyncpg_stmt_1__" does not exist` or `DuplicatePreparedStatementError` — intermittently, which makes it maddening to debug.

```python
from uuid import uuid4
from sqlalchemy.pool import NullPool

engine = create_async_engine(
    "postgresql+asyncpg://postgres.<ref>:<pw>@aws-0-<region>.pooler.supabase.com:6543/postgres",
    poolclass=NullPool,
    connect_args={
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
    },
)
```

For a bot that runs as a normal process, avoid this entirely — use session mode.

## Migrations

Run Alembic against the **direct connection or session-mode pooler**, never transaction mode. DDL in transaction mode behaves unpredictably because statements may land on different backends.

You can use Supabase's own migration tooling (`supabase migration new` / `supabase db push`), but do not mix the two systems: pick Alembic *or* the Supabase CLI as the single source of schema truth. Two tools writing DDL to one database produces a schema neither of them can reason about. Since the bot is Python with SQLAlchemy models, Alembic is the natural choice — point it at the direct URL and ignore the CLI's migration folder.

The dashboard's SQL editor is for inspection, not for schema changes. Anything applied there is invisible to your migration history and will be missing from every fresh environment.

## Row Level Security

Supabase enables RLS-oriented workflows because its typical client is a browser holding an anon key. A bot connecting as the `postgres` role over a direct Postgres connection **bypasses RLS entirely** — which is correct here: the bot *is* the trusted server, and it authorises by Telegram user id in application code.

Consequences worth being explicit about:

- Do not design the schema around RLS policies you will never exercise.
- The **`service_role` key is a full-access credential**. It belongs in server environment variables only — never in anything a user could see. It is not needed at all if you connect over plain Postgres.
- If you later add a web dashboard that talks to PostgREST from a browser, that is when RLS starts mattering, and it must be enabled per table before that dashboard ships. A table with RLS off and a public anon key is world-readable.

## Storage for audio

Supabase Storage is a reasonable place for generated TTS and user recordings — S3-compatible, with signed URLs.

But for a Telegram bot, **the cheapest storage is Telegram itself**: send the file once, keep the returned `file_id`, and re-send by `file_id` for free. Use Storage only for what you need outside Telegram — a web player, an analytics export, re-processing user recordings later.

If you do store user voice recordings, that is personal data. Keep a private bucket, set a retention period, and be able to delete a user's audio on request.

## Platform behaviours that bite

**Free-tier projects pause after ~1 week of inactivity.** For a hobby bot that runs sporadically this means the database is simply gone one morning and the bot throws connection errors until someone clicks "restore" in the dashboard. If the bot must be reliable, this alone is the reason to be on a paid tier.

**Backups are limited on lower tiers** — daily at best, with short retention, and point-in-time recovery only on higher plans. Take your own `pg_dump` on a schedule for anything you would be upset to lose. A learner's two-year review history is exactly that.

**Connection limits are low** and shared across everything touching the project (bot replicas, the dashboard, any local psql session, Studio). Size pools accordingly.

**Latency depends on region.** Pick the region nearest the bot's host, not the nearest to you. A bot in Frankfurt talking to a database in Singapore adds ~200 ms to every query, and a handler making five queries becomes visibly slow.

## pgvector, if semantic search comes up

`pgvector` is available — useful for "find a similar example sentence", deduplicating generated content, or retrieving relevant past errors.

```sql
create extension if not exists vector;

alter table sentences add column embedding vector(1536);

create index on sentences using hnsw (embedding vector_cosine_ops);
```

Build the index **after** bulk-loading, not before — building incrementally on inserts is far slower. And embed the text you will actually query against: embedding a whole lesson and querying with a single word retrieves noise.

## Checklist

- Session-mode pooler (5432), not transaction mode, for the bot process.
- `pool_size` small (≤10 total across replicas); `pool_pre_ping=True`.
- Alembic against the direct/session URL; Alembic *or* the Supabase CLI, not both.
- No schema changes from the dashboard SQL editor.
- `service_role` key and DB password in environment variables, never in the repo.
- Region matches the bot's host.
- Own `pg_dump` backup if the data matters.
- Paid tier, or accept that the project pauses when idle.
