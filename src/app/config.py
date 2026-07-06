from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "ZAFIRA-IA"
    api_version: str = "0.1.0"
    debug: bool = True
    api_docs_enabled: bool = True
    api_v1_prefix: str = "/api/v1"

    # HMAC: JSON object {"client_id": "secret", ...}
    hmac_allowed_clients_json: str | None = Field(
        default=None, validation_alias="HMAC_ALLOWED_CLIENTS"
    )
    hmac_clock_skew_seconds: int = Field(
        default=60, ge=1, le=3600, validation_alias="HMAC_CLOCK_SKEW_SECONDS"
    )

    # 'stub' exercises the full pipeline (fetch → model → storage) without GPU
    # or provider network; 'hosted' delegates to a Replicate-style prediction API.
    ai_backend: Literal["stub", "hosted", "gemini", "hybrid"] = Field(
        default="stub", validation_alias="AI_BACKEND"
    )

    # Hosted provider (only required when ai_backend == 'hosted')
    provider_base_url: str | None = Field(default=None, validation_alias="PROVIDER_BASE_URL")
    provider_api_key: str | None = Field(default=None, validation_alias="PROVIDER_API_KEY")
    avatar_model_ref: str | None = Field(default=None, validation_alias="AVATAR_MODEL_REF")
    tryon_model_ref: str | None = Field(default=None, validation_alias="TRYON_MODEL_REF")
    provider_timeout_seconds: int = Field(
        default=180, ge=10, le=900, validation_alias="PROVIDER_TIMEOUT_SECONDS"
    )

    # Gemini (only required when ai_backend == 'gemini')
    gemini_api_key: str | None = Field(default=None, validation_alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-flash-image", validation_alias="GEMINI_MODEL")
    gemini_base_url: str = Field(
        default="https://generativelanguage.googleapis.com",
        validation_alias="GEMINI_BASE_URL",
    )
    gemini_timeout_seconds: int = Field(
        default=120, ge=10, le=900, validation_alias="GEMINI_TIMEOUT_SECONDS"
    )

    # Object storage (S3/MinIO) — bucket shared with ZAFIRA-CORE
    storage_endpoint_url: str | None = Field(default=None, validation_alias="STORAGE_ENDPOINT_URL")
    storage_access_key: str | None = Field(default=None, validation_alias="STORAGE_ACCESS_KEY")
    storage_secret_key: str | None = Field(default=None, validation_alias="STORAGE_SECRET_KEY")
    storage_bucket: str = Field(default="zafira-media", validation_alias="STORAGE_BUCKET")
    storage_region: str | None = Field(default=None, validation_alias="STORAGE_REGION")


@lru_cache
def get_settings() -> Settings:
    return Settings()
