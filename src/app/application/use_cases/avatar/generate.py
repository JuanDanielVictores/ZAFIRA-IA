"""Avatar generation use case — fetch the source photo, run the model, return the result.

Storage upload is optional: when no storage backend is configured the caller
receives only the base64 payload.
"""

from __future__ import annotations

import base64

from app.application.dto.avatar import AvatarRequest, AvatarResponse
from app.infrastructure.ai.base import AvatarModel
from app.infrastructure.http.image_fetcher import ImageFetcher
from app.infrastructure.storage.base import StorageClient


class GenerateAvatarUseCase:
    def __init__(
        self, *, fetcher: ImageFetcher, model: AvatarModel, storage: StorageClient | None
    ) -> None:
        self._fetcher = fetcher
        self._model = model
        self._storage = storage

    async def execute(self, request: AvatarRequest) -> AvatarResponse:
        source_image = await self._fetcher.fetch(str(request.source_image_url))
        generated = await self._model.generate(source_image=source_image, params=request.params)

        key: str | None = None
        if self._storage is not None:
            key = f"avatars/{request.external_ref}.png"
            await self._storage.upload(key=key, data=generated, content_type="image/png")

        return AvatarResponse(
            external_ref=request.external_ref,
            avatar_image_b64=base64.b64encode(generated).decode(),
            avatar_image_key=key,
            meta={"model": type(self._model).__name__, "size_bytes": len(generated)},
        )
