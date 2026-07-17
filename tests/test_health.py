from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_health_returns_ok() -> None:
    client = TestClient(
        create_app(
            Settings(
                _env_file=None,
                database_url="postgresql+psycopg://postgres:postgres@localhost/test",
            )
        )
    )

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
