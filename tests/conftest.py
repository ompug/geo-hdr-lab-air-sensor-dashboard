from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        sensors_file=tmp_path / "sensors.yaml",
        database_path=tmp_path / "test.db",
        host="127.0.0.1",
        port=8000,
        stale_after_seconds=30,
        consistency_poll_seconds=60,
        reading_interval_seconds=0.01,
        retention_days=30,
        request_timeout_seconds=1,
        sse_reconnect_max_seconds=1,
        collector_enabled=False,
    )
