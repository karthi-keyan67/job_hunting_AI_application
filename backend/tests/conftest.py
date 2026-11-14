import asyncio
import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

if os.getenv("TEST_DATABASE_URL"):
    TEST_DATABASE_URL = os.environ["TEST_DATABASE_URL"]
else:
    from app.core.config import Settings

    test_settings = Settings()
    TEST_DATABASE_URL = URL.create(
        "postgresql+asyncpg",
        username=test_settings.postgres_user,
        password=test_settings.postgres_password,
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        database=test_settings.verify_database_name,
    ).render_as_string(hide_password=False)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from app.api.dependencies import get_session
from app.main import app
from app.models import Base


@pytest_asyncio.fixture
async def test_engine():
    engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def session_factory(test_engine):
    return async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(scope="session", autouse=True)
def migrate_test_database():
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL.replace("%", "%%"))
    command.upgrade(config, "head")
    yield
    async def clear_rows():
        cleanup_engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)
        try:
            async with cleanup_engine.begin() as connection:
                await connection.execute(text("SELECT set_config('app.audit_cleanup', 'on', true)"))
                for table in reversed(Base.metadata.sorted_tables):
                    await connection.execute(delete(table))
        finally:
            await cleanup_engine.dispose()

    asyncio.run(clear_rows())


@pytest_asyncio.fixture(autouse=True)
async def clean_test_database(migrate_test_database, test_engine):
    async with test_engine.begin() as connection:
        await connection.execute(text("SELECT set_config('app.audit_cleanup', 'on', true)"))
        for table in reversed(Base.metadata.sorted_tables):
            await connection.execute(delete(table))
    yield


@pytest_asyncio.fixture
async def client(session_factory) -> AsyncIterator[AsyncClient]:
    async def override_session():
        async with session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def db_session(session_factory) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


