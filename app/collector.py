from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy import select

from app.config import SensorConfig, Settings
from app.database import Database, READING_FIELDS, Reading, Sensor
from app.normalize import metadata_for_entity, metric_for_entity, numeric_value
from app.sse import parse_sse

logger = logging.getLogger(__name__)


class LiveHub:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def publish(self, message: dict[str, Any]) -> None:
        for queue in tuple(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(message)


class SensorRuntime:
    def __init__(
        self,
        config: SensorConfig,
        settings: Settings,
        database: Database,
        client: httpx.AsyncClient,
        hub: LiveHub,
    ):
        self.config = config
        self.settings = settings
        self.database = database
        self.client = client
        self.hub = hub
        self.entities: dict[str, dict[str, Any]] = {}
        self.metrics: dict[str, float] = {}
        self.metadata: dict[str, str] = {}
        self.device_title: str | None = None
        self.model: str | None = "Apollo AIR-1"
        self.last_seen: datetime | None = None
        self.sse_connected = False
        self.last_error: str | None = None
        self._last_write = 0.0
        self._write_task: asyncio.Task[None] | None = None
        self._restore_discovery()

    @property
    def online(self) -> bool:
        if self.last_seen is None:
            return False
        age = (datetime.now(timezone.utc) - self.last_seen).total_seconds()
        return age <= self.settings.stale_after_seconds

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.config.id,
            "name": self.config.name,
            "hostname": self.config.hostname,
            "online": self.online,
            "stale": not self.online,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "sse_connected": self.sse_connected,
            "last_error": self.last_error,
            "ip_address": self.metadata.get("ip_address"),
            "mac": self.metadata.get("mac"),
            "model": self.model,
            "firmware_version": self.metadata.get("firmware_version"),
            "esphome_version": self.metadata.get("esphome_version"),
            "device_title": self.device_title,
            "metrics": dict(self.metrics) if self.online else dict(self.metrics),
            "entity_count": len(self.entities),
            "entities": [
                {
                    key: entity.get(key)
                    for key in ("id", "name_id", "domain", "name", "uom", "entity_category")
                }
                for entity in self.entities.values()
            ],
        }

    async def run(self) -> None:
        delay = 1.0
        while True:
            try:
                await self._stream_session()
                raise ConnectionError("SSE stream ended")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.sse_connected = False
                self.last_error = f"{type(exc).__name__}: {exc}"
                logger.warning("%s disconnected: %s", self.config.id, self.last_error)
                if self.entities:
                    try:
                        await self._poll_rest()
                    except Exception:
                        logger.debug(
                            "%s REST fallback failed", self.config.id, exc_info=True
                        )
                self.hub.publish({"type": "sensor", "sensor": self.snapshot()})
                await asyncio.sleep(delay + random.random())
                delay = min(delay * 2, self.settings.sse_reconnect_max_seconds)
            else:
                delay = 1.0

    def _restore_discovery(self) -> None:
        with self.database.session_factory() as session:
            sensor = session.get(Sensor, self.config.id)
            if sensor is None:
                return
            self.metadata = {
                key: value
                for key, value in {
                    "ip_address": sensor.ip_address,
                    "mac": sensor.mac,
                    "firmware_version": sensor.firmware_version,
                    "esphome_version": sensor.esphome_version,
                }.items()
                if value
            }
            self.device_title = sensor.device_title
            self.model = sensor.model or self.model
            if not sensor.entities_json:
                return
            try:
                entities = json.loads(sensor.entities_json)
                self.entities = {
                    entity["id"]: entity
                    for entity in entities
                    if isinstance(entity, dict) and entity.get("id")
                }
            except (json.JSONDecodeError, TypeError):
                logger.warning("%s has invalid stored entity discovery", self.config.id)

    async def _stream_session(self) -> None:
        url = f"http://{self.config.hostname}/events"
        timeout = httpx.Timeout(
            connect=self.settings.request_timeout_seconds,
            read=None,
            write=self.settings.request_timeout_seconds,
            pool=self.settings.request_timeout_seconds,
        )
        async with self.client.stream(
            "GET", url, headers={"Accept": "text/event-stream"}, timeout=timeout
        ) as response:
            response.raise_for_status()
            if "text/event-stream" not in response.headers.get("content-type", ""):
                raise ValueError("ESPHome /events did not return text/event-stream")
            self.sse_connected = True
            self.last_error = None
            consistency_task = asyncio.create_task(self._consistency_loop())
            try:
                async for event in parse_sse(response.aiter_lines()):
                    if event.event == "state":
                        try:
                            entity = json.loads(event.data)
                        except (json.JSONDecodeError, TypeError):
                            logger.warning("%s sent malformed SSE state", self.config.id)
                            continue
                        await self._handle_entity(entity)
                    elif event.event == "ping":
                        self._handle_ping(event.data)
            finally:
                consistency_task.cancel()
                await asyncio.gather(consistency_task, return_exceptions=True)
                self.sse_connected = False

    def _handle_ping(self, data: str) -> None:
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            return
        if title := payload.get("title"):
            self.device_title = str(title)
        if comment := payload.get("comment"):
            self.model = str(comment)

    async def _handle_entity(self, entity: dict[str, Any]) -> None:
        entity_id = entity.get("id")
        if not isinstance(entity_id, str):
            return
        previous = self.entities.get(entity_id, {})
        merged = previous | entity
        self.entities[entity_id] = merged

        if metadata := metadata_for_entity(merged):
            self.metadata[metadata[0]] = metadata[1]

        metric = metric_for_entity(merged)
        value = numeric_value(merged)
        if metric is None or value is None:
            return

        self.metrics[metric] = value
        self.last_seen = datetime.now(timezone.utc)
        self.last_error = None
        if self._write_task is None or self._write_task.done():
            elapsed = time.monotonic() - self._last_write
            wait = 0.5 if self._last_write == 0 else max(
                0.0, self.settings.reading_interval_seconds - elapsed
            )
            self._write_task = asyncio.create_task(self._write_after(wait))
        self.hub.publish({"type": "sensor", "sensor": self.snapshot()})

    async def _write_after(self, delay: float) -> None:
        await asyncio.sleep(delay)
        if not self.metrics or self.last_seen is None:
            return
        entity_metadata = [
            {
                key: entity.get(key)
                for key in ("id", "name_id", "domain", "name", "uom", "entity_category")
            }
            for entity in self.entities.values()
        ]
        values = {field: self.metrics.get(field) for field in READING_FIELDS}
        with self.database.session_factory.begin() as session:
            sensor = session.get(Sensor, self.config.id)
            if sensor is None:
                sensor = Sensor(
                    id=self.config.id,
                    name=self.config.name,
                    hostname=self.config.hostname,
                )
                session.add(sensor)
            sensor.online = True
            sensor.last_seen = self.last_seen
            sensor.ip_address = self.metadata.get("ip_address")
            sensor.mac = self.metadata.get("mac")
            sensor.model = self.model
            sensor.firmware_version = self.metadata.get("firmware_version")
            sensor.esphome_version = self.metadata.get("esphome_version")
            sensor.device_title = self.device_title
            sensor.entities_json = json.dumps(entity_metadata, ensure_ascii=False)
            session.add(
                Reading(
                    sensor_id=self.config.id,
                    timestamp=self.last_seen,
                    **values,
                )
            )
        self._last_write = time.monotonic()

    async def _consistency_loop(self) -> None:
        await asyncio.sleep(2)
        while True:
            await self._poll_rest()
            await asyncio.sleep(self.settings.consistency_poll_seconds)

    async def _poll_rest(self) -> None:
        readable = [
            entity
            for entity in self.entities.values()
            if entity.get("domain") in {"sensor", "text_sensor"}
            and isinstance(entity.get("name_id"), str)
        ]
        if not readable:
            return

        async def fetch(entity: dict[str, Any]) -> None:
            domain, name = entity["name_id"].split("/", 1)
            endpoint = f"/{quote(domain, safe='')}/{quote(name, safe='')}"
            response = await self.client.get(
                f"http://{self.config.hostname}{endpoint}",
                timeout=self.settings.request_timeout_seconds,
            )
            response.raise_for_status()
            await self._handle_entity(response.json())

        results = await asyncio.gather(*(fetch(entity) for entity in readable), return_exceptions=True)
        failures = sum(isinstance(result, Exception) for result in results)
        if failures == len(results):
            raise ConnectionError("all ESPHome REST consistency requests failed")


