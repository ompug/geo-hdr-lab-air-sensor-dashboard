# Production deployment and operations

## Layout

- Application and virtual environment: `/opt/air-sensors`
- Sensor inventory: `/etc/air-sensors/sensors.yaml`
- Service environment: `/etc/air-sensors/air-sensors.env`
- Persistent SQLite database: `/var/lib/air-sensors/air-sensors.db`
- systemd unit: `/etc/systemd/system/air-sensors.service`

The service runs as the dedicated non-root `air-sensors` user. systemd applies
filesystem protections, restarts after failure, starts after the network is
online, and sends logs to journald.

## Service operations

```bash
sudo systemctl enable --now air-sensors
sudo systemctl status air-sensors
sudo systemctl restart air-sensors
sudo journalctl -u air-sensors -f
sudo journalctl -u air-sensors --since today
```

Health:

```bash
curl http://127.0.0.1:8000/api/health
```

`application` and `database` health are separate from `sensors_online` and
`sensors_offline`. A healthy application can correctly report unavailable
sensors.

## Network boundaries

The Fedora collector makes outbound/internal HTTP connections to sensor port
80. Sensor addresses should remain internal and must not be exposed to the
public Internet.

The dashboard listens on port 8000 by default. If it should be available to
other machines on an approved internal subnet:

```bash
sudo firewall-cmd --permanent --add-port=8000/tcp
sudo firewall-cmd --reload
```

Public Internet publication, TLS termination, authentication, and any reverse
proxy are intentionally separate deployment decisions. They are not needed
for sensor collection and should not make sensors publicly reachable.

## Data lifecycle

All timestamps are UTC. The collector stores at most one current snapshot per
sensor per `AIR_SENSORS_READING_INTERVAL` seconds. SSE updates still refresh
the live dashboard immediately.

`AIR_SENSORS_RETENTION_DAYS` controls hourly cleanup. A value of zero retains
history indefinitely.

Back up SQLite while the service is stopped:

```bash
sudo systemctl stop air-sensors
sudo cp /var/lib/air-sensors/air-sensors.db /path/to/backup/
sudo systemctl start air-sensors
```

## Offline behavior

A configured sensor is not online by definition. It becomes online only after
a valid numeric telemetry value arrives over SSE or REST. It becomes offline
after `AIR_SENSORS_STALE_AFTER` seconds without valid telemetry. DNS success,
SSE pings, and HTTP UI availability alone are insufficient.

Each sensor reconnects independently with bounded backoff. Discovered entities
are persisted so REST recovery remains possible if a later SSE connection is
temporarily unavailable.

## Troubleshooting

1. Run `scripts/test_sensors.py` as the service user.
2. Check `/api/health`.
3. Review `journalctl -u air-sensors`.
4. Verify DNS with `getent hosts <sensor-hostname>`.
5. Verify the actual web API with `curl -v http://<sensor-hostname>/` and
   `curl -N http://<sensor-hostname>/events`.

Do not troubleshoot this service through TCP 6053, Home Assistant, MQTT, or
mDNS; none are part of the data path.
