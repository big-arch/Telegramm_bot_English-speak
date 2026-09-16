FROM python:3.12-slim

# ffmpeg is required for voice: every synthesised reply is converted to
# OGG/OPUS, the only format Telegram renders as a playable voice bubble.
# It is not in python:slim, and its absence shows up as silent replies.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# The SQLite file lives here; mount a volume so it survives a redeploy. On a
# host with ephemeral disk, point DB_DSN at Postgres/Supabase instead.
RUN mkdir -p /app/data && useradd -m -u 1000 bot && chown -R bot:bot /app
USER bot

# Only used in webhook mode. Hosts usually override this via the PORT env var.
EXPOSE 8000

CMD ["sh", "./docker-entrypoint.sh"]
