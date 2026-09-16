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

echo "--> 1/4  checking models and the database"
if ! python -m scripts.doctor; then
    echo ""
    echo "!! Fix the settings named above in the hosting dashboard and redeploy."
    exit 1
fi

echo "--> 2/4  applying database migrations"
if ! alembic upgrade head; then
    echo ""
    echo "!! MIGRATIONS FAILED - the database answered but could not be prepared."
    exit 1
fi

echo "--> 3/4  seeding conversation topics"
if ! python -m scripts.seed; then
    echo ""
    echo "!! SEEDING FAILED - the database is reachable but could not be written to"
    exit 1
fi

echo "--> 4/4  starting the bot"
exec python -m bot
