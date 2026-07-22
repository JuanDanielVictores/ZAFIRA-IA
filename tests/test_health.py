from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_health_head() -> None:
    # Monitores de uptime (UptimeRobot) piden HEAD por defecto; sin soporte
    # explícito, FastAPI responde 405 y el monitor marca el servicio caído.
    response = client.head("/health")
    assert response.status_code == 200


def test_root() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["service"] == "ZAFIRA-IA"
