from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./bauclock.db")

engine = create_async_engine(
    DATABASE_URL,
    echo=False,  # Set to True for debugging SQL queries
    future=True,
    pool_pre_ping=True
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

async def get_db():
    """FastAPI Dependency for getting async DB session."""
    async with SessionLocal() as session:
        yield session
