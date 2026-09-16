#!/bin/sh
# Startup for container hosting.
#
# Each stage announces itself and fails with a sentence a person can act on.
# On a platform log, "MIGRATIONS FAILED - check DB_DSN" is worth more than
# forty lines of SQLAlchemy traceback scrolled off the top.

set -e

echo "=============================================="
echo " SpeakOut starting"
echo "=============================================="

echo "--> 1/3  applying database migrations"
if ! alembic upgrade head; then
    echo ""
    echo "!! MIGRATIONS FAILED"
    echo "!! The database could not be reached or prepared. Check DB_DSN:"
    echo "!!   - it must start with postgresql+asyncpg://  (not postgresql://)"
    echo "!!   - use the Supabase SESSION pooler on port 5432, not 6543"
    echo "!!   - the password must not contain @ # / : ? characters"
    exit 1
fi

echo "--> 2/3  seeding conversation topics"
if ! python -m scripts.seed; then
    echo ""
    echo "!! SEEDING FAILED - the database is reachable but could not be written to"
    exit 1
fi

echo "--> 3/3  starting the bot"
exec python -m bot
