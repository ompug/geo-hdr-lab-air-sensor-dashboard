from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, text

from app.collector import CollectorManager
from app.config import load_sensor_configs, load_settings
from app.database import Database, READING_FIELDS, Reading, Sensor

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

settings = load_settings()
database = Database(settings)
manager = CollectorManager(settings, database)
STATIC_DIR = Path(__file__).with_name("static")


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def reading_dict(reading: Reading) -> dict[str, Any]:
    return {
        "id": reading.id,
        "sensor_id": reading.sensor_id,
        "timestamp": iso(reading.timestamp),
        **{field: getattr(reading, field) for field in READING_FIELDS},
    }


def database_sensor_dict(sensor: Sensor, latest: Reading | None = None) -> dict[str, Any]:
    metrics = (
        {field: getattr(latest, field) for field in READING_FIELDS}
        if latest is not None
        else {}
    )
    return {
        "id": sensor.id,
        "name": sensor.name,
        "hostname": sensor.hostname,
        "online": sensor.online,
        "stale": not sensor.online,
        "last_seen": iso(sensor.last_seen),
        "sse_connected": False,
        "ip_address": sensor.ip_address,
        "mac": sensor.mac,
        "model": sensor.model,
        "firmware_version": sensor.firmware_version,
        "esphome_version": sensor.esphome_version,
        "device_title": sensor.device_title,
        "metrics": metrics,
    }


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.initialize()
    if settings.collector_enabled:
        configs = load_sensor_configs(settings.sensors_file)
        await manager.start(configs)
    try:
        yield
    finally:
        await manager.stop()


app = FastAPI(
    title="Apollo AIR-1 Research Sensor Network",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/api/health")
def health() -> dict[str, Any]:
    database_healthy = True
    database_error = None
    try:
        with database.session_factory() as session:
            session.execute(text("SELECT 1"))
    except Exception as exc:
        database_healthy = False
        database_error = str(exc)
    snapshots = manager.snapshots()
    if snapshots:
        online = sum(sensor["online"] for sensor in snapshots)
        total = len(snapshots)
    else:
        with database.session_factory() as session:
            total = session.scalar(select(func.count()).select_from(Sensor)) or 0
            online = (
                session.scalar(
                    select(func.count()).select_from(Sensor).where(Sensor.online.is_(True))
                )
                or 0
            )
    return {
        "status": "healthy" if database_healthy else "degraded",
        "application": "healthy",
        "database": "healthy" if database_healthy else "unhealthy",
        "database_error": database_error,
        "sensors_total": total,
        "sensors_online": online,
        "sensors_offline": total - online,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/sensors")
def sensors() -> list[dict[str, Any]]:
    snapshots = manager.snapshots()
    if snapshots:
        return snapshots
    with database.session_factory() as session:
        rows = session.scalars(select(Sensor).order_by(Sensor.id)).all()
        return [database_sensor_dict(sensor) for sensor in rows]


@app.get("/api/sensors/{sensor_id}")
def sensor_detail(sensor_id: str) -> dict[str, Any]:
    runtime = manager.runtimes.get(sensor_id)
    with database.session_factory() as session:
        sensor = session.get(Sensor, sensor_id)
        if sensor is None:
            raise HTTPException(404, "Sensor not found")
        latest = session.scalar(
            select(Reading)
            .where(Reading.sensor_id == sensor_id)
            .order_by(Reading.timestamp.desc())
            .limit(1)
        )
        payload = runtime.snapshot() if runtime else database_sensor_dict(sensor, latest)
        payload["latest_reading"] = reading_dict(latest) if latest else None
        return payload


@app.get("/api/sensors/{sensor_id}/readings")
@app.get("/api/sensors/{sensor_id}/history")
def sensor_history(
    sensor_id: str,
    hours: float = Query(default=24, gt=0, le=24 * 365),
    metric: str | None = Query(default=None),
    limit: int = Query(default=2000, ge=1, le=10000),
) -> dict[str, Any]:
    if metric is not None and metric not in READING_FIELDS:
        raise HTTPException(400, f"Unknown metric: {metric}")
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    with database.session_factory() as session:
        if session.get(Sensor, sensor_id) is None:
            raise HTTPException(404, "Sensor not found")
        rows = session.scalars(
            select(Reading)
            .where(Reading.sensor_id == sensor_id, Reading.timestamp >= since)
            .order_by(Reading.timestamp.desc())
            .limit(limit)
        ).all()
    readings = [reading_dict(row) for row in reversed(rows)]
    if metric:
        readings = [
            {"timestamp": row["timestamp"], metric: row[metric]}
            for row in readings
            if row[metric] is not None
        ]
    return {
        "sensor_id": sensor_id,
        "metric": metric,
        "hours": hours,
        "count": len(readings),
        "readings": readings,
    }


@app.get("/api/metrics")
def metrics() -> dict[str, Any]:
    with database.session_factory() as session:
        reading_count = session.scalar(select(func.count()).select_from(Reading)) or 0
        latest = session.scalar(select(func.max(Reading.timestamp)))
    snapshots = manager.snapshots()
    return {
        "sensor_count": len(snapshots),
        "online_count": sum(sensor["online"] for sensor in snapshots),
        "reading_count": reading_count,
        "latest_reading": iso(latest),
        "available_metrics": list(READING_FIELDS),
    }


@app.websocket("/api/ws")
async def websocket_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    queue = manager.hub.subscribe()
    await websocket.send_json({"type": "snapshot", "sensors": manager.snapshots()})
    try:
        while True:
            try:
                message = await asyncio.wait_for(queue.get(), timeout=25)
                await websocket.send_json(message)
            except TimeoutError:
                await websocket.send_json({"type": "keepalive"})
    except WebSocketDisconnect:
        pass
    finally:
        manager.hub.unsubscribe(queue)


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/sensor/{sensor_id}", include_in_schema=False)
def sensor_page(sensor_id: str) -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
