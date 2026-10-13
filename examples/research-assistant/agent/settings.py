"""Agent configuration, read from environment variables (and `.env`)."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    agent_name: str = "Research Assistant"

    # LLM (any OpenAI-compatible endpoint works via OPENAI_BASE_URL)
    llm_model: str = ""
    llm_temperature: float | None = None
    openai_api_key: SecretStr | None = None
    openai_base_url: str | None = None


@lru_cache
def get_settings() -> AgentSettings:
    return AgentSettings()
