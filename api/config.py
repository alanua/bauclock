import json
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    API_PORT: int = 8000
    DATABASE_URL: str = "sqlite+aiosqlite:///./bauclock.db"
    BOT_TOKEN: str = ""
    BOT_USERNAME: str = "SEKbaubot"
    ENCRYPTION_KEY: str
    PLATFORM_BOT_TOKEN: str = ""
    PLATFORM_BOT_USERNAME: str = "gewerbebot"
    SHARED_CLIENT_BOT_TOKEN: str = ""
    SHARED_CLIENT_BOT_USERNAME: str = "bauuhrbot"
    OWNER_PHONE: str = "+49176807279824"
    REDIS_URL: str = "redis://redis:6379/0"
    APP_URL: str = "https://sekbot.duckdns.org"
    ADMIN_USERNAMES: list[str] = []
    PLATFORM_SUPERADMIN_USERNAMES: list[str] = ["AnOleksii"]
    ENABLE_RETENTION: bool = False
    RETENTION_DRY_RUN: bool = True
    DATA_RETENTION_YEARS_TIME_EVENTS: int = 3
    DATA_RETENTION_YEARS_AUDIT_LOGS: int = 5

    @field_validator("ADMIN_USERNAMES", "PLATFORM_SUPERADMIN_USERNAMES", mode="before")
    @classmethod
    def parse_username_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            raw_value = value.strip()
            if not raw_value:
                return []
            if raw_value.startswith("["):
                try:
                    value = json.loads(raw_value)
                except json.JSONDecodeError:
                    value = raw_value.split(",")
            else:
                value = raw_value.split(",")
        if isinstance(value, tuple):
            value = list(value)
        return [str(item).strip().lstrip("@").casefold() for item in value if str(item).strip()]

settings = Settings()
