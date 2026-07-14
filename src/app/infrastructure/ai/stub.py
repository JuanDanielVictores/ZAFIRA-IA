"""Stub backend: passthrough models that exercise the full pipeline
(fetch → generate → upload) without GPU or provider network. Default backend."""

from typing import Any


class StubAvatarModel:
    async def generate(self, *, source_image: bytes, params: dict[str, Any]) -> bytes:
        return source_image


class StubTryOnModel:
    async def generate(
        self,
        *,
        person_image: bytes,
        garment_image: bytes,
        garment_type: str,
        params: dict[str, Any],
        extra_garment_image: bytes | None = None,
        extra_garment_type: str | None = None,
    ) -> bytes:
        return person_image
