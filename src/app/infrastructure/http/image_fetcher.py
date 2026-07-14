"""HTTP image download with content-type and size guards."""

from __future__ import annotations

from typing import Protocol

import httpx

from app.domain.exceptions import DomainError

_MAX_IMAGE_BYTES = 15 * 1024 * 1024

# Algunos CDN (ej. Etafashion) sirven imágenes reales con
# content-type 'application/octet-stream': se valida por magic bytes.
_SNIFFABLE_CONTENT_TYPES = {"application/octet-stream", "binary/octet-stream", ""}


def _looks_like_image(data: bytes) -> bool:
    return (
        data.startswith(b"\xff\xd8\xff")  # JPEG
        or data.startswith(b"\x89PNG\r\n\x1a\n")  # PNG
        or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")  # WEBP
        or data.startswith((b"GIF87a", b"GIF89a"))  # GIF
    )


class ImageFetcher(Protocol):
    async def fetch(self, url: str) -> bytes: ...


class HttpImageFetcher:
    def __init__(
        self,
        *,
        timeout_seconds: float = 30.0,
        max_bytes: int = _MAX_IMAGE_BYTES,
        transport: httpx.AsyncBaseTransport | None = None,
        cache_entries: int = 24,
    ) -> None:
        self._timeout = timeout_seconds
        self._max_bytes = max_bytes
        self._transport = transport
        # Caché en memoria por URL: la foto del usuario y la prenda se
        # re-piden en cada intento/reintento — recordar las últimas ahorra
        # ~1-2s por prueba. Las URLs son inmutables (archivos nuevos cambian
        # de nombre), así que no hay riesgo de servir contenido viejo.
        self._cache: dict[str, bytes] = {}
        self._cache_entries = cache_entries

    async def fetch(self, url: str) -> bytes:
        cached = self._cache.get(url)
        if cached is not None:
            return cached
        data = await self._download(url)
        if len(self._cache) >= self._cache_entries:
            self._cache.pop(next(iter(self._cache)))
        self._cache[url] = data
        return data

    async def _download(self, url: str) -> bytes:
        try:
            async with (
                httpx.AsyncClient(
                    timeout=self._timeout, follow_redirects=True, transport=self._transport
                ) as client,
                client.stream("GET", url) as response,
            ):
                if response.status_code != 200:
                    raise DomainError(
                        f"Image URL returned HTTP {response.status_code}", "IMAGE_FETCH_ERROR"
                    )

                content_type = (
                    response.headers.get("content-type", "").split(";")[0].strip().lower()
                )
                if not content_type.startswith("image/") and (
                    content_type not in _SNIFFABLE_CONTENT_TYPES
                ):
                    raise DomainError(
                        f"URL did not return an image (got '{content_type or 'unknown'}')",
                        "IMAGE_INVALID_CONTENT_TYPE",
                    )

                declared_length = response.headers.get("content-length", "")
                if declared_length.isdigit() and int(declared_length) > self._max_bytes:
                    raise DomainError("Image exceeds the allowed size", "IMAGE_TOO_LARGE")

                # Stream + cota incremental: nunca bufferizar más de max_bytes en RAM,
                # incluso si el servidor miente u omite Content-Length.
                buffer = bytearray()
                async for chunk in response.aiter_bytes():
                    buffer.extend(chunk)
                    if len(buffer) > self._max_bytes:
                        raise DomainError("Image exceeds the allowed size", "IMAGE_TOO_LARGE")

                data = bytes(buffer)
                # Si el header no era image/*, validar por contenido real
                if not content_type.startswith("image/") and not _looks_like_image(data):
                    raise DomainError(
                        f"URL did not return an image (got '{content_type or 'unknown'}')",
                        "IMAGE_INVALID_CONTENT_TYPE",
                    )
                return data
        except httpx.HTTPError as exc:
            raise DomainError(f"Could not download image: {exc}", "IMAGE_FETCH_ERROR") from exc
