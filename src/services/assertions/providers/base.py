from abc import ABC, abstractmethod


class AssertionModelProvider(ABC):
    @abstractmethod
    async def propose_assertions(self, prompt: str, schema: dict) -> dict:
        """Return parsed JSON containing scenario-level assertion proposals."""
