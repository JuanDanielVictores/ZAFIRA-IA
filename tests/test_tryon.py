"""Try-on endpoint tests — no network, no MinIO (fakes via dependency_overrides)."""

import base64

from fastapi.testclient import TestClient

from app.interfaces.dependencies import get_image_fetcher, get_storage_client
from app.main import app
from tests.conftest import FakeImageFetcher, InMemoryStorage

client = TestClient(app)

_PERSON_URL = "https://media.example.com/avatars/user-1.png"
_GARMENT_URL = "https://media.example.com/products/jacket-77.jpg"


def test_generate_tryon_happy_path() -> None:
    fetcher = FakeImageFetcher(payload=b"person-bytes")
    storage = InMemoryStorage()

    app.dependency_overrides[get_image_fetcher] = lambda: fetcher
    app.dependency_overrides[get_storage_client] = lambda: storage

    try:
        response = client.post(
            "/api/v1/tryon",
            json={
                "external_ref": "tryon-7",
                "person_image_url": _PERSON_URL,
                "garment_image_url": _GARMENT_URL,
                "garment_type": "upper_body",
                "params": {},
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["external_ref"] == "tryon-7"
    assert data["result_image_key"] == "tryons/tryon-7.png"
    assert data["meta"]["model"] == "StubTryOnModel"

    assert base64.b64decode(data["result_image_b64"]) == b"person-bytes"

    assert fetcher.requested == [_PERSON_URL, _GARMENT_URL]
    assert storage.objects["tryons/tryon-7.png"] == b"person-bytes"


def test_tryon_without_storage_returns_b64_and_null_key() -> None:
    fetcher = FakeImageFetcher(payload=b"person-bytes")

    app.dependency_overrides[get_image_fetcher] = lambda: fetcher
    app.dependency_overrides[get_storage_client] = lambda: None

    try:
        response = client.post(
            "/api/v1/tryon",
            json={
                "external_ref": "tryon-9",
                "person_image_url": _PERSON_URL,
                "garment_image_url": _GARMENT_URL,
                "garment_type": "upper_body",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["result_image_key"] is None
    assert base64.b64decode(data["result_image_b64"]) == b"person-bytes"


def test_invalid_garment_type_rejected() -> None:
    response = client.post(
        "/api/v1/tryon",
        json={
            "external_ref": "tryon-8",
            "person_image_url": _PERSON_URL,
            "garment_image_url": _GARMENT_URL,
            "garment_type": "shoes",
        },
    )

    assert response.status_code == 422
