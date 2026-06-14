from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core.config import get_settings
from src.core.database import session_manager
from src.core.redis import redis_manager
from src.core.neo import neo_manager
from src.api.router import api_router
from src.core.exceptions import register_exception_handlers
from src.middleware import RequestLoggingMiddleware
from src.core.logging import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle: startup and shutdown."""
    settings = get_settings()

    # Initialize Logging
    setup_logging(settings)

    # Startup Connections
    await session_manager.init()
    await redis_manager.init()
    neo_manager.init()
    yield

    # Shutdown Connections
    await redis_manager.close()
    await session_manager.close()
    await neo_manager.close()


def create_app() -> FastAPI:
    """Factory function to create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(RequestLoggingMiddleware)

    register_exception_handlers(app)

    app.include_router(api_router, prefix="/api/v1")

    return app
