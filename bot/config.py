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

DEFAULT_DB_DSN = "sqlite+aiosqlite:///data/speakout.db"


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
    db_dsn: str = DEFAULT_DB_DSN

    # --- Dialogue and assessment ---
    # groq is the default because one key covers both speech recognition and
    # dialogue. Gemini is a one-variable swap for better dialogue quality.
    llm_provider: str = "groq"  # groq (free) | gemini (free) | anthropic
    # Groq retires models on a few months' notice — llama-3.3-70b-versatile and
    # llama-3.1-8b-instant were both decommissioned in August 2026. Whatever is
    # written here will go stale too, which is why scripts/doctor.py checks the
    # configured names against the live list at startup and prints what is
    # actually available.
    groq_chat_model: str = "openai/gpt-oss-120b"
    # Drop the assessor to openai/gpt-oss-20b to raise the daily ceiling — the
    # free tier allows far more requests to the smaller model.
    groq_assessor_model: str = "openai/gpt-oss-120b"
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
    # Leave empty to poll, which is right for a laptop or an always-on VM.
    webhook_base_url: str | None = None
    webhook_secret: SecretStr | None = None
    port: int = 8000

    # Render injects this into every web service. Picking it up automatically
    # removes a whole deployment step — and with it the most common way to end
    # up with a silent bot: deploying, forgetting to paste the URL back in, and
    # sitting in polling mode where nothing ever wakes the service.
    render_external_url: str | None = None

    # --- Ops ---
    admin_ids: list[int] = Field(default_factory=list)
    log_level: str = "INFO"

    # --- Guardrails ---
    # Free tiers have daily ceilings. This keeps one enthusiastic user from
    # spending the whole day's quota before lunch.
    free_daily_turns: int = 40
    max_voice_seconds: int = 120

    @field_validator("db_dsn", mode="before")
    @classmethod
    def _blank_dsn_falls_back(cls, v: object) -> object:
        """A variable left blank in a hosting dashboard arrives as "".

        Without this, an empty DB_DSN reaches SQLAlchemy as an unparseable URL
        and the container dies on the first line with a stack trace that says
        nothing about the real problem.
        """
        if v is None or (isinstance(v, str) and not v.strip()):
            return DEFAULT_DB_DSN
        return str(v).strip()

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
        "render_external_url",
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
    def public_base_url(self) -> str | None:
        """Where Telegram should POST updates, if anywhere.

        An explicit setting always wins, so a platform-provided URL can be
        overridden (a custom domain, say) without editing code.
        """
        return self.webhook_base_url or self.render_external_url

    @property
    def use_webhook(self) -> bool:
        return bool(self.public_base_url)

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
