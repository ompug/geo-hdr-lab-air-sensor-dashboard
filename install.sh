#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/opt/air-sensors
CONFIG_DIR=/etc/air-sensors
DATA_DIR=/var/lib/air-sensors
SERVICE=air-sensors
SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

run_root() {
  if [[ ${EUID} -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

run_as_service() {
  if [[ ${EUID} -eq 0 ]]; then
    runuser -u air-sensors -- "$@"
  else
    sudo -u air-sensors "$@"
  fi
}

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3.11 or newer is required. On Fedora: sudo dnf install python3"
  exit 1
fi

python3 - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit(f"Python 3.11+ required; found {sys.version.split()[0]}")
PY

if [[ ${EUID} -ne 0 ]] && ! command -v sudo >/dev/null 2>&1; then
  echo "Run this installer as root or install sudo."
  exit 1
fi

echo "Installing Apollo AIR-1 service into ${APP_DIR}"
if ! id -u air-sensors >/dev/null 2>&1; then
  run_root useradd --system --home-dir "$DATA_DIR" --shell /sbin/nologin air-sensors
fi

run_root install -d -m 0755 "$APP_DIR" "$CONFIG_DIR"
run_root install -d -o air-sensors -g air-sensors -m 0750 "$DATA_DIR"
run_root cp -a "$SOURCE_DIR/app" "$SOURCE_DIR/scripts" "$APP_DIR/"
run_root install -m 0644 "$SOURCE_DIR/requirements.txt" "$APP_DIR/requirements.txt"
run_root python3 -m venv "$APP_DIR/.venv"
run_root "$APP_DIR/.venv/bin/python" -m pip install --upgrade pip
run_root "$APP_DIR/.venv/bin/python" -m pip install -r "$APP_DIR/requirements.txt"

if [[ ! -f "$CONFIG_DIR/sensors.yaml" ]]; then
  run_root install -m 0644 "$SOURCE_DIR/config/sensors.yaml" "$CONFIG_DIR/sensors.yaml"
  echo "Created $CONFIG_DIR/sensors.yaml"
else
  echo "Preserving existing $CONFIG_DIR/sensors.yaml"
fi

if [[ ! -f "$CONFIG_DIR/air-sensors.env" ]]; then
  run_root install -m 0640 "$SOURCE_DIR/.env.example" "$CONFIG_DIR/air-sensors.env"
  echo "Created $CONFIG_DIR/air-sensors.env"
else
  echo "Preserving existing $CONFIG_DIR/air-sensors.env"
fi

run_root install -m 0644 \
  "$SOURCE_DIR/systemd/air-sensors.service" \
  "/etc/systemd/system/air-sensors.service"
run_root systemctl daemon-reload
run_root systemctl enable --now "$SERVICE"

echo "Waiting for the local health endpoint..."
healthy=false
for _ in {1..20}; do
  if "$APP_DIR/.venv/bin/python" - <<'PY' >/dev/null 2>&1
import json
from urllib.request import urlopen
with urlopen("http://127.0.0.1:8000/api/health", timeout=2) as response:
    assert json.load(response)["application"] == "healthy"
PY
  then
    healthy=true
    break
  fi
  sleep 1
done

if [[ "$healthy" != true ]]; then
  echo "Service did not pass its startup health check."
  run_root systemctl status "$SERVICE" --no-pager || true
  exit 1
fi

echo "Application health check passed."
echo "Running the live nine-sensor diagnostic (a failed sensor does not undo installation)..."
if ! run_as_service \
  "$APP_DIR/.venv/bin/python" "$APP_DIR/scripts/test_sensors.py" \
  --config "$CONFIG_DIR/sensors.yaml"; then
  echo "WARNING: One or more sensors failed live diagnostics. Check network access and journald."
fi

echo
echo "Installation complete: http://$(hostname -f):8000/"
echo "Status: sudo systemctl status air-sensors"
echo "Logs:   sudo journalctl -u air-sensors -f"
