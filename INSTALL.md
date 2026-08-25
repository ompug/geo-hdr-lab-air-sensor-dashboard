# Installation

## Fedora prerequisites

The production host needs Python 3.11 or newer, Git, and ordinary DNS/HTTP
access to the nine internal sensor hostnames.

```bash
sudo dnf install -y git python3
git clone <repository-url>
cd dr-li-air-sensors
chmod +x install.sh
./install.sh
```

The script uses `sudo` when needed and:

1. creates the non-login `air-sensors` system user;
2. copies the application to `/opt/air-sensors`;
3. creates `/opt/air-sensors/.venv` and installs pinned project requirements;
4. creates `/etc/air-sensors` configuration without overwriting local changes;
5. creates the persistent, service-owned `/var/lib/air-sensors` directory;
6. installs and starts the systemd service;
7. checks `http://127.0.0.1:8000/api/health`;
8. runs the live nine-sensor diagnostic.

One unavailable sensor produces a diagnostic warning but does not undo a
working service installation.

## Configure

Edit sensor inventory:

```bash
sudoedit /etc/air-sensors/sensors.yaml
```

Edit runtime behavior:

```bash
sudoedit /etc/air-sensors/air-sensors.env
```

Important values include the stale timeout, REST consistency interval,
database snapshot interval, and retention period. Set
`AIR_SENSORS_RETENTION_DAYS=0` to disable cleanup.

Apply changes:

```bash
sudo systemctl restart air-sensors
```

## Verify

```bash
sudo systemctl enable --now air-sensors
sudo systemctl status air-sensors
sudo journalctl -u air-sensors -f
curl http://127.0.0.1:8000/api/health
```

Run the sensor test independently:

```bash
sudo -u air-sensors \
  /opt/air-sensors/.venv/bin/python \
  /opt/air-sensors/scripts/test_sensors.py \
  --config /etc/air-sensors/sensors.yaml
```

## Updating

Pull the repository and rerun the idempotent installer:

```bash
git pull --ff-only
./install.sh
```

The installer preserves `/etc/air-sensors/sensors.yaml`,
`/etc/air-sensors/air-sensors.env`, and the SQLite database.

## Windows development

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python scripts/test_sensors.py
python -m app
```

Open <http://localhost:8000/>.
