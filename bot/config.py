import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    BOT_TOKEN: str
    REDIS_URL: str = "redis://redis:6379/0"
    DATABASE_URL: str = "sqlite+aiosqlite:///./bauclock.db"
    APP_URL: str = "http://localhost:8000"
    BOT_USERNAME: str = "SEKbaubot"
    OWNER_PHONE: str = "+49176807279824"
    
    class Config:
        env_file = ".env"
        extra = "ignore"
        
settings = Settings()
