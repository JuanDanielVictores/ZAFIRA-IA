from functools import lru_cache

from fastapi import Depends

from app.application.use_cases.avatar.generate import GenerateAvatarUseCase
from app.application.use_cases.get_health import GetHealthUseCase
from app.application.use_cases.tryon.generate import GenerateTryOnUseCase
from app.config import Settings, get_settings
from app.infrastructure.ai.base import AvatarModel, TryOnModel
from app.infrastructure.ai.gemini import GeminiAvatarModel, GeminiImageClient, GeminiTryOnModel
from app.infrastructure.ai.hybrid import HybridTryOnModel
from app.infrastructure.ai.hosted import (
    HostedAvatarModel,
    HostedPredictionClient,
    HostedTryOnModel,
)
from app.infrastructure.ai.stub import StubAvatarModel, StubTryOnModel
from app.infrastructure.http.image_fetcher import HttpImageFetcher, ImageFetcher
from app.infrastructure.storage.base import StorageClient
from app.infrastructure.storage.s3_client import S3StorageClient


def get_get_health_use_case(settings: Settings = Depends(get_settings)) -> GetHealthUseCase:
    return GetHealthUseCase(app_name=settings.app_name, version=settings.api_version)


@lru_cache
def get_image_fetcher() -> HttpImageFetcher:
    return HttpImageFetcher()


@lru_cache
def get_storage_client() -> S3StorageClient | None:
    settings = get_settings()
    if not settings.storage_endpoint_url:
        return None
    return S3StorageClient(
        bucket=settings.storage_bucket,
        endpoint_url=settings.storage_endpoint_url,
        access_key=settings.storage_access_key,
        secret_key=settings.storage_secret_key,
        region=settings.storage_region,
    )


def _hosted_client(
    settings: Settings, model_ref: str | None, ref_env: str
) -> HostedPredictionClient:
    if not (settings.provider_base_url and settings.provider_api_key and model_ref):
        raise RuntimeError(
            f"AI_BACKEND=hosted requires PROVIDER_BASE_URL, PROVIDER_API_KEY and {ref_env}"
        )
    return HostedPredictionClient(
        base_url=settings.provider_base_url,
        api_key=settings.provider_api_key,
        model_ref=model_ref,
        timeout_seconds=settings.provider_timeout_seconds,
    )


def _gemini_client(settings: Settings) -> GeminiImageClient:
    if not settings.gemini_api_key:
        raise RuntimeError("AI_BACKEND=gemini requires GEMINI_API_KEY")
    return GeminiImageClient(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        base_url=settings.gemini_base_url,
        timeout_seconds=settings.gemini_timeout_seconds,
    )


@lru_cache
def get_avatar_model() -> AvatarModel:
    settings = get_settings()
    if settings.ai_backend == "hosted":
        return HostedAvatarModel(
            client=_hosted_client(settings, settings.avatar_model_ref, "AVATAR_MODEL_REF")
        )
    if settings.ai_backend in ("gemini", "hybrid"):
        return GeminiAvatarModel(client=_gemini_client(settings))
    return StubAvatarModel()


@lru_cache
def get_tryon_model() -> TryOnModel:
    settings = get_settings()
    if settings.ai_backend == "hosted":
        return HostedTryOnModel(
            client=_hosted_client(settings, settings.tryon_model_ref, "TRYON_MODEL_REF")
        )
    if settings.ai_backend == "gemini":
        return GeminiTryOnModel(client=_gemini_client(settings))
    if settings.ai_backend == "hybrid":
        # Torso/vestidos -> Gemini (pixel-fiel) · Piernas -> IDM-VTON DressCode
        return HybridTryOnModel(
            gemini_model=GeminiTryOnModel(client=_gemini_client(settings)),
            hosted_model=HostedTryOnModel(
                client=_hosted_client(settings, settings.tryon_model_ref, "TRYON_MODEL_REF")
            ),
        )
    return StubTryOnModel()


def get_generate_avatar_use_case(
    fetcher: ImageFetcher = Depends(get_image_fetcher),
    model: AvatarModel = Depends(get_avatar_model),
    storage: StorageClient | None = Depends(get_storage_client),
) -> GenerateAvatarUseCase:
    return GenerateAvatarUseCase(fetcher=fetcher, model=model, storage=storage)


def get_generate_tryon_use_case(
    fetcher: ImageFetcher = Depends(get_image_fetcher),
    model: TryOnModel = Depends(get_tryon_model),
    storage: StorageClient | None = Depends(get_storage_client),
) -> GenerateTryOnUseCase:
    return GenerateTryOnUseCase(fetcher=fetcher, model=model, storage=storage)
