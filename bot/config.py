import os
import json
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings

from bot.utils.access import normalize_usernames

class Settings(BaseSettings):
    BOT_TOKEN: str
    REDIS_URL: str = "redis://redis:6379/0"
    DATABASE_URL: str = "sqlite+aiosqlite:///./bauclock.db"
    APP_URL: str = "http://localhost:8000"
    BOT_USERNAME: str = "SEKbaubot"
    OWNER_PHONE: str = "+49176807279824"
    ADMIN_USERNAMES: list = ["AnOleksii"]

    @field_validator("ADMIN_USERNAMES", mode="before")
    @classmethod
    def parse_admin_usernames(cls, value: Any) -> list[str]:
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

        return normalize_usernames(value)
    
    class Config:
        env_file = ".env"
        extra = "ignore"
        
settings = Settings()
