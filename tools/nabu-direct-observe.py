"""Passive bounded HTTP observation on the DGX host; never sends device audio."""
import argparse
import ipaddress
import json
from pathlib import Path
import re
import subprocess
import time


def summarize(output, device):
    rows, packets, wire_bytes = [], 0, 0
    packet = None
    for line in output.splitlines():
        header = re.match(r"^(\d+\.\d+) .*?IP (\S+) > (\S+): .*length (\d+)", line)
        if header:
            at, source, target, length = header.groups()
            packet = {"at": float(at), "source": source, "target": target}
            packets += 1
            wire_bytes += int(length)
            continue
        if not packet:
            continue
        request = re.search(r"GET (/nabu-audio/[a-f0-9]{32}\.flac)(?:\?\S*)? HTTP/1\.[01]", line)
        if request:
            rows.append({**packet, "request": request.group(1),
                         "direct_device_request": packet["source"].startswith(device + ".")})
        elif re.search(r"HTTP/1\.[01] \d{3}", line):
            status = re.search(r"HTTP/1\.[01] (\d{3})", line)
            rows.append({**packet, "status": int(status.group(1))})
        elif line.startswith("Content-Type:") or line.startswith("User-Agent: micro-decoder/"):
            rows.append({**packet, "header": line.strip()[:160]})
    return {"events": rows, "packets": packets, "wire_payload_bytes": wire_bytes,
            "direct_requests": sum(bool(row.get("direct_device_request")) for row in rows),
            "limits": "Observed requests/transfer only, not acoustic proof. Wire bytes can include retransmissions. Signed query tokens and audio payloads are not retained."}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default="10.89.1.161")
    parser.add_argument("--seconds", type=int, default=45)
    parser.add_argument("--output", default="docs/nabu-direct-observation.json")
    args = parser.parse_args()
    if ipaddress.ip_address(args.device) not in ipaddress.ip_network("10.89.1.0/24"):
        raise SystemExit("Device must be the known local LAN address")
    if not 5 <= args.seconds <= 55:
        raise SystemExit("Observation must be bounded to 5..55 seconds")
    started = time.time()
    # timeout owns tcpdump's lifetime even if the requesting shell disconnects.
    result = subprocess.run(["sudo", "-n", "timeout", str(args.seconds), "tcpdump",
        "-i", "any", "-nn", "-tt", "-l", "-A", "-s", "0",
        "host", args.device, "and", "tcp", "port", "8096"],
        capture_output=True, text=True, errors="replace", timeout=args.seconds + 5)
    report = {"read_only": True, "started_at": started, "ended_at": time.time(),
              "device": args.device, "capture_exit": result.returncode,
              **summarize(result.stdout, args.device)}
    if result.returncode not in (0, 124):
        report["capture_error"] = result.stderr[-500:]
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("read_only", "device", "capture_exit", "direct_requests")}))


if __name__ == "__main__":
    main()
