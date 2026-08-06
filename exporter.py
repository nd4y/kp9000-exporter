#!/usr/bin/env python3
"""Prometheus exporter for KeepLink KP-9000-6XHML-X2 (and similar Realtek-based
web-managed switches with login.cgi / port.cgi firmware).

The switches expose only an HTTP UI: port settings (link state, negotiated
speed) and packet counters. No SNMP, no SFP DDM data in this firmware.

Auth: the UI expects cookie admin=md5(username+password) and a POST to
login.cgi with the same hash; the session is then tied to the client IP and
expires after idle, so we re-login on every scrape (cheap) and retry once if
a page comes back as a redirect to login.cgi.

Multi-target: SWITCH_TARGETS is a comma-separated list of hosts (or full
http:// URLs); every metric carries a `switch` label. Older firmware (V1.6)
closes cells with malformed tags like `</td align="center">`, hence the
tolerant regexes.

Stdlib only — no third-party dependencies, so it runs on a bare python image
with the script bind-mounted read-only.
"""

import hashlib
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_targets_env = os.environ.get("SWITCH_TARGETS", "192.168.0.3")
TARGETS = [t.strip() for t in _targets_env.split(",") if t.strip()]
SWITCH_USER = os.environ.get("SWITCH_USER", "admin")
SWITCH_PASS = os.environ.get("SWITCH_PASS", "admin")
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "9835"))
TIMEOUT = float(os.environ.get("SWITCH_TIMEOUT", "5"))

AUTH_HASH = hashlib.md5((SWITCH_USER + SWITCH_PASS).encode()).hexdigest()

SPEED_MBPS = {
    "10Half": 10, "10Full": 10,
    "100Half": 100, "100Full": 100,
    "1000Full": 1000, "2500Full": 2500,
    "10GFull": 10000,
}

ROW_RE = re.compile(r"<tr>(.*?)</tr\s*>", re.DOTALL)
CELL_RE = re.compile(r"<td[^>]*>(.*?)</td[^>]*>", re.DOTALL)
INFO_RE = re.compile(r"<th[^>]*>(.*?)</th[^>]*>\s*<td[^>]*>(.*?)</td[^>]*>", re.DOTALL)


