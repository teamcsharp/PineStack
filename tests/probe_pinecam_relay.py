"""Observe an already-live tablet relay without changing either radio.

Run from the shared checkout: python tests/probe_pinecam_relay.py --seconds 660
The 11-minute default crosses the reported ten-minute dropout interval.
"""
import argparse
import json
import re
import subprocess
import time
from urllib.request import urlopen

parser = argparse.ArgumentParser()
parser.add_argument("--seconds", type=float, default=660)
parser.add_argument("--adb", help="Optional ADB executable to sample the tablet's house Wi-Fi signal")
args = parser.parse_args()
started = time.monotonic()
samples = 0
failures = []
pids = set()
max_frame_age = 0.0
next_log = 0.0
next_wifi = 0.0
home_wifi = {}
while True:
    elapsed = time.monotonic() - started
    try:
        # Fetch from the live service: SMB can cache atomically replaced JSON.
        with urlopen("http://10.89.1.246:8096/api/pinelink/state", timeout=8) as response:
            state = json.load(response)
        with urlopen("http://10.89.1.246:8096/api/pinelink/relay", timeout=8) as response:
            report = json.load(response).get("report") or {}
        age = float(state.get("frame_age", 999))
        max_frame_age = max(max_frame_age, age)
        source = state.get("source") or {}
        link = report.get("link") or {}
        relay = report.get("relay") or {}
        if args.adb and elapsed >= next_wifi:
            try:
                result = subprocess.run([args.adb, "-s", "10.89.1.154:5555", "shell", "iw", "dev", "wlan0", "link"],
                                        capture_output=True, text=True, timeout=5)
                rssi = re.search(r"signal:\s*(-?\d+) dBm", result.stdout)
                home_wifi = {"rssi_dbm": int(rssi[1])} if rssi else {"error": result.stderr.strip() or "not associated"}
            except (OSError, subprocess.TimeoutExpired) as error:
                home_wifi = {"error": str(error)}
            next_wifi = elapsed + 10
        reading = {"elapsed_s": round(elapsed, 1), "state": state.get("state"),
                   "source": source.get("use"), "joined": link.get("joined"),
                   "listening": relay.get("listening"), "frame_age_s": round(age, 2),
                   "pid": state.get("pid"), "joined_s": link.get("joined_s"),
                   "signal": link.get("signal"), "packets": relay.get("udp_packets")}
        if args.adb:
            reading["home_wifi"] = home_wifi
        healthy = (state.get("state") == "live" and source.get("use") == "tablet"
                   and link.get("joined") and relay.get("listening") and age < 5
                   and time.time() - float(report.get("at") or 0) < 20)
        if not healthy:
            failures.append(reading)
        if state.get("pid"):
            pids.add(state["pid"])
        samples += 1
        if elapsed >= next_log or not healthy:
            print(json.dumps(reading), flush=True)
            next_log = elapsed + 30
    except (OSError, ValueError) as error:
        failures.append({"elapsed_s": round(elapsed, 1), "error": str(error)})
        print(json.dumps(failures[-1]), flush=True)
    if elapsed >= args.seconds:
        break
    time.sleep(min(2, args.seconds - elapsed))
summary = {"seconds": round(time.monotonic() - started, 1), "samples": samples,
           "unhealthy_samples": len(failures), "stream_pids": sorted(pids),
           "max_frame_age_s": round(max_frame_age, 2)}
print(json.dumps(summary), flush=True)
raise SystemExit(1 if failures else 0)
