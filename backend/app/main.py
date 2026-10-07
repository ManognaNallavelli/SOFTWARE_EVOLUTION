"""FastAPI application entrypoint."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import analysis, architecture, auth, healthcheck, projects, rag
from app.config import get_settings
from app.db.mongo import close_mongo, connect_mongo
from app.rag.embedder import warmup_embedding_model
from app.utils.logging import configure_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    configure_logging(debug=settings.debug)
    logger.info("Starting %s (%s)", settings.app_name, settings.app_env)
    await connect_mongo()
    try:
        warmup_embedding_model(settings.embedding_model_name)
    except Exception:  # noqa: BLE001
        logger.exception("Embedding model warmup failed (will load lazily on first use)")
    yield
    await close_mongo()
    logger.info("Shutting down %s", settings.app_name)


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(healthcheck.router, prefix=settings.api_prefix)
    application.include_router(auth.router, prefix=settings.api_prefix)
    application.include_router(projects.router, prefix=settings.api_prefix)
    application.include_router(analysis.router, prefix=settings.api_prefix)
    application.include_router(architecture.router, prefix=settings.api_prefix)
    application.include_router(rag.router, prefix=settings.api_prefix)
    return application


app = create_app()
