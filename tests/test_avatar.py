"""Avatar endpoint tests — no network, no MinIO (fakes via dependency_overrides)."""

import base64

from fastapi.testclient import TestClient

from app.interfaces.dependencies import get_image_fetcher, get_storage_client
from app.main import app
from tests.conftest import FakeImageFetcher, InMemoryStorage

client = TestClient(app)


def test_generate_avatar_happy_path() -> None:
    fetcher = FakeImageFetcher(payload=b"selfie-bytes")
    storage = InMemoryStorage()

    app.dependency_overrides[get_image_fetcher] = lambda: fetcher
    app.dependency_overrides[get_storage_client] = lambda: storage

    try:
        response = client.post(
            "/api/v1/avatar",
            json={
                "external_ref": "avatar-42",
                "source_image_url": "https://media.example.com/selfie.jpg",
                "params": {"style": "semi-realistic"},
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["external_ref"] == "avatar-42"
    assert data["avatar_image_key"] == "avatars/avatar-42.png"
    assert data["meta"]["model"] == "StubAvatarModel"
    assert data["meta"]["size_bytes"] == len(b"selfie-bytes")
    assert base64.b64decode(data["avatar_image_b64"]) == b"selfie-bytes"

    assert fetcher.requested == ["https://media.example.com/selfie.jpg"]
    assert storage.objects["avatars/avatar-42.png"] == b"selfie-bytes"


def test_invalid_source_url_rejected() -> None:
    response = client.post(
        "/api/v1/avatar",
        json={"external_ref": "x", "source_image_url": "not-a-url"},
    )

    assert response.status_code == 422


def test_external_ref_with_path_segments_rejected() -> None:
    response = client.post(
        "/api/v1/avatar",
        json={
            "external_ref": "../../etc/passwd",
            "source_image_url": "https://media.example.com/selfie.jpg",
        },
    )

    assert response.status_code == 422
