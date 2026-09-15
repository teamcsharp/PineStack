"""#1253: behave like a real HLS player and see whether the stream holds.

A player re-reads the playlist every few seconds and fetches each new
segment exactly once, in order. Two things break audio and neither shows
up in a single playlist fetch:

  * a GAP in the media sequence - a segment that existed in one playlist
    and was deleted before the player asked for it, which is a hole in
    the audio;
  * a segment that 404s, which a player reports as a stall.

This walks the playlist for a while doing precisely what a player does,
and reports continuity, per-segment fetch time, and total audio duration
against wall clock. Duration/wall below 1.0 means the listener cannot
keep up no matter how good their connection is.
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else ""
TOKEN = sys.argv[2] if len(sys.argv) > 2 else ""
RATE = sys.argv[3] if len(sys.argv) > 3 else "64"
RUN_SECONDS = float(sys.argv[4]) if len(sys.argv) > 4 else 90.0


def get(url: str, timeout: float = 20.0):
    started = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": "hls-probe"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
    return body, time.monotonic() - started, 200


def main() -> int:
    playlist_url = f"{BASE}/stream.m3u8?t={TOKEN}&br={RATE}"
    seen: dict[str, float] = {}
    order: list[str] = []
    errors: list[str] = []
    fetch_times: list[float] = []
    total_dur = 0.0
    started = time.monotonic()
    last_seq = None
    gaps = 0
    polls = 0

    while time.monotonic() - started < RUN_SECONDS:
        try:
            body, took, _ = get(playlist_url)
            polls += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"playlist: {exc}")
            time.sleep(2)
            continue
        text = body.decode("utf-8", "replace")
        seq = re.search(r"#EXT-X-MEDIA-SEQUENCE:(\d+)", text)
        seq_n = int(seq.group(1)) if seq else -1

        lines = text.splitlines()
        durs = {}
        cur = None
        for line in lines:
            if line.startswith("#EXTINF:"):
                try:
                    cur = float(line.split(":", 1)[1].strip().rstrip(","))
                except ValueError:
                    cur = None
            elif line and not line.startswith("#"):
                durs[line] = cur
                cur = None

        for uri, dur in durs.items():
            if uri in seen:
                continue
            name = uri.split("/")[-1].split("?")[0]
            num = int(re.sub(r"\D", "", name) or -1)
            if last_seq is not None and num != last_seq + 1:
                gaps += 1
                errors.append(f"SEQUENCE GAP: {last_seq} -> {num}")
            last_seq = num
            url = uri if uri.startswith("http") else BASE + uri
            try:
                data, took, _ = get(url)
                fetch_times.append(took)
                if len(data) < 500:
                    errors.append(f"{name}: only {len(data)} bytes")
                seen[uri] = dur or 0.0
                order.append(name)
                total_dur += dur or 0.0
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{name}: {exc}")
        time.sleep(2.0)

    wall = time.monotonic() - started
    print(f"ran {wall:.0f}s  playlist polls={polls}  segments={len(order)}")
    print(f"audio fetched: {total_dur:.1f}s  "
          f"ratio to wall: {total_dur / wall:.3f}  (want >= 1.0)")
    if fetch_times:
        fetch_times.sort()
        print(f"segment fetch: median={fetch_times[len(fetch_times)//2]:.2f}s "
              f"p90={fetch_times[int(len(fetch_times)*.9)]:.2f}s "
              f"max={fetch_times[-1]:.2f}s")
    print(f"sequence gaps: {gaps}")
    print(f"errors: {len(errors)}")
    for e in errors[:12]:
        print("   ", e)
    ok = gaps == 0 and not errors and total_dur / wall >= 0.95
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
