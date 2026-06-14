from neo4j import AsyncGraphDatabase
from src.core.config import get_settings

settings = get_settings()


class NeoManager:
    def __init__(self):
        self.driver = None

    def init(self):
        self.driver = AsyncGraphDatabase.driver(
            settings.neo4j_url, auth=(settings.neo4j_username, settings.neo4j_password)
        )

    async def close(self):
        """Close the Neo4j driver connection pool gracefully."""
        if self.driver:
            await self.driver.close()
            self.driver = None


neo_manager = NeoManager()
