#!/usr/bin/env python3
"""PineLink discovery: find out what this camera actually speaks.

The camera is an ACCESS POINT, not a client. Nothing on the house LAN can
see it; something has to join `H88_<mac>` and ask from inside. The DGX has
two radios, so the spare one (`wlx…`, the USB adapter) can hold the camera
while `wlP9s9` keeps the station's 10.89.1.246 - that is the whole reason
the relay lives here and not on the tablet.

This does not guess. The Viidure family covers several chipsets (Novatek,
Anyka, Ingenic) and they do NOT share a control protocol: some serve RTSP
on 554, some an HTTP CGI on 80 or 8080, some a Novatek-style command port
on 3333. So this walks the plausible doors, records exactly what answered,
and writes it down. Whatever it finds is what PineLink is built against -
not what the manual implies.

    sudo python3 pinelink-probe.py --join        # join the AP, then probe
    sudo python3 pinelink-probe.py --probe-only  # already joined

Refuses to touch the radio holding the station. That interface is the only
way anything reaches the broadcast, and a probe is never worth it.
"""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

STATION_IF = "wlP9s9"          # holds 10.89.1.246 - never touched
SPARE_IF = "wlx984827b6b478"   # the USB adapter added for this
SSID = "H88_5c8e8bddfab1"
PSK = "12345678"
OUT = Path("/tmp/pinelink-probe.json")

# Ports worth knocking on, and what a hit would mean.
PORTS = [
    (554, "RTSP - the one we want; ffmpeg can pull it directly"),
    (80, "HTTP - a CGI control surface, and often an MJPEG path"),
    (8080, "HTTP alt - same, common on Anyka"),
    (8192, "Novatek control"),
    (3333, "Novatek command port"),
    (7878, "Ambarella-style control"),
    (9000, "some Ingenic builds"),
    (23, "telnet - a busybox shell would tell us everything"),
]

# Paths to try once something answers HTTP. Recording what does NOT work
# is half the value: it is what stops the next person re-trying it.
HTTP_PATHS = [
    "/", "/index.html", "/cgi-bin/hi3510/param.cgi", "/cgi-bin/Config.cgi",
    "/app/index.html", "/?custom=1&cmd=3001", "/cgi-bin/foo.cgi",
    "/live", "/video", "/videostream.cgi", "/snapshot.cgi",
    "/onvif/device_service", "/tmp/SD0/", "/DCIM/",
]
RTSP_PATHS = [
    "/live", "/live/ch0", "/live/0", "/11", "/cam1/mpeg4",
    "/stream0", "/stream1", "/h264", "/media/stream1", "/",
]


def run(cmd: list[str], timeout: float = 30.0) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as err:  # noqa: BLE001
        return 1, str(err)


def guard() -> None:
    """The station's radio is not available for this."""
    code, out = run(["ip", "-4", "-br", "addr", "show", STATION_IF])
    if "10.89.1.246" not in out:
        print("REFUSING: %s does not hold 10.89.1.246 - the layout is not "
              "what this script was written for, and guessing here takes "
              "the station off the air." % STATION_IF)
        sys.exit(2)


def join() -> bool:
    run(["nmcli", "device", "set", SPARE_IF, "managed", "yes"])
    run(["ip", "link", "set", SPARE_IF, "up"])
    time.sleep(2)
    run(["nmcli", "device", "wifi", "rescan", "ifname", SPARE_IF], 45)
    time.sleep(6)
    code, out = run(["nmcli", "-t", "-f", "SSID", "device", "wifi", "list",
                     "ifname", SPARE_IF])
    if SSID not in out:
        print("The camera's network (%s) is NOT being broadcast." % SSID)
        print("Nothing here can proceed until it is: turn the camera's "
              "Wi-Fi on, and disconnect the phone - these APs usually "
              "take one client at a time.")
        print("\nWhat the radio CAN see right now:")
        for line in sorted(set(out.splitlines()))[:24]:
            if line.strip():
                print("   " + line)
        return False
    print("Found %s - joining on %s" % (SSID, SPARE_IF))
    code, out = run(["nmcli", "device", "wifi", "connect", SSID,
                     "password", PSK, "ifname", SPARE_IF], 60)
    print(out.strip()[:300])
    return code == 0


def gateway() -> str:
    """The camera itself. The phone was handed 192.168.1.33, so the AP is
    a /24 there and the camera is almost certainly .1 - but it is asked,
    not assumed."""
    code, out = run(["ip", "route", "show", "dev", SPARE_IF])
    for line in out.splitlines():
        if line.startswith("default via "):
            return line.split()[2]
    for line in out.splitlines():
        if " src " in line:                      # 192.168.1.0/24 … src …
            return line.split("/")[0].rsplit(".", 1)[0] + ".1"
    return "192.168.1.1"


def knock(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:  # noqa: BLE001
        return False


def http_try(host: str, port: int, path: str) -> str:
    code, out = run(["curl", "-s", "-m", "6", "-i",
                     "http://%s:%d%s" % (host, port, path)], 12)
    head = out.split("\r\n\r\n", 1)[0][:400]
    return head.replace("\n", " | ")[:300]


def rtsp_try(url: str) -> str:
    code, out = run(["ffprobe", "-v", "error", "-rtsp_transport", "tcp",
                     "-show_streams", "-of", "json", "-timeout", "5000000",
                     url], 20)
    if code == 0 and '"codec_type"' in out:
        try:
            js = json.loads(out)
            bits = []
            for s in js.get("streams", []):
                bits.append("%s %s %sx%s" % (
                    s.get("codec_type"), s.get("codec_name"),
                    s.get("width"), s.get("height")))
            return "OPEN: " + "; ".join(bits)
        except Exception:  # noqa: BLE001
            return "OPEN (unparsed)"
    return ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--join", action="store_true")
    ap.add_argument("--probe-only", action="store_true")
    args = ap.parse_args()

    guard()
    if args.join and not join():
        sys.exit(1)

    host = gateway()
    found: dict[str, object] = {"at": time.time(), "host": host,
                                "ports": {}, "http": {}, "rtsp": {}}
    print("\n=== the camera answers at %s ===" % host)

    open_ports = []
    for port, why in PORTS:
        up = knock(host, port)
        found["ports"][str(port)] = up
        print("  %-6d %-8s %s" % (port, "OPEN" if up else "shut", why))
        if up:
            open_ports.append(port)

    for port in open_ports:
        if port in (80, 8080):
            print("\n=== HTTP on %d ===" % port)
            for path in HTTP_PATHS:
                head = http_try(host, port, path)
                if head and "404" not in head.split("|")[0]:
                    found["http"]["%d%s" % (port, path)] = head
                    print("  %-34s %s" % (path, head[:120]))
        if port == 554:
            print("\n=== RTSP ===")
            for path in RTSP_PATHS:
                url = "rtsp://%s:554%s" % (host, path)
                got = rtsp_try(url)
                if got:
                    found["rtsp"][url] = got
                    print("  %-28s %s" % (path, got))

    OUT.write_text(json.dumps(found, indent=2))
    print("\nwritten to %s" % OUT)
    if not found["rtsp"] and not found["http"]:
        print("Nothing answered. Either the join did not take, or this "
              "camera only talks to its own app over a protocol none of "
              "these doors match - in which case the next step is a "
              "packet capture with the phone driving it.")


if __name__ == "__main__":
    main()
