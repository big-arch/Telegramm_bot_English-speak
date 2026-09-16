"""Typed configuration. Everything secret comes from the environment.

Defaults are the **free stack**: Groq for both dialogue and speech recognition,
Microsoft Edge neural voices for speech, SQLite for storage.

That combination costs nothing and needs exactly one API key beyond the bot
token, because Groq covers both speech recognition and dialogue. Gemini and
Claude are one-variable swaps for better dialogue quality.
"""

from __future__ import annotations

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Telegram ---
    bot_token: SecretStr

    # --- Storage ---
    # SQLite needs nothing installed and no account. Point this at Postgres or
    # Supabase when you outgrow one process.
    db_dsn: str = "sqlite+aiosqlite:///data/speakout.db"

    # --- Dialogue and assessment ---
    # groq is the default because one key covers both speech recognition and
    # dialogue. Gemini is a one-variable swap for better dialogue quality.
    llm_provider: str = "groq"  # groq (free) | gemini (free) | anthropic
    groq_chat_model: str = "llama-3.3-70b-versatile"
    # Swap the assessor to llama-3.1-8b-instant to raise the daily ceiling a
    # long way — the free tier allows far more requests to the smaller model.
    groq_assessor_model: str = "llama-3.3-70b-versatile"
    gemini_api_key: SecretStr | None = None
    gemini_chat_model: str = "gemini-2.5-flash"
    gemini_assessor_model: str = "gemini-2.5-flash"
    anthropic_api_key: SecretStr | None = None
    tutor_model: str = "claude-opus-5"
    assessor_model: str = "claude-opus-5"

    # --- Speech recognition ---
    stt_provider: str = "groq"  # groq (free) | openai
    groq_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None

    # --- Speech synthesis ---
    tts_provider: str = "edge"  # edge (free) | openai | elevenlabs
    elevenlabs_api_key: SecretStr | None = None

    # --- Optional infra ---
    redis_url: str | None = None

    # --- Hosting ---
    # Set WEBHOOK_BASE_URL to run in webhook mode (required on hosts that put
    # the service to sleep when idle — Telegram's own POST is what wakes it).
    # Leave empty to poll, which is right for a laptop or a always-on VM.
    webhook_base_url: str | None = None
    webhook_secret: SecretStr | None = None
    port: int = 8000

    # --- Ops ---
    admin_ids: list[int] = Field(default_factory=list)
    log_level: str = "INFO"

    # --- Guardrails ---
    # Free tiers have daily ceilings. This keeps one enthusiastic user from
    # spending the whole day's quota before lunch.
    free_daily_turns: int = 40
    max_voice_seconds: int = 120

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _split_admin_ids(cls, v: object) -> object:
        """Accept "123,456" from the environment as well as a real list."""
        if isinstance(v, str):
            return [int(x) for x in v.replace(" ", "").split(",") if x]
        return v

    @field_validator(
        "redis_url",
        "webhook_base_url",
        "webhook_secret",
        "elevenlabs_api_key",
        "openai_api_key",
        "anthropic_api_key",
        "gemini_api_key",
        "groq_api_key",
        mode="before",
    )
    @classmethod
    def _empty_to_none(cls, v: object) -> object:
        # An unset key in .env arrives as "" rather than absent.
        return None if v == "" else v

    @property
    def is_sqlite(self) -> bool:
        return self.db_dsn.startswith("sqlite")

    @property
    def use_webhook(self) -> bool:
        return bool(self.webhook_base_url)

    @property
    def webhook_path(self) -> str:
        return "/tg/webhook"

    def missing_keys(self) -> list[str]:
        """Which keys the chosen providers need but do not have.

        Checked once at startup so a misconfiguration fails immediately with a
        readable message, rather than inside a handler an hour later.
        """
        missing = []
        if self.llm_provider == "groq" and self.groq_api_key is None:
            missing.append("GROQ_API_KEY (LLM_PROVIDER=groq)")
        if self.llm_provider == "gemini" and self.gemini_api_key is None:
            missing.append("GEMINI_API_KEY (LLM_PROVIDER=gemini)")
        if self.llm_provider == "anthropic" and self.anthropic_api_key is None:
            missing.append("ANTHROPIC_API_KEY (LLM_PROVIDER=anthropic)")
        if self.stt_provider == "groq" and self.groq_api_key is None:
            missing.append("GROQ_API_KEY (STT_PROVIDER=groq)")
        if self.stt_provider == "openai" and self.openai_api_key is None:
            missing.append("OPENAI_API_KEY (STT_PROVIDER=openai)")
        if self.tts_provider == "elevenlabs" and self.elevenlabs_api_key is None:
            missing.append("ELEVENLABS_API_KEY (TTS_PROVIDER=elevenlabs)")
        if self.tts_provider == "openai" and self.openai_api_key is None:
            missing.append("OPENAI_API_KEY (TTS_PROVIDER=openai)")
        return missing


settings = Settings()  # type: ignore[call-arg]
