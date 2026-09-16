"""Test environment.

`bot.config` validates settings at import and `bot.db.base` builds the engine
from them, so the dummy values have to be in place before any bot module is
imported. The database is a throwaway SQLite file — the same dialect the free
stack runs on, so the upsert paths under test are the real ones.
"""

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="speakout-tests-")

os.environ.setdefault("BOT_TOKEN", "test")
os.environ.setdefault("DB_DSN", f"sqlite+aiosqlite:///{_TMP}/test.db")
os.environ.setdefault("LLM_PROVIDER", "groq")
os.environ.setdefault("STT_PROVIDER", "groq")
os.environ.setdefault("GROQ_API_KEY", "test")
os.environ.setdefault("GEMINI_API_KEY", "test")
os.environ.setdefault("TTS_PROVIDER", "edge")
