import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from bot.utils.owner_worker import ensure_company_owner_worker
from db.models import Base, Company, Worker


def test_ensure_company_owner_worker_is_idempotent():
    async def run_test():
        os.environ["ENCRYPTION_KEY"] = "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff"
        os.environ["HASH_PEPPER"] = "test_pepper"

        with TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "owner_worker.db"
            engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
            session_maker = async_sessionmaker(engine, expire_on_commit=False)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with session_maker() as session:
                company = Company(
                    name="SEK",
                    owner_telegram_id_enc="owner_enc",
                    owner_telegram_id_hash="owner_hash",
                )
                session.add(company)
                await session.commit()

                telegram_user = SimpleNamespace(id=123456, full_name="Owner User")

                first_worker = await ensure_company_owner_worker(telegram_user, session, company)
                second_worker = await ensure_company_owner_worker(telegram_user, session, company)

                worker_count = (
                    await session.execute(
                        select(func.count(Worker.id)).where(Worker.company_id == company.id)
                    )
                ).scalar_one()

                assert first_worker.id == second_worker.id
                assert worker_count == 1

            await engine.dispose()

    asyncio.run(run_test())
