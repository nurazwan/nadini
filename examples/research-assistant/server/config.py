"""Server configuration, read from environment variables (and `.env`)."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8000
    # URL clients use to reach this service (advertised in the A2A agent card).
    public_url: str = "http://localhost:8000"
    agent_version: str = "0.1.0"
    agent_description: str = (
        "Answers questions by searching Wikipedia and doing exact arithmetic, citing its sources."
    )

    # MCP: Host headers allowed by DNS-rebinding protection. Empty = protection off
    # (fine behind a gateway); set e.g. ["localhost:*", "my-agent.example.com"].
    mcp_allowed_hosts: list[str] = []

    # Bearer token for A2A / MCP / dev API. Empty = auth disabled.
    auth_token: SecretStr | None = None

    # Dev chat UI at /dev-ui. Keep OFF in production.
    dev_ui_enabled: bool = False
    # Trace deep links shown in the dev UI ({trace_id} is substituted).
    trace_url_template: str = (
        "http://localhost:3000/explore?schemaVersion=1&panes="
        '{"t":{"datasource":"tempo","queries":[{"refId":"A","datasource":{"type":"tempo","uid":"tempo"},'
        '"queryType":"traceql","query":"{trace_id}"}],"range":{"from":"now-6h","to":"now"}}}'
    )

    # Telemetry. Standard OTEL_* env vars (OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_SERVICE_NAME,
    # OTEL_RESOURCE_ATTRIBUTES, OTEL_SDK_DISABLED, ...) are honoured by the SDK directly.
    otel_enabled: bool = True
    # Langfuse reads LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_BASE_URL itself.
    langfuse_enabled: bool = True


@lru_cache
def get_settings() -> ServerSettings:
    return ServerSettings()
