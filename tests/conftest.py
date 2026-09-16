"""Test environment.

`bot.config` validates settings at import, so the dummy values have to be in
place before any bot module is imported. Nothing here touches the network or a
database — these tests cover pure logic only.
"""

import os

os.environ.setdefault("BOT_TOKEN", "test")
os.environ.setdefault("DB_DSN", "postgresql+asyncpg://u:p@localhost:5432/test")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("ELEVENLABS_API_KEY", "test")
