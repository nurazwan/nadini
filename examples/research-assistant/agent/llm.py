"""Chat model factory. Swap the provider here; the rest of the agent is unaffected."""

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from agent.settings import get_settings


def get_llm() -> BaseChatModel:
    settings = get_settings()
    if not settings.llm_model:
        raise RuntimeError("LLM_MODEL is not set - add it to .env (see .env.example)")

    kwargs = {}
    if settings.llm_temperature is not None:
        kwargs["temperature"] = settings.llm_temperature
    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        streaming=True,
        stream_usage=True,
        **kwargs,
    )
