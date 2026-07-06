"""Gemini image backend — try-on/avatar composites via Gemini 2.5 Flash Image.

Plain REST over httpx (models/{model}:generateContent with inline images);
no extra SDK dependency. Wire it up with AI_BACKEND=gemini + GEMINI_API_KEY.
"""

from __future__ import annotations

import base64
from typing import Any

import httpx

from app.domain.exceptions import DomainError

TRYON_PROMPT_TEMPLATE = (
    "Virtual try-on task with two input images.\n"
    "IMAGE 1 is the ONLY real person. It is the sole source of identity. You must "
    "keep this person's face, facial features, facial structure, skin tone, hair, "
    "eyes, expression, body and background EXACTLY as they are — pixel-faithful. "
    "Never alter, beautify, swap, blend or regenerate the face or head of IMAGE 1.\n"
    "IMAGE 2 is a {garment_label} garment product photo. Use it ONLY as a clothing "
    "reference: extract the {garment_label} garment and nothing else. If IMAGE 2 "
    "shows a model, mannequin, face, head, hands or any other person, completely "
    "ignore and discard them — do NOT transfer any facial features, skin or body "
    "from IMAGE 2 onto the result.\n"
    "Output: the person from IMAGE 1, unchanged, now wearing the extracted "
    "{garment_label} garment. Replace only the {garment_label} clothing. "
    "Return only the final image."
)

AVATAR_PROMPT = (
    "Generate a clean, semi-realistic avatar portrait of the person in the image. "
    "Preserve identity and facial features. Neutral studio background. "
    "Return only the final image."
)

_GARMENT_LABELS = {
    "upper_body": "upper-body",
    "lower_body": "lower-body",
    "dress": "full-body dress",
}


def _detect_mime(image: bytes) -> str:
    if image.startswith(b"\x89PNG"):
        return "image/png"
    if image.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if image[:16].find(b"WEBP") != -1:
        return "image/webp"
    return "image/jpeg"


class GeminiImageClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://generativelanguage.googleapis.com",
        timeout_seconds: int = 120,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._transport = transport

    async def generate(self, *, prompt: str, images: list[bytes]) -> bytes:
        parts: list[dict[str, Any]] = [{"text": prompt}]
        for image in images:
            parts.append(
                {
                    "inline_data": {
                        "mime_type": _detect_mime(image),
                        "data": base64.b64encode(image).decode(),
                    }
                }
            )

        url = f"{self._base_url}/v1beta/models/{self._model}:generateContent"
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            response = await client.post(
                url,
                json={"contents": [{"parts": parts}]},
                headers={"x-goog-api-key": self._api_key},
            )

        if response.status_code == 429:
            raise DomainError(
                "Gemini quota/rate limit exceeded (enable billing or retry later)",
                "RATE_LIMITED",
            )
        if response.status_code >= 500:
            raise DomainError(
                f"Gemini upstream error (HTTP {response.status_code})", "PROVIDER_UNAVAILABLE"
            )
        if response.status_code != 200:
            raise DomainError(
                f"Gemini rejected the request (HTTP {response.status_code})", "PROVIDER_ERROR"
            )
        return self._extract_image(response.json())

    @staticmethod
    def _extract_image(data: dict[str, Any]) -> bytes:
        for candidate in data.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                inline = part.get("inline_data") or part.get("inlineData") or {}
                if inline.get("data"):
                    return base64.b64decode(inline["data"])
        raise DomainError(
            "Gemini returned no image (safety block or text-only reply)", "GENERATION_REJECTED"
        )


class GeminiTryOnModel:
    def __init__(self, *, client: GeminiImageClient) -> None:
        self._client = client

    async def generate(
        self,
        *,
        person_image: bytes,
        garment_image: bytes,
        garment_type: str,
        params: dict[str, Any],
    ) -> bytes:
        label = _GARMENT_LABELS.get(garment_type, "upper-body")
        prompt = params.get("prompt") or TRYON_PROMPT_TEMPLATE.format(garment_label=label)
        return await self._client.generate(prompt=prompt, images=[person_image, garment_image])


class GeminiAvatarModel:
    def __init__(self, *, client: GeminiImageClient) -> None:
        self._client = client

    async def generate(self, *, source_image: bytes, params: dict[str, Any]) -> bytes:
        prompt = params.get("prompt") or AVATAR_PROMPT
        return await self._client.generate(prompt=prompt, images=[source_image])
