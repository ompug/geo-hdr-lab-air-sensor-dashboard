# Observed ESPHome HTTP API

This document records live inspection performed on August 25, 2026. It is not
based on guessed endpoint names.

## Web application

`GET http://<hostname>/` returned HTTP 200 and:

```html
<!DOCTYPE html><html><head><meta charset=UTF-8><link rel=icon href=data:></head>
<body><esp-app></esp-app><script src="https://oi.esphome.io/v3/www.js"></script>
</body></html>
```

The installed firmware therefore uses ESPHome Web Server v3.

## Server-Sent Events

`GET http://<hostname>/events` with `Accept: text/event-stream` returned HTTP
200 and `Content-Type: text/event-stream`. The stream sends an initial state
event for every entity, then updated state events, pings, and firmware logs.

Observed frames:

```text
event: ping
data: {"title":"Apollo AIR-1 3e2468","comment":"Apollo AIR-1","ota":true,...}

event: state
data: {"name_id":"sensor/CO2","id":"sensor-co2","domain":"sensor",
       "name":"CO2","value":366,"state":"366 ppm","uom":"ppm"}
```

The collector treats only numeric `sensor` state values as valid telemetry.
Ping traffic, DNS resolution, and an open HTTP socket do not mark a device
online.

## REST

Readable entities are available at:

```text
GET /<domain>/<URL-encoded entity name from name_id>
```

Confirmed examples:

```text
GET /sensor/co2
GET /sensor/sen55_voc
GET /sensor/pm__2_5__m_weight_concentration
GET /text_sensor/ip_address
```

A response has the current value:

```json
{"name_id":"sensor/CO2","id":"sensor-co2","value":361,"state":"361 ppm"}
```

Entity discovery comes from the initial SSE state burst. Those discovered
`name_id` values are persisted, so REST can provide initial/recovery values
after a restart even while SSE is unavailable. While SSE is connected, REST
is used as a low-frequency consistency check.

## Entities observed on Sensor 07

Useful values exposed by this firmware include:

- CO2
- PM less-than 1, 2.5, 4, and 10 micrometer weight concentrations
- SEN55 VOC and NOx indexes
- SEN55 temperature and humidity
- DPS310 pressure
- RSSI and ESP temperature
- NowCast AQI
- particulate size-bin concentrations
- carbon monoxide, methane, ethanol, hydrogen, ammonia, and nitrogen dioxide
  entities (these returned `null`/`NA` during inspection and are not stored as
  invented values)
- IP address, ESPHome version, and Apollo firmware version

No MAC address entity was observed on Sensor 07. The database keeps the field
nullable and the dashboard reports it as not exposed.

## Live fleet result during development

The concurrent diagnostic and a sequential retry were both run from the
Windows development machine:

- Sensors 04, 07, and 08: DNS, HTTP, REST, SSE, and numeric telemetry passed.
- Sensors 01, 02, 03, 05, and 09: DNS resolved, but TCP/HTTP port 80 timed out
  after 15 seconds.
- Sensor 06: DNS lookup failed for the configured authoritative hostname.

This was a **3/9 operational** result at that time. The application correctly
reported three online and six offline; it did not convert DNS success into an
online state. Run `python scripts/test_sensors.py` from the target Fedora
network to obtain the current result.
