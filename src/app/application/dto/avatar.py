"""Avatar generation DTOs."""

from typing import Any

from pydantic import BaseModel, Field, HttpUrl

# external_ref becomes part of the storage key — restrict it to filesystem-safe
# characters so a caller can never inject path segments (e.g. '../').
EXTERNAL_REF_PATTERN = r"^[A-Za-z0-9._-]+$"


class AvatarRequest(BaseModel):
    external_ref: str = Field(
        min_length=1,
        max_length=128,
        pattern=EXTERNAL_REF_PATTERN,
        description="Caller-side identifier (e.g. ZAFIRA-CORE avatar UUID)",
    )
    source_image_url: HttpUrl = Field(description="Public or presigned URL of the user photo")
    params: dict[str, Any] = Field(
        default_factory=dict, description="Backend-specific generation parameters"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "external_ref": "9f4e2c1a-7b3d-4f6a-9c1e-2d8b5a0f3e7c",
                "source_image_url": "https://media.zafira.app/uploads/selfie.jpg",
                "params": {},
            }
        }
    }


class AvatarResponse(BaseModel):
    external_ref: str
    avatar_image_b64: str = Field(description="Base64-encoded bytes of the generated avatar")
    avatar_image_key: str | None = Field(
        default=None, description="Object storage key (only when storage is configured)"
    )
    meta: dict[str, Any] = Field(default_factory=dict)
