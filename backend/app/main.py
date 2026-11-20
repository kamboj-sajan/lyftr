"""FastAPI app factory: lifespan (DB, key pool, cache), CORS and error handling."""

from __future__ import annotations

import logging
import os
import warnings
from contextlib import asynccontextmanager
from typing import AsyncIterator

# Use the model cost map bundled with LiteLLM instead of fetching it at import time.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
# Pydantic warns about ReadOnly TypedDict items inside LiteLLM's own types; it is noise.
warnings.filterwarnings("ignore", message=r".*ReadOnly. qualifier", category=UserWarning)

import litellm  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from app.config import Settings  # noqa: E402
from app.db import Database  # noqa: E402
from app.llm.gateway import LLMGateway  # noqa: E402
from app.routes import chat, health, sessions  # noqa: E402

logger = logging.getLogger("app")

INTERNAL_ERROR = {"detail": "internal server error"}


def configure_logging(level: str) -> None:
    logging.basicConfig(level=level.upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("app").setLevel(level.upper())
    # LiteLLM debug/verbose logs can include request params; keep them quiet.
    litellm.suppress_debug_info = True
    litellm.set_verbose = False
    for name in ("LiteLLM", "LiteLLM Router", "LiteLLM Proxy", "litellm"):
        logging.getLogger(name).setLevel(logging.ERROR)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings.log_level)
        try:
            gateway = LLMGateway(settings)
        except ValueError as exc:
            logger.error("startup failed: %s", exc)  # message never contains key values
            raise
        db = Database(settings.database_path)
        await db.init()
        gateway.setup_cache()
        await gateway.warm_up()

        app.state.settings = settings
        app.state.db = db
        app.state.gateway = gateway
        app.state.session_locks = chat.SessionLocks()
        logger.info(
            "startup ok keys_configured=%d model=%s cache=%s failure_simulation=%s db=%s",
            len(gateway.slots),
            settings.llm_model,
            settings.cache_type,
            settings.enable_failure_simulation,
            settings.database_path,
        )
        yield

    app = FastAPI(title="Lyftr Chat API", version="1.0.0", lifespan=lifespan, redirect_slashes=False)

    # Registered before CORS so it sits *inside* the CORS middleware: a 500 still
    # carries CORS headers and the browser can read the JSON body.
    @app.middleware("http")
    async def catch_unhandled(request: Request, call_next):  # type: ignore[no-untyped-def]
        try:
            return await call_next(request)
        except Exception:
            logger.exception("unhandled error on %s %s", request.method, request.url.path)
            return JSONResponse(status_code=500, content=INTERNAL_ERROR)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Simulate-Failure"],
    )

    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content=INTERNAL_ERROR)

    app.include_router(health.router)
    app.include_router(chat.router)
    app.include_router(sessions.router)
    return app


app = create_app()
