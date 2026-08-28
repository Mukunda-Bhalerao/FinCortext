"""Unit tests for the health endpoint and app factory."""

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_endpoint_returns_ok():
    app = create_app()
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "fincortext-backend"
    assert "config" in payload
    # Secrets must never be exposed in the health payload.
    assert "news_api_key" not in str(payload)