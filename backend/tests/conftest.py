from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Database
from app.main import build_services, create_app


def _seed(db: Database) -> None:
    now = datetime.now(UTC)
    db.execute(
        "INSERT INTO instruments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            "NSE_EQ|INE002A01018",
            "NSE_EQ",
            "NSE",
            "EQ",
            "RELIANCE",
            "RELIANCE INDUSTRIES LTD",
            "Reliance Industries",
            "INE002A01018",
            "2885",
            1,
            10.0,
            "upstox",
            now,
        ],
    )


@pytest.fixture
def make_client():
    def make(**overrides) -> TestClient:
        settings = Settings(_env_file=None, **overrides)
        db = Database(":memory:")
        _seed(db)
        app = create_app()
        app.state.services = build_services(settings, db)
        return TestClient(app)  # lifespan not entered: no network, no background tasks

    return make
