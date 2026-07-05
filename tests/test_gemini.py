"""Gemini backend tests — no network (httpx.MockTransport / fake client)."""

import base64
import json

import httpx
import pytest

from app.domain.exceptions import DomainError
from app.infrastructure.ai.gemini import (
    GeminiImageClient,
    GeminiTryOnModel,
    _detect_mime,
)

_PNG = b"\x89PNG\r\n\x1a\nrest"
_JPEG = b"\xff\xd8\xffrest"


def test_detect_mime() -> None:
    assert _detect_mime(_PNG) == "image/png"
    assert _detect_mime(_JPEG) == "image/jpeg"
    assert _detect_mime(b"unknown-bytes") == "image/jpeg"


def _gemini_response(image: bytes | None) -> dict:
    parts = [{"text": "done"}]
    if image is not None:
        parts.append(
            {"inline_data": {"mime_type": "image/png", "data": base64.b64encode(image).decode()}}
        )
    return {"candidates": [{"content": {"parts": parts}}]}


def _client_with_transport(handler) -> GeminiImageClient:
    return GeminiImageClient(
        api_key="test-key",
        model="gemini-2.5-flash-image",
        transport=httpx.MockTransport(handler),
    )


async def test_generate_extracts_inline_image() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["api_key"] = request.headers.get("x-goog-api-key")
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json=_gemini_response(b"generated-image"))

    client = _client_with_transport(handler)
    result = await client.generate(prompt="try on", images=[_PNG, _JPEG])

    assert result == b"generated-image"
    assert captured["api_key"] == "test-key"
    assert "gemini-2.5-flash-image:generateContent" in captured["url"]
    parts = captured["payload"]["contents"][0]["parts"]
    assert parts[0] == {"text": "try on"}
    assert parts[1]["inline_data"]["mime_type"] == "image/png"
    assert parts[2]["inline_data"]["mime_type"] == "image/jpeg"


async def test_generate_without_image_raises_generation_rejected() -> None:
    client = _client_with_transport(
        lambda request: httpx.Response(200, json=_gemini_response(None))
    )

    with pytest.raises(DomainError) as exc_info:
        await client.generate(prompt="try on", images=[_PNG])

    assert exc_info.value.code == "GENERATION_REJECTED"


async def test_generate_429_raises_rate_limited() -> None:
    client = _client_with_transport(
        lambda request: httpx.Response(429, json={"error": {"message": "quota"}})
    )

    with pytest.raises(DomainError) as exc_info:
        await client.generate(prompt="try on", images=[_PNG])

    assert exc_info.value.code == "RATE_LIMITED"


async def test_generate_5xx_raises_provider_unavailable() -> None:
    client = _client_with_transport(
        lambda request: httpx.Response(502, json={"error": {"message": "bad gateway"}})
    )

    with pytest.raises(DomainError) as exc_info:
        await client.generate(prompt="try on", images=[_PNG])

    assert exc_info.value.code == "PROVIDER_UNAVAILABLE"


async def test_generate_other_4xx_raises_provider_error() -> None:
    client = _client_with_transport(
        lambda request: httpx.Response(400, json={"error": {"message": "bad request"}})
    )

    with pytest.raises(DomainError) as exc_info:
        await client.generate(prompt="try on", images=[_PNG])

    assert exc_info.value.code == "PROVIDER_ERROR"


class FakeGeminiClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def generate(self, *, prompt: str, images: list[bytes]) -> bytes:
        self.calls.append({"prompt": prompt, "images": images})
        return b"composited"


async def test_tryon_model_builds_prompt_by_garment_type() -> None:
    fake = FakeGeminiClient()
    model = GeminiTryOnModel(client=fake)

    result = await model.generate(
        person_image=b"person",
        garment_image=b"garment",
        garment_type="lower_body",
        params={},
    )

    assert result == b"composited"
    assert fake.calls[0]["images"] == [b"person", b"garment"]
    assert "lower-body" in fake.calls[0]["prompt"]


async def test_tryon_model_honors_prompt_override() -> None:
    fake = FakeGeminiClient()
    model = GeminiTryOnModel(client=fake)

    await model.generate(
        person_image=b"person",
        garment_image=b"garment",
        garment_type="dress",
        params={"prompt": "custom prompt"},
    )

    assert fake.calls[0]["prompt"] == "custom prompt"
