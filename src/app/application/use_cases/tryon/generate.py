"""Try-on use case — fetch person + garment images, run the model, return the result.

Storage upload is optional: when no storage backend is configured the caller
receives only the base64 payload.
"""

from __future__ import annotations

import base64

from app.application.dto.tryon import TryOnRequest, TryOnResponse
from app.infrastructure.ai.base import TryOnModel
from app.infrastructure.http.image_fetcher import ImageFetcher
from app.infrastructure.storage.base import StorageClient


class GenerateTryOnUseCase:
    def __init__(
        self, *, fetcher: ImageFetcher, model: TryOnModel, storage: StorageClient | None
    ) -> None:
        self._fetcher = fetcher
        self._model = model
        self._storage = storage

    async def execute(self, request: TryOnRequest) -> TryOnResponse:
        person_image = await self._fetcher.fetch(str(request.person_image_url))
        garment_image = await self._fetcher.fetch(str(request.garment_image_url))
        # Outfit en una llamada: segunda prenda opcional (torso + pierna juntos)
        extra_garment_image = None
        if request.extra_garment_image_url is not None:
            extra_garment_image = await self._fetcher.fetch(
                str(request.extra_garment_image_url)
            )
        generated = await self._model.generate(
            person_image=person_image,
            garment_image=garment_image,
            garment_type=request.garment_type,
            params=request.params,
            extra_garment_image=extra_garment_image,
            extra_garment_type=request.extra_garment_type,
        )

        key: str | None = None
        if self._storage is not None:
            key = f"tryons/{request.external_ref}.png"
            await self._storage.upload(key=key, data=generated, content_type="image/png")

        return TryOnResponse(
            external_ref=request.external_ref,
            result_image_b64=base64.b64encode(generated).decode(),
            result_image_key=key,
            meta={"model": type(self._model).__name__, "size_bytes": len(generated)},
        )
