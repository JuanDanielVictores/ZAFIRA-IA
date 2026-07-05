from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.domain.exceptions import DomainError
from app.interfaces.api.v1 import api_router
from app.interfaces.health import router as health_router


def create_app() -> FastAPI:
    settings = get_settings()

    tags_metadata = [
        {"name": "health", "description": "Liveness/readiness probe."},
        {"name": "avatar", "description": "Semi-realistic avatar generation from a user photo."},
        {"name": "tryon", "description": "Virtual try-on of garments over an avatar."},
    ]

    app = FastAPI(
        title=settings.app_name,
        version=settings.api_version,
        description=(
            "ZAFIRA-IA — internal AI microservice. "
            "ZAFIRA-CORE (Django/Celery) → ZAFIRA-IA → AI models + object storage."
        ),
        openapi_url="/openapi.json",
        docs_url="/docs" if settings.api_docs_enabled else None,
        redoc_url="/redoc" if settings.api_docs_enabled else None,
        openapi_tags=tags_metadata,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router, tags=["health"])
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    @app.exception_handler(DomainError)
    async def domain_error_handler(_request: Request, exc: DomainError) -> JSONResponse:
        transient = exc.code in {"RATE_LIMITED", "PROVIDER_UNAVAILABLE"}
        return JSONResponse(
            status_code=503 if transient else 422,
            content={"detail": exc.message, "code": exc.code},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": exc.errors()})

    @app.get("/", tags=["root"], summary="Service metadata")
    async def root() -> dict[str, str]:
        return {
            "service": settings.app_name,
            "health": "/health",
            "docs": "/docs" if settings.api_docs_enabled else "disabled",
            "openapi": "/openapi.json",
        }

    return app


app = create_app()
