# src/core/ports.py
from abc import ABC, abstractmethod
from typing import Any, Dict


class GraphEventConsumer(ABC):
    """
    Abstract interface for consuming navigation graphs from the Crawler.
    Implementations could be a FastAPI endpoint, a Kafka consumer, or a gRPC servicer.
    """

    @abstractmethod
    async def start_consuming(self) -> None:
        pass


class ResultPublisher(ABC):
    """
    Abstract interface for publishing the final labeled results to other services.
    Implementations could write to Postgres, emit a RabbitMQ event, or call a webhook.
    """

    @abstractmethod
    async def publish_state(self, labeled_state: Any) -> None:
        pass

    @abstractmethod
    async def publish_transition(self, labeled_transition: Any) -> None:
        pass
