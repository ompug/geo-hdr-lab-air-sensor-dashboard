from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select
from unittest.mock import AsyncMock

from app.collector import LiveHub, SensorRuntime
from app.config import SensorConfig, Settings
from app.database import Database, Reading, Sensor


def make_runtime(
    settings: Settings,
    database: Database,
    client: httpx.AsyncClient,
) -> SensorRuntime:
    database.initialize()
    return SensorRuntime(
        SensorConfig("air-sensor-test", "Test sensor", "sensor.example"),
        settings,
        database,
        client,
        LiveHub(),
    )


@pytest.mark.asyncio
async def test_real_entity_update_writes_database(settings: Settings) -> None:
    database = Database(settings)
    database.initialize()
    with database.session_factory.begin() as session:
        session.add(
            Sensor(
                id="air-sensor-test",
                name="Test sensor",
                hostname="sensor.example",
            )
        )
    async with httpx.AsyncClient() as client:
        runtime = make_runtime(settings, database, client)
        runtime._last_write = time.monotonic() - 10
        await runtime._handle_entity(
            {
                "id": "sensor-co2",
                "name_id": "sensor/CO2",
                "domain": "sensor",
                "name": "CO2",
                "value": 438,
            }
        )
        await asyncio.sleep(0.05)
    with database.session_factory() as session:
        reading = session.scalar(select(Reading))
        assert reading is not None
        assert reading.co2 == 438
        assert session.get(Sensor, "air-sensor-test").online is True


@pytest.mark.asyncio
async def test_rest_consistency_retrieves_actual_entity(settings: Settings) -> None:
    database = Database(settings)
    database.initialize()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/sensor/CO2"
        return httpx.Response(
            200,
            json={"id": "sensor-co2", "name_id": "sensor/CO2", "value": 512},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        runtime = make_runtime(settings, database, client)
        runtime.entities["sensor-co2"] = {
            "id": "sensor-co2",
            "name_id": "sensor/CO2",
            "domain": "sensor",
            "name": "CO2",
        }
        await runtime._poll_rest()
        assert runtime.metrics["co2"] == 512


@pytest.mark.asyncio
async def test_malformed_entity_does_not_mark_sensor_online(settings: Settings) -> None:
    database = Database(settings)
    database.initialize()
    async with httpx.AsyncClient() as client:
        runtime = make_runtime(settings, database, client)
        await runtime._handle_entity({"id": "bad", "domain": "sensor", "value": "broken"})
        assert runtime.online is False
        assert runtime.metrics == {}


@pytest.mark.asyncio
async def test_stale_logic_marks_old_real_data_offline(settings: Settings) -> None:
    database = Database(settings)
    async with httpx.AsyncClient() as client:
        runtime = make_runtime(settings, database, client)
        runtime.last_seen = datetime.now(timezone.utc) - timedelta(
            seconds=settings.stale_after_seconds + 1
        )
        runtime.metrics["co2"] = 400
        assert runtime.online is False
        assert runtime.snapshot()["stale"] is True


@pytest.mark.asyncio
async def test_disconnect_triggers_reconnect(settings: Settings, monkeypatch) -> None:
    database = Database(settings)
    async with httpx.AsyncClient() as client:
        runtime = make_runtime(settings, database, client)
        stream = AsyncMock(side_effect=ConnectionError("offline"))
        runtime._stream_session = stream

        sleep_calls = 0

        async def stop_after_retry(_: float) -> None:
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls >= 2:
                raise asyncio.CancelledError

        monkeypatch.setattr("app.collector.asyncio.sleep", stop_after_retry)
        with pytest.raises(asyncio.CancelledError):
            await runtime.run()
        assert stream.await_count == 2


def test_retention_is_configurable(settings: Settings) -> None:
    database = Database(settings)
    database.initialize()
    with database.session_factory.begin() as session:
        session.add(
            Sensor(
                id="air-sensor-test",
                name="Test sensor",
                hostname="sensor.example",
            )
        )
        session.add_all(
            [
                Reading(
                    sensor_id="air-sensor-test",
                    timestamp=datetime.now(timezone.utc) - timedelta(days=31),
                    co2=400,
                ),
                Reading(
                    sensor_id="air-sensor-test",
                    timestamp=datetime.now(timezone.utc),
                    co2=410,
                ),
            ]
        )
    assert database.cleanup(30) == 1
    with database.session_factory() as session:
        assert len(session.scalars(select(Reading)).all()) == 1
