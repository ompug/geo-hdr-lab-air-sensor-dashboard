from __future__ import annotations

import pytest

from app.normalize import metadata_for_entity, metric_for_entity, numeric_value
from app.sse import parse_sse


@pytest.mark.parametrize(
    ("name", "metric"),
    [
        ("CO2", "co2"),
        ("PM <1µm Weight concentration", "pm1_0"),
        ("PM <2.5µm Weight concentration", "pm2_5"),
        ("PM <4µm Weight concentration", "pm4_0"),
        ("PM <10µm Weight concentration", "pm10"),
        ("SEN55 VOC", "voc"),
        ("SEN55 NOX", "nox"),
        ("SEN55 Temperature", "temperature"),
        ("SEN55 Humidity", "humidity"),
        ("DPS310 Pressure", "pressure"),
        ("RSSI", "rssi"),
    ],
)
def test_dynamic_entity_normalization(name: str, metric: str) -> None:
    entity = {"domain": "sensor", "name": name, "value": 12.5}
    assert metric_for_entity(entity) == metric
    assert numeric_value(entity) == 12.5


def test_null_and_malformed_values_are_not_telemetry() -> None:
    assert numeric_value({"value": None}) is None
    assert numeric_value({"value": "NA"}) is None
    assert numeric_value({"value": True}) is None


def test_metadata_discovery_uses_entity_name() -> None:
    entity = {
        "domain": "text_sensor",
        "name": "ESPHome Version",
        "value": "2026.5.3",
    }
    assert metadata_for_entity(entity) == ("esphome_version", "2026.5.3")


@pytest.mark.asyncio
async def test_sse_parser_handles_frames_and_multiline_data() -> None:
    async def lines():
        for line in [
            ": keepalive",
            "event: state",
            'data: {"id":"sensor-co2",',
            'data: "value":421}',
            "",
            "event: ping",
            "data: {}",
            "",
        ]:
            yield line

    events = [event async for event in parse_sse(lines())]
    assert events[0].event == "state"
    assert events[0].data == '{"id":"sensor-co2",\n"value":421}'
    assert events[1].event == "ping"
