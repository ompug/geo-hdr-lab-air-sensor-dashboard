from __future__ import annotations

import importlib
from datetime import datetime, timezone

from fastapi.testclient import TestClient


def test_api_health_sensor_and_history(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AIR_SENSORS_DATABASE", str(tmp_path / "api.db"))
    monkeypatch.setenv("AIR_SENSORS_COLLECTOR_ENABLED", "false")
    import app.main
    from app.database import Reading, Sensor

    main = importlib.reload(app.main)
    with TestClient(main.app) as client:
        with main.database.session_factory.begin() as session:
            session.add(
                Sensor(
                    id="air-sensor-01",
                    name="Sensor 01",
                    hostname="sensor.example",
                    online=True,
                    last_seen=datetime.now(timezone.utc),
                )
            )
            session.add(
                Reading(
                    sensor_id="air-sensor-01",
                    timestamp=datetime.now(timezone.utc),
                    co2=445,
                    pm2_5=3.2,
                )
            )

        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["database"] == "healthy"
        assert health.json()["sensors_online"] == 1

        detail = client.get("/api/sensors/air-sensor-01")
        assert detail.status_code == 200
        assert detail.json()["latest_reading"]["co2"] == 445

        history = client.get(
            "/api/sensors/air-sensor-01/history",
            params={"metric": "co2", "hours": 1},
        )
        assert history.status_code == 200
        assert history.json()["readings"][0]["co2"] == 445

        invalid = client.get(
            "/api/sensors/air-sensor-01/history",
            params={"metric": "invented"},
        )
        assert invalid.status_code == 400
