# kp9000-exporter

🇬🇧 **English** | [🇷🇺 Русский](README.ru.md)

Prometheus exporter for KeepLink KP-9000-6XHML-X2 switches — cheap web-managed
Realtek-based 2.5G/10G switches with the `login.cgi` / `port.cgi` firmware
(Hasivo and similar rebrands most likely work too).

These switches expose **HTTP only**: the firmware has no SNMP, no telnet, no SSH
(verified on V100.9.4 and V1.6), so the usual `snmp_exporter` route is off the
table. This exporter logs into the web UI and parses three pages — `info.cgi`,
`port.cgi`, `port.cgi?page=stats`.

Several switches are polled by a single process (`SWITCH_TARGETS`); every metric
carries a `switch` label. Pure Python standard library — no dependencies, the
script runs on a bare `python:3.12-alpine` with a single bind mount.

## Metrics

| Metric | Type | Description |
|---|---|---|
| `kp9000_up` | gauge | web UI scrape succeeded |
| `kp9000_scrape_duration_seconds` | gauge | scrape duration |
| `kp9000_device_info` | gauge | model, MAC, firmware/hardware versions in labels |
| `kp9000_port_enabled{port}` | gauge | port administratively enabled |
| `kp9000_port_link_up{port}` | gauge | link is up |
| `kp9000_port_speed_mbps{port}` | gauge | negotiated speed, Mbit/s (0 = link down) |
| `kp9000_port_flow_control{port}` | gauge | flow control active |
| `kp9000_port_{tx,rx}_{good,bad}_packets_total{port}` | counter | packet counters |

The switch counters are 32-bit and wrap around ~4.29 billion packets —
`rate()` / `increase()` handle the wrap as an ordinary counter reset, just keep
the scrape interval reasonably short (30–60 s).

The firmware exposes no byte counters and no SFP DDM data (temperature, optical
power, …) — neither via the web UI nor any other channel, so there is nothing
to export beyond the above.

## Configuration (env)

| Variable | Default | |
|---|---|---|
| `SWITCH_TARGETS` | `192.168.0.3` | comma-separated switch addresses (host or `http://…`) |
| `SWITCH_USER` | `admin` | login |
| `SWITCH_PASS` | `admin` | password |
| `LISTEN_PORT` | `9835` | `/metrics` port |
| `SWITCH_TIMEOUT` | `5` | HTTP timeout towards the switch, seconds |

## Running

```bash
docker compose up -d
curl http://localhost:9835/metrics
```

Or with the prebuilt image:

```bash
docker run -d --name kp9000-exporter \
  -e SWITCH_TARGETS=192.168.0.3,192.168.0.4 \
  -p 9835:9835 \
  ghcr.io/nd4y/kp9000-exporter:latest
```

`/healthz` is a cheap liveness endpoint that does not touch the switches — point
container healthchecks there, not at `/metrics`.

## Quirks worth knowing

- The firmware's session is tied to the client IP and expires quickly, so the
  exporter re-logins on every scrape. Side effect: an admin session opened in a
  browser from another IP may occasionally get logged out — the firmware keeps
  a single active session.
- Authentication is `admin=md5(username+password)` in a cookie plus a POST to
  `login.cgi`; the password crosses the network as an unsalted MD5 hash and the
  switch has no HTTPS. The exporter makes nothing worse — the stock web UI
  works exactly the same way.
- Firmware V1.6 emits malformed HTML (`</td align="center">`); the parser is
  deliberately tolerant of it.
