from arq import create_pool
from arq.connections import RedisSettings
from src.core.config import get_settings

settings = get_settings()

redis_settings = RedisSettings.from_dsn(settings.redis_url)


class RedisManager:
    def __init__(self):
        self.pool = None

    async def init(self):
        """Initialize the ARQ Redis pool for enqueuing jobs."""
        self.pool = await create_pool(redis_settings)

    async def close(self):
        """Close the Redis pool gracefully."""
        if self.pool:
            await self.pool.close()


redis_manager = RedisManager()
