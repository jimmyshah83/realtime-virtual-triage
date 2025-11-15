import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # Azure AI Foundry
    azure_foundry_endpoint: str = os.getenv(
        "AZURE_FOUNDRY_ENDPOINT",
        "https://your-foundry-endpoint.openai.azure.com/"
    )
    azure_foundry_api_key: str = os.getenv("AZURE_FOUNDRY_API_KEY", "")
    azure_deployment_name_realtime: str = os.getenv(
        "AZURE_DEPLOYMENT_NAME_REALTIME", "gpt-4o-realtime"
    )
    azure_api_version: str = os.getenv("AZURE_API_VERSION", "2024-10-01-preview")

    # Session Configuration
    session_ttl_hours: int = 24
    session_cleanup_interval_minutes: int = 60

    # Server Configuration
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # STUN Servers for WebRTC
    stun_servers: list[str] = [
        "stun:stun.l.google.com:19302",
        "stun:stun1.l.google.com:19302",
    ]

    # Logging
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


settings = Settings()
