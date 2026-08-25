from __future__ import annotations

import re
import unicodedata
from typing import Any


def normalized_name(entity: dict[str, Any]) -> str:
    text = str(entity.get("name") or entity.get("name_id") or "")
    text = unicodedata.normalize("NFKD", text).lower().replace("µ", "u")
    return re.sub(r"[^a-z0-9.<]+", " ", text).strip()


def metric_for_entity(entity: dict[str, Any]) -> str | None:
    if entity.get("domain") != "sensor":
        return None
    name = normalized_name(entity)

    exact_or_contains = (
        ("esp temperature", "esp_temperature"),
        ("nowcast aqi", "nowcast_aqi"),
        ("carbon monoxide", "carbon_monoxide"),
        ("nitrogen dioxide", "nitrogen_dioxide"),
        ("methane", "methane"),
        ("ethanol", "ethanol"),
        ("hydrogen", "hydrogen"),
        ("ammonia", "ammonia"),
        ("rssi", "rssi"),
        ("pressure", "pressure"),
        ("humidity", "humidity"),
        ("temperature", "temperature"),
        ("nox", "nox"),
        ("voc", "voc"),
        ("co2", "co2"),
    )
    for token, metric in exact_or_contains:
        if token in name:
            return metric

    if "pm 0.3 to 1" in name:
        return "pm_0_3_to_1"
    if "pm 1 to 2.5" in name:
        return "pm_1_to_2_5"
    if "pm 2.5 to 4" in name:
        return "pm_2_5_to_4"
    if "pm 4 to 10" in name:
        return "pm_4_to_10"
    if "weight concentration" in name:
        if "<2.5" in name:
            return "pm2_5"
        if "<10" in name:
            return "pm10"
        if "<4" in name:
            return "pm4_0"
        if "<1" in name:
            return "pm1_0"
    return None


def metadata_for_entity(entity: dict[str, Any]) -> tuple[str, str] | None:
    if entity.get("domain") != "text_sensor":
        return None
    name = normalized_name(entity)
    value = entity.get("value")
    if not isinstance(value, str) or not value:
        return None
    if "ip address" in name:
        return "ip_address", value
    if "apollo firmware version" in name:
        return "firmware_version", value
    if "esphome version" in name:
        return "esphome_version", value
    if "mac" in name:
        return "mac", value
    return None


def numeric_value(entity: dict[str, Any]) -> float | None:
    value = entity.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
