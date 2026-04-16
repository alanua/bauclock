import json
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings

from bot.utils.access import normalize_usernames

class Settings(BaseSettings):
    BOT_TOKEN: str
    REDIS_URL: str = "redis://redis:6379/0"
    DATABASE_URL: str = "sqlite+aiosqlite:///./bauclock.db"
    APP_URL: str = "https://sekbot.duckdns.org"
    BOT_USERNAME: str = "SEKbaubot"
    BOT_ROLE: str = "dedicated_client"
    PLATFORM_BOT_USERNAME: str = "gewerbebot"
    DEDICATED_CLIENT_BOT_USERNAME: str = "SEKbaubot"
    SHARED_CLIENT_BOT_USERNAME: str = "bauuhrbot"
    OWNER_PHONE: str = "+49176807279824"
    ADMIN_USERNAMES: list[str] = ["AnOleksii"]
    PLATFORM_SUPERADMIN_USERNAMES: list[str] = ["AnOleksii"]

    @field_validator("ADMIN_USERNAMES", "PLATFORM_SUPERADMIN_USERNAMES", mode="before")
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

    @staticmethod
    def _normalize_single_username(value: str | None) -> str:
        usernames = normalize_usernames([value] if value else [])
        return usernames[0] if usernames else ""

    @property
    def is_platform_bot(self) -> bool:
        bot_username = self._normalize_single_username(self.BOT_USERNAME)
        platform_username = self._normalize_single_username(self.PLATFORM_BOT_USERNAME)
        return self.BOT_ROLE == "platform" or (
            bool(bot_username) and bot_username == platform_username
        )
    
    class Config:
        env_file = ".env"
        extra = "ignore"
        
settings = Settings()
