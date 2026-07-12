"""Test environment + shared helpers/fakes."""

import os

os.environ["AI_BACKEND"] = "stub"


class FakeImageFetcher:
    def __init__(self, payload: bytes = b"fake-image-bytes") -> None:
        self.payload = payload
        self.requested: list[str] = []

    async def fetch(self, url: str) -> bytes:
        self.requested.append(url)
        return self.payload


class InMemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def upload(self, *, key: str, data: bytes, content_type: str = "image/png") -> None:
        self.objects[key] = data