class SwitchClient:
    def __init__(self, target):
        base = target if target.startswith("http") else f"http://{target}"
        self.base = base.rstrip("/")
        self.label = re.sub(r"^https?://", "", self.base)

    def _request(self, path, data=None):
        req = urllib.request.Request(
            f"{self.base}/{path}",
            data=urllib.parse.urlencode(data).encode() if data else None,
            headers={"Cookie": f"admin={AUTH_HASH}"},
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read().decode(errors="replace")

    def login(self):
        self._request("login.cgi", {
            "username": SWITCH_USER,
            "password": SWITCH_PASS,
            "language": "EN",
            "Response": AUTH_HASH,
        })

    def get(self, path):
        text = self._request(path)
        if "login.cgi" in text:  # session expired -> re-login and retry once
            self.login()
            text = self._request(path)
        return text


def strip_tags(html):
    return re.sub(r"<[^>]+>", "", html).strip()


def cells(row_html):
    return [strip_tags(c) for c in CELL_RE.findall(row_html)]


def parse_port_settings(html):
    """Last table of port.cgi: Port | State | Config | Actual | Config | Actual."""
    ports = {}
    for row in ROW_RE.findall(html):
        c = cells(row)
        if len(c) == 6 and c[0].startswith("Port"):
            ports[c[0]] = {"state": c[1], "actual_speed": c[3], "flow": c[5]}
    return ports


def parse_port_stats(html):
    """port.cgi?page=stats: Port | State | Link | TxGood | TxBad | RxGood | RxBad."""
    ports = {}
    for row in ROW_RE.findall(html):
        c = cells(row)
        if len(c) == 7 and c[0].startswith("Port"):
            ports[c[0]] = {
                "link": c[2],
                "tx_good": int(c[3]), "tx_bad": int(c[4]),
                "rx_good": int(c[5]), "rx_bad": int(c[6]),
            }
    return ports


def parse_info(html):
    info = {}
    for k, v in INFO_RE.findall(html):
        info[strip_tags(k).lower().replace(" ", "_")] = strip_tags(v)
    return info


def esc(v):
    return v.replace("\\", "\\\\").replace('"', '\\"')


class Sample:
    """Accumulates exposition-format lines grouped per metric family."""

    def __init__(self):
        self.families = {}  # name -> (type, help, [lines])

    def add(self, name, mtype, help_text, labels, value):
        fam = self.families.setdefault(name, (mtype, help_text, []))
        label_str = ",".join(f'{k}="{esc(str(v))}"' for k, v in labels.items())
        fam[2].append(f"{name}{{{label_str}}} {value}")

    def render(self):
        out = []
        for name, (mtype, help_text, lines) in self.families.items():
            out.append(f"# HELP {name} {help_text}")
            out.append(f"# TYPE {name} {mtype}")
            out.extend(lines)
        return "\n".join(out) + "\n"


CLIENTS = [SwitchClient(t) for t in TARGETS]
SCRAPE_LOCK = threading.Lock()


def scrape():
    s = Sample()
    for client in CLIENTS:
        sw = client.label
        start = time.monotonic()
        try:
            client.login()
            info = parse_info(client.get("info.cgi"))
            settings = parse_port_settings(client.get("port.cgi"))
            stats = parse_port_stats(client.get("port.cgi?page=stats"))
        except Exception as e:
            print(f"scrape of {sw} failed: {e}", file=sys.stderr, flush=True)
            s.add("kp9000_up", "gauge", "Switch web UI scrape succeeded", {"switch": sw}, 0)
            s.add("kp9000_scrape_duration_seconds", "gauge", "Time spent scraping the switch",
                  {"switch": sw}, round(time.monotonic() - start, 3))
            continue

        s.add("kp9000_up", "gauge", "Switch web UI scrape succeeded", {"switch": sw}, 1)
        s.add("kp9000_scrape_duration_seconds", "gauge", "Time spent scraping the switch",
              {"switch": sw}, round(time.monotonic() - start, 3))
        s.add("kp9000_device_info", "gauge", "Switch identity", {
            "switch": sw,
            "model": info.get("device_model", ""),
            "mac": info.get("mac_address", ""),
            "firmware": info.get("firmware_version", ""),
            "firmware_date": info.get("firmware_date", ""),
            "hardware": info.get("hardware_version", ""),
        }, 1)

        for port, p in settings.items():
            lbl = {"switch": sw, "port": port.replace("Port ", "")}
            s.add("kp9000_port_enabled", "gauge", "Port administratively enabled",
                  lbl, 1 if p["state"] == "Enable" else 0)
            s.add("kp9000_port_speed_mbps", "gauge",
                  "Negotiated port speed in Mbit/s (0 = link down)",
                  lbl, SPEED_MBPS.get(p["actual_speed"], 0))
            s.add("kp9000_port_flow_control", "gauge", "Flow control active",
                  lbl, 0 if p["flow"] == "Off" else 1)
        for port, p in stats.items():
            lbl = {"switch": sw, "port": port.replace("Port ", "")}
            s.add("kp9000_port_link_up", "gauge", "Port link is up",
                  lbl, 1 if p["link"] == "Link Up" else 0)
            s.add("kp9000_port_tx_good_packets_total", "counter",
                  "Transmitted good packets (32-bit counter)", lbl, p["tx_good"])
            s.add("kp9000_port_tx_bad_packets_total", "counter",
                  "Transmitted bad packets (32-bit counter)", lbl, p["tx_bad"])
            s.add("kp9000_port_rx_good_packets_total", "counter",
                  "Received good packets (32-bit counter)", lbl, p["rx_good"])
            s.add("kp9000_port_rx_bad_packets_total", "counter",
                  "Received bad packets (32-bit counter)", lbl, p["rx_bad"])
    return s.render()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok\n")
            return
        if self.path != "/metrics":
            self.send_response(404)
            self.end_headers()
            return
        with SCRAPE_LOCK:
            body = scrape().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass  # keep container logs to actual errors


def main():
    server = ThreadingHTTPServer(("", LISTEN_PORT), Handler)
    print(f"kp9000-exporter listening on :{LISTEN_PORT}, targets: {', '.join(TARGETS)}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
