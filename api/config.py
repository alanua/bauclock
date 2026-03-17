import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    API_PORT: int = 8000
    DATABASE_URL: str = "sqlite+aiosqlite:///./bauclock.db"
    BOT_USERNAME: str = "SEKbaubot"
    ENCRYPTION_KEY: str
    
    # We load this locally if not provided in env for local tests
    class Config:
        env_file = ".env"
        extra = "ignore"
        
settings = Settings()
