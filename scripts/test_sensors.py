#!/usr/bin/env python3
"""Live connectivity and ESPHome Web API diagnostic for all configured sensors."""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Result:
    sensor_id: str
    name: str
    hostname: str
    dns: bool = False
    addresses: list[str] = field(default_factory=list)
    http: bool = False
    sse: bool = False
    rest: bool = False
    entities: list[dict[str, Any]] = field(default_factory=list)
    telemetry_count: int = 0
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.dns and self.http and self.sse and self.rest and self.telemetry_count > 0


def load_sensors(path: Path) -> list[dict[str, str]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    sensors = data.get("sensors", [])
    if not sensors:
        raise ValueError(f"No sensors configured in {path}")
    return sensors


async def resolve(hostname: str) -> list[str]:
    loop = asyncio.get_running_loop()
    records = await loop.getaddrinfo(hostname, 80, type=socket.SOCK_STREAM)
    return sorted({record[4][0] for record in records})


async def read_initial_sse(
    client: httpx.AsyncClient, hostname: str, seconds: float
) -> list[dict[str, Any]]:
    entities: dict[str, dict[str, Any]] = {}
    async with client.stream(
        "GET",
        f"http://{hostname}/events",
        headers={"Accept": "text/event-stream"},
        timeout=httpx.Timeout(connect=5, read=None, write=5, pool=5),
    ) as response:
        response.raise_for_status()
        if "text/event-stream" not in response.headers.get("content-type", ""):
            raise ValueError("response is not text/event-stream")

        event_type: str | None = None
        try:
            async with asyncio.timeout(seconds):
                async for line in response.aiter_lines():
                    if line.startswith("event:"):
                        event_type = line[6:].strip()
                    elif line.startswith("data:") and event_type == "state":
                        payload = json.loads(line[5:].strip())
                        entity_id = payload.get("id")
                        if entity_id:
                            entities[entity_id] = payload
                    elif not line:
                        event_type = None
        except TimeoutError:
            pass
    return list(entities.values())


async def check_sensor(
    client: httpx.AsyncClient, sensor: dict[str, str], sse_seconds: float
) -> Result:
    result = Result(sensor["id"], sensor["name"], sensor["hostname"])
    try:
        result.addresses = await resolve(result.hostname)
        result.dns = bool(result.addresses)

        root = await client.get(f"http://{result.hostname}/", timeout=8)
        root.raise_for_status()
        result.http = "<esp-app" in root.text and "esphome" in root.text.lower()
        if not result.http:
            raise ValueError("HTTP root is not an ESPHome web interface")

        result.entities = await read_initial_sse(client, result.hostname, sse_seconds)
        result.sse = bool(result.entities)
        telemetry = [
            entity
            for entity in result.entities
            if entity.get("domain") == "sensor"
            and isinstance(entity.get("value"), (int, float))
        ]
        result.telemetry_count = len(telemetry)
        if not telemetry:
            raise ValueError("SSE returned no numeric sensor telemetry")

        sample = telemetry[0]["name_id"].split("/", 1)
        endpoint = f"/{quote(sample[0])}/{quote(sample[1])}"
        rest = await client.get(f"http://{result.hostname}{endpoint}", timeout=8)
        rest.raise_for_status()
        payload = rest.json()
        result.rest = payload.get("value") is not None and payload.get("id")
        if not result.rest:
            raise ValueError(f"REST endpoint {endpoint} returned no value")
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
    return result


async def run(config: Path, sse_seconds: float) -> list[Result]:
    sensors = load_sensors(config)
    limits = httpx.Limits(max_connections=max(20, len(sensors) * 2))
    async with httpx.AsyncClient(follow_redirects=True, limits=limits) as client:
        return await asyncio.gather(
            *(check_sensor(client, sensor, sse_seconds) for sensor in sensors)
        )


def print_report(results: list[Result], as_json: bool) -> None:
    if as_json:
        print(json.dumps([result.__dict__ | {"passed": result.passed} for result in results], indent=2))
        return

    print("Apollo AIR-1 Connectivity Test")
    print("=" * 96)
    for result in results:
        number = result.sensor_id.rsplit("-", 1)[-1]
        state = "PASS" if result.passed else "FAIL"
        capabilities = " ".join(
            name
            for name, available in (
                ("DNS", result.dns),
                ("HTTP", result.http),
                ("REST", result.rest),
                ("SSE", result.sse),
            )
            if available
        )
        print(
            f"{number}  {result.hostname:<43} {state:<4} "
            f"{capabilities:<18} {result.telemetry_count:>2} telemetry entities"
        )
        if result.error:
            print(f"    {result.error}")
    passed = sum(result.passed for result in results)
    print("=" * 96)
    print(f"{passed}/{len(results)} sensors operational")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config", type=Path, default=ROOT / "config" / "sensors.yaml"
    )
    parser.add_argument("--sse-seconds", type=float, default=4.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    results = asyncio.run(run(args.config, args.sse_seconds))
    print_report(results, args.json)
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
