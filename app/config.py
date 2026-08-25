from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _path_from_env(name: str, default: Path) -> Path:
    value = os.getenv(name)
    return Path(value).expanduser() if value else default


@dataclass(frozen=True)
class SensorConfig:
    id: str
    name: str
    hostname: str


@dataclass(frozen=True)
class Settings:
    sensors_file: Path
    database_path: Path
    host: str
    port: int
    stale_after_seconds: float
    consistency_poll_seconds: float
    reading_interval_seconds: float
    retention_days: int
    request_timeout_seconds: float
    sse_reconnect_max_seconds: float
    collector_enabled: bool

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path.as_posix()}"


def load_settings() -> Settings:
    data_dir = _path_from_env("AIR_SENSORS_DATA_DIR", PROJECT_ROOT / "data")
    return Settings(
        sensors_file=_path_from_env(
            "AIR_SENSORS_CONFIG", PROJECT_ROOT / "config" / "sensors.yaml"
        ),
        database_path=_path_from_env(
            "AIR_SENSORS_DATABASE", data_dir / "air-sensors.db"
        ),
        host=os.getenv("AIR_SENSORS_HOST", "0.0.0.0"),
        port=int(os.getenv("AIR_SENSORS_PORT", "8000")),
        stale_after_seconds=float(os.getenv("AIR_SENSORS_STALE_AFTER", "90")),
        consistency_poll_seconds=float(
            os.getenv("AIR_SENSORS_CONSISTENCY_POLL", "60")
        ),
        reading_interval_seconds=float(
            os.getenv("AIR_SENSORS_READING_INTERVAL", "30")
        ),
        retention_days=int(os.getenv("AIR_SENSORS_RETENTION_DAYS", "365")),
        request_timeout_seconds=float(os.getenv("AIR_SENSORS_HTTP_TIMEOUT", "10")),
        sse_reconnect_max_seconds=float(
            os.getenv("AIR_SENSORS_RECONNECT_MAX", "60")
        ),
        collector_enabled=os.getenv("AIR_SENSORS_COLLECTOR_ENABLED", "true").lower()
        not in {"0", "false", "no"},
    )


def load_sensor_configs(path: Path) -> list[SensorConfig]:
    with path.open(encoding="utf-8") as handle:
        payload: dict[str, Any] = yaml.safe_load(handle) or {}
    sensors = [SensorConfig(**item) for item in payload.get("sensors", [])]
    if not sensors:
        raise ValueError(f"No sensors configured in {path}")
    ids = [sensor.id for sensor in sensors]
    if len(ids) != len(set(ids)):
        raise ValueError(f"Duplicate sensor IDs in {path}")
    return sensors
