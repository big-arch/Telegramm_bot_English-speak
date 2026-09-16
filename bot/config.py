"""Typed configuration. Everything secret comes from the environment."""

from __future__ import annotations

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram
    bot_token: SecretStr

    # Database
    db_dsn: str

    # LLM
    anthropic_api_key: SecretStr
    tutor_model: str = "claude-opus-5"
    assessor_model: str = "claude-opus-5"

    # Speech
    openai_api_key: SecretStr
    tts_provider: str = "elevenlabs"
    elevenlabs_api_key: SecretStr | None = None

    # Optional infra
    redis_url: str | None = None

    # Ops
    admin_ids: list[int] = Field(default_factory=list)
    log_level: str = "INFO"

    # Economics
    free_daily_turns: int = 0
    max_voice_seconds: int = 120

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _split_admin_ids(cls, v: object) -> object:
        """Accept "123,456" from the environment as well as a real list."""
        if isinstance(v, str):
            return [int(x) for x in v.replace(" ", "").split(",") if x]
        return v

    @field_validator("redis_url", "elevenlabs_api_key", mode="before")
    @classmethod
    def _empty_to_none(cls, v: object) -> object:
        # An unset key in .env arrives as "" rather than absent.
        return None if v == "" else v

    @property
    def uses_elevenlabs(self) -> bool:
        return self.tts_provider == "elevenlabs" and self.elevenlabs_api_key is not None


settings = Settings()  # type: ignore[call-arg]
