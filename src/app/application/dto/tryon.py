"""Virtual try-on DTOs."""

from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl

from app.application.dto.avatar import EXTERNAL_REF_PATTERN

GarmentType = Literal["upper_body", "lower_body", "dress"]


class TryOnRequest(BaseModel):
    external_ref: str = Field(
        min_length=1,
        max_length=128,
        pattern=EXTERNAL_REF_PATTERN,
        description="Caller-side identifier (e.g. ZAFIRA-CORE try-on UUID)",
    )
    person_image_url: HttpUrl = Field(description="URL of the avatar or person photo")
    garment_image_url: HttpUrl = Field(description="URL of the garment product image")
    garment_type: GarmentType = Field(description="Garment category for the try-on model")
    # Outfit completo en UNA generación: segunda prenda opcional. Ahorra la
    # mitad del tiempo y del costo frente al encadenado de dos llamadas.
    extra_garment_image_url: HttpUrl | None = Field(
        default=None, description="Optional second garment for a full outfit in one pass"
    )
    extra_garment_type: GarmentType | None = Field(
        default=None, description="Garment category of the second garment"
    )
    params: dict[str, Any] = Field(
        default_factory=dict, description="Backend-specific generation parameters"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "external_ref": "5b2d8e0c-1f4a-4c7b-8d3e-9a6f2c5e1b4d",
                "person_image_url": "https://media.zafira.app/avatars/user-1.png",
                "garment_image_url": "https://media.zafira.app/products/jacket-77.jpg",
                "garment_type": "upper_body",
                "params": {},
            }
        }
    }


class TryOnResponse(BaseModel):
    external_ref: str
    result_image_b64: str = Field(description="Base64-encoded bytes of the try-on result image")
    result_image_key: str | None = Field(
        default=None, description="Object storage key (only when storage is configured)"
    )
    meta: dict[str, Any] = Field(default_factory=dict)
