"""#1253: the persistence contract, tested without touching the live show.

"whenever I enable it, it basically doesn't turn off until I re-hit the
switch" - so the things that used to end a listening session must not end
this one:

  1. THE STATION PAUSES. The old road stopped the element and showed a
     wake button. Here the socket stays open and is fed silence, so
     coming back on air costs the listener nothing.
  2. THE RECORD RUNS OUT / TURNS OVER.
  3. THE SNAPSHOT THROWS. A fault upstairs must degrade to silence on a
     held socket, never to a closed connection.

Each phase asserts bytes KEEP ARRIVING and the sink is still open.
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, "/app")
import station_stream as S  # noqa: E402


def tone(path: Path, seconds: float, freq: int) -> None:
    subprocess.run(
        [S._ffmpeg_exe(), "-nostdin", "-hide_banner", "-loglevel", "error",
         "-y", "-f", "lavfi", "-i",
         f"sine=frequency={freq}:duration={seconds}:sample_rate=44100",
         "-ac", "2", str(path)], check=True, timeout=120)


async def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="persist-"))
    rec_a, rec_b = tmp / "a.wav", tmp / "b.wav"
    tone(rec_a, 30, 220)
    tone(rec_b, 30, 330)

    mode = {"phase": "playing"}

    def snapshot():
        phase = mode["phase"]
        if phase == "throw":
            raise RuntimeError("the upstairs fell over")
        if phase == "paused":
            return {"on": True, "paused": True, "music": None, "clips": []}
        track = rec_b if phase == "track_b" else rec_a
        tid = "b" if phase == "track_b" else "a"
        return {"on": True, "paused": False,
                "music": {"id": tid, "path": str(track),
                          "started": time.time(),
                          "title": "Record " + tid.upper(), "artist": "Test"},
                "clips": []}

    stream = S.StationStream(snapshot, bitrate=128)
    sink = stream.attach()

    async def pull(seconds: float) -> int:
        got = 0
        end = time.time() + seconds
        while time.time() < end:
            got += len(await sink.aget(0.5))
        return got

    plan = [
        ("playing", "on air", 6),
        ("paused", "station PAUSED", 6),
        ("playing", "back on air", 5),
        ("track_b", "record turned over", 5),
        ("throw", "snapshot THROWING", 5),
        ("playing", "recovered", 5),
    ]

    print("phase                      bytes   kbit/s  open?")
    ok = True
    for phase, label, secs in plan:
        mode["phase"] = phase
        got = await pull(secs)
        print("%-22s %9d %8.1f  %s"
              % (label, got, got * 8 / secs / 1000, sink.open))
        if got <= 0:
            print("   FAIL: the stream went dead during " + label)
            ok = False
        if not sink.open:
            print("   FAIL: the socket CLOSED during " + label)
            ok = False

    state = stream.state()
    row = dict(sink.row())
    print("\nclips_aired:", state.get("clips_aired"),
          "encoder_restarts:", state.get("encoder_restarts"),
          "underruns:", state.get("underruns"))
    print("last_error:", state.get("last_error") or "(none)")
    print("listener: delivered_x=%s dropped_kb=%s"
          % (row["delivered_x"], row["dropped_kb"]))
    print("produced=%ss up=%ss"
          % (state.get("produced_seconds"), state.get("up_seconds")))

    stream.detach(sink)
    stream.stop()
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
