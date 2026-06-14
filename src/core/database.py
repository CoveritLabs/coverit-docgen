from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from src.core.config import get_settings

settings = get_settings()

class DatabaseSessionManager:
    """Manages async database sessions with proper lifecycle."""

    def __init__(self):
        self._engine = None
        self._session_maker = None

    async def init(self):
        self._engine = create_async_engine(
            settings.database_url,
            pool_size=20,
            max_overflow=10,
            pool_pre_ping=True,
            echo=False,
        )
        self._session_maker = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def close(self):
        if self._engine:
            await self._engine.dispose()

    @asynccontextmanager
    async def session(self):
        if self._session_maker is None:
            raise RuntimeError("DatabaseSessionManager is not initialized")

        async with self._session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise


session_manager = DatabaseSessionManager()


async def get_db_session():
    """FastAPI dependency for database sessions."""
    async with session_manager.session() as session:
        yield session
