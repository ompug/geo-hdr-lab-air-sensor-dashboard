# Apollo AIR-1 Research Sensor Network

A self-contained HTTP/SSE collector, SQLite archive, FastAPI service, and live
research dashboard for nine Apollo AIR-1 air-quality sensors.

```text
Apollo AIR-1 sensors (HTTP :80, ESPHome REST + SSE)
                         ↓
             asynchronous collector
                         ↓
                      SQLite
                         ↓
             FastAPI + live WebSocket
                         ↓
              static browser dashboard
```

The sensors are contacted only through their configured
`*.dyn.uncc.edu` hostnames over HTTP port 80. There is no Home Assistant,
MQTT, mDNS, ESPHome Native API/TCP 6053, Nginx, or Docker requirement.

## What it does

- Maintains independent SSE connections to all nine sensors.
- Discovers actual ESPHome entities dynamically.
- Uses REST for synchronization, recovery, and periodic consistency checks.
- Normalizes real telemetry into a stable SQL schema.
- Marks a device online only after recent valid numeric telemetry.
- Reconnects with bounded backoff without allowing one device to stop others.
- Stores UTC historical readings with configurable retention.
- Serves API documentation at `/docs` and the dashboard at `/`.
- Pushes live browser updates over `/api/ws`.

Observed API behavior and the development-time fleet result are documented in
[docs/ESPHOME_HTTP_API.md](docs/ESPHOME_HTTP_API.md).

## Windows development

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python scripts/test_sensors.py
python -m app
```

Open <http://localhost:8000/>. Data is written to `data/air-sensors.db`, which
is ignored by Git. No fake readings are seeded.

Run tests:

```powershell
python -m pytest -q
```

## Fedora production

On a fresh Fedora host with Git, Python 3.11+, and network access to the
sensors:

```bash
git clone <repository-url>
cd dr-li-air-sensors
chmod +x install.sh
./install.sh
```

The installer creates a dedicated `air-sensors` user, virtual environment,
persistent data directory, configuration, systemd unit, and startup health
test. See [INSTALL.md](INSTALL.md) and [DEPLOYMENT.md](DEPLOYMENT.md).

## Configuration

Sensor inventory is in `config/sensors.yaml`. Runtime settings are environment
variables documented in `.env.example`. Fedora installation copies these to:

- `/etc/air-sensors/sensors.yaml`
- `/etc/air-sensors/air-sensors.env`
- `/var/lib/air-sensors/air-sensors.db`

## Main API routes

- `GET /api/health`
- `GET /api/sensors`
- `GET /api/sensors/{sensor_id}`
- `GET /api/sensors/{sensor_id}/readings`
- `GET /api/sensors/{sensor_id}/history`
- `GET /api/metrics`
- `WS /api/ws`