class CollectorManager:
    def __init__(self, settings: Settings, database: Database):
        self.settings = settings
        self.database = database
        self.hub = LiveHub()
        self.runtimes: dict[str, SensorRuntime] = {}
        self._tasks: list[asyncio.Task[Any]] = []
        self._client: httpx.AsyncClient | None = None

    async def start(self, configs: list[SensorConfig]) -> None:
        self._upsert_configured_sensors(configs)
        self._client = httpx.AsyncClient(
            follow_redirects=True,
            limits=httpx.Limits(max_connections=max(40, len(configs) * 5)),
        )
        self.runtimes = {
            config.id: SensorRuntime(
                config, self.settings, self.database, self._client, self.hub
            )
            for config in configs
        }
        self._tasks.extend(
            asyncio.create_task(runtime.run(), name=f"collector-{sensor_id}")
            for sensor_id, runtime in self.runtimes.items()
        )
        self._tasks.append(asyncio.create_task(self._status_loop(), name="status-monitor"))
        self._tasks.append(asyncio.create_task(self._cleanup_loop(), name="retention-cleanup"))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        if self._client:
            await self._client.aclose()
            self._client = None

    def snapshots(self) -> list[dict[str, Any]]:
        return [runtime.snapshot() for runtime in self.runtimes.values()]

    def _upsert_configured_sensors(self, configs: list[SensorConfig]) -> None:
        with self.database.session_factory.begin() as session:
            for config in configs:
                sensor = session.get(Sensor, config.id)
                if sensor is None:
                    session.add(
                        Sensor(
                            id=config.id,
                            name=config.name,
                            hostname=config.hostname,
                            online=False,
                        )
                    )
                else:
                    sensor.name = config.name
                    sensor.hostname = config.hostname

    async def _status_loop(self) -> None:
        previous: dict[str, bool] = {}
        while True:
            for sensor_id, runtime in self.runtimes.items():
                online = runtime.online
                if previous.get(sensor_id) != online:
                    with self.database.session_factory.begin() as session:
                        sensor = session.get(Sensor, sensor_id)
                        if sensor:
                            sensor.online = online
                    self.hub.publish({"type": "sensor", "sensor": runtime.snapshot()})
                    previous[sensor_id] = online
            await asyncio.sleep(5)

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(3600)
            deleted = self.database.cleanup(self.settings.retention_days)
            if deleted:
                logger.info("Retention cleanup removed %d readings", deleted)
