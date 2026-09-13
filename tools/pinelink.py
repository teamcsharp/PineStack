#!/usr/bin/env python3
"""PineLink: the camera, held on the spare radio and served to the house.

The camera is an ACCESS POINT. Anything that wants its video has to join
`H88_<mac>`, and a device with one radio that joins it drops off the house
LAN - which for the tablet means losing the station entirely. The DGX has
two radios, so this holds the camera on the spare one (`wlx…`) while
`wlP9s9` keeps 10.89.1.246 and the broadcast. That asymmetry is the whole
reason the link lives here and not on the tablet.

One ffmpeg, one input, two outputs:

    rtsp://192.168.1.254:554/live  (h264 848x480, the preview substream)
      ├─ HLS   → data/pinelink/live/index.m3u8   what the house watches
      └─ mp4   → data/pinelink/clips/<stamp>.mp4  what is kept

Both are `-c copy`. The camera already hands over h264, so nothing is
re-encoded: no GPU, no quality loss, and a recording that is byte-identical
to what was broadcast. The 4K H.265 never comes down this pipe - it stays
on the camera's card and is fetched over its HTTP server afterwards. 4K
over a 10 m camera AP into a live broadcast would be a bad trade even if it
worked.

`-use_wallclock_as_timestamps` is not optional. The camera sends packets
with no PTS at all - measured: "Timestamps are unset in a packet for stream
0" and non-monotonic DTS on the very first test pull - and a `-c copy`
without it produces a file whose timing is broken in a way that only shows
up later, when you try to play it back or cut it.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "pinelink"
LIVE = OUT / "live"
CLIPS = OUT / "clips"
STATE = OUT / "state.json"

STATION_IF = "wlP9s9"           # holds 10.89.1.246 - never touched
SPARE_IF = "wlx984827b6b478"
SSID = "H88_5c8e8bddfab1"
PSK = "12345678"
CAMERA = "192.168.1.254"
RTSP = "rtsp://%s:554/live" % CAMERA

SEGMENT_SECONDS = 300           # one file per five minutes
KEEP_HOURS = 48.0               # same as every other ledger here
RESTART_REST = 5.0


def run(cmd: list[str], timeout: float = 30.0) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as err:  # noqa: BLE001
        return 1, str(err)


def say(state: str, **more) -> None:
    """One state file, written whole. The station reads this; it never
    reads the process table, so a stale file is a lie and the only defence
    is that every path through this program writes one."""
    try:
        OUT.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps({
            "at": time.time(), "state": state, "camera": CAMERA,
            "rtsp": RTSP, "ssid": SSID, "iface": SPARE_IF, **more}, indent=2))
    except Exception:  # noqa: BLE001
        pass


def station_safe() -> bool:
    code, out = run(["ip", "-4", "-br", "addr", "show", STATION_IF])
    return "10.89.1.246" in out


def linked() -> bool:
    code, out = run(["ip", "-4", "-br", "addr", "show", SPARE_IF])
    return "192.168.1." in out


def join() -> bool:
    """Join the camera's AP on the spare radio only."""
    if linked():
        return True
    run(["nmcli", "device", "set", SPARE_IF, "managed", "yes"])
    run(["ip", "link", "set", SPARE_IF, "up"])
    run(["nmcli", "device", "wifi", "rescan", "ifname", SPARE_IF], 45)
    time.sleep(4)
    code, out = run(["nmcli", "device", "wifi", "connect", SSID,
                     "password", PSK, "ifname", SPARE_IF], 60)
    return code == 0 and linked()


def camera_awake() -> bool:
    """Does the camera answer? Asked of RTSP, not of ping: these cameras
    answer ICMP while their streamer is still coming up, so a ping is a
    reading that is true too early."""
    code, _ = run(["ffprobe", "-v", "error", "-rtsp_transport", "tcp",
                   "-timeout", "4000000", "-show_streams", RTSP], 15)
    return code == 0


def trim_old() -> int:
    """Two days of clips, like every other ledger on this box."""
    gone = 0
    floor = time.time() - KEEP_HOURS * 3600.0
    try:
        for f in CLIPS.glob("*.mp4"):
            if f.stat().st_mtime < floor:
                f.unlink()
                gone += 1
    except Exception:  # noqa: BLE001
        pass
    return gone


def ffmpeg_cmd() -> list[str]:
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        "-rtsp_transport", "tcp",
        # The camera sets no PTS. Without this the copy is unplayable
        # later in ways that do not show up now.
        "-use_wallclock_as_timestamps", "1",
        "-i", RTSP,
        # what the house watches
        "-map", "0:v", "-c", "copy",
        "-f", "hls", "-hls_time", "2", "-hls_list_size", "6",
        "-hls_flags", "delete_segments+append_list+omit_endlist",
        "-hls_segment_filename", str(LIVE / "seg%05d.ts"),
        str(LIVE / "index.m3u8"),
        # what is kept
        "-map", "0:v", "-c", "copy",
        "-f", "segment", "-segment_time", str(SEGMENT_SECONDS),
        "-reset_timestamps", "1", "-strftime", "1",
        str(CLIPS / "%Y-%m-%d_%H-%M-%S.mp4"),
    ]


def supervise(once: bool = False) -> None:
    if not station_safe():
        say("refused", why="%s is not holding 10.89.1.246 - refusing to "
            "touch the radios" % STATION_IF)
        print("REFUSING: the station's radio is not where it should be.")
        sys.exit(2)
    LIVE.mkdir(parents=True, exist_ok=True)
    CLIPS.mkdir(parents=True, exist_ok=True)

    while True:
        if not join():
            say("no-link", why="the camera's network is not being "
                "broadcast, or the join failed")
            if once:
                return
            time.sleep(15)
            continue
        if not camera_awake():
            say("linked-quiet", why="joined, but the camera is not "
                "streaming yet")
            if once:
                return
            time.sleep(8)
            continue

        trimmed = trim_old()
        say("live", pid=0, trimmed=trimmed,
            hls="data/pinelink/live/index.m3u8")
        print("PineLink live: %s -> %s" % (RTSP, LIVE))
        proc = subprocess.Popen(ffmpeg_cmd(), stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, text=True)
        say("live", pid=proc.pid, hls="data/pinelink/live/index.m3u8")
        try:
            _, err = proc.communicate()
        except KeyboardInterrupt:
            proc.terminate()
            say("stopped", why="asked to stop")
            return
        tail = "\n".join((err or "").strip().splitlines()[-4:])
        # An ffmpeg that exits is not an error to swallow: the camera
        # sleeps, wanders out of range, or its battery goes. Say which,
        # as far as can be told, and try again.
        say("dropped", why=tail[:400] or "the stream ended")
        print("PineLink dropped: %s" % (tail[:200] or "stream ended"))
        if once:
            return
        time.sleep(RESTART_REST)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true",
                    help="one attempt, then exit (for testing)")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()
    if args.status:
        try:
            print(STATE.read_text())
        except Exception:  # noqa: BLE001
            print('{"state": "never-run"}')
        return
    supervise(once=args.once)


if __name__ == "__main__":
    main()
