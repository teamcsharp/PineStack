"""#1253: the persistence contract, tested without touching the live show.

"whenever I enable it, it basically doesn't turn off until I re-hit the
switch" - so the three things that used to end a listening session must
not end this one:

  1. THE STATION PAUSES. The old road stopped the element and, on the
     page, showed a wake button. Here the socket must stay open and be
     fed silence, so coming back on air costs the listener nothing.
  2. THE RECORD RUNS OUT / TURNS OVER. Must not end the stream.
  3. THE SNAPSHOT THROWS. A fault upstairs must degrade to silence on a
     held socket, never to a closed connection.

Each phase asserts that bytes KEEP ARRIVING and that the sink is still
open at the end.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import threading
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


tmp = Path(tempfile.mkdtemp(prefix="persist-"))
rec_a, rec_b = tmp / "a.wav", tmp / "b.wav"
tone(rec_a, 30, 220)
tone(rec_b, 30, 330)

MODE = {"phase": "playing"}
started = time.time()


def snapshot():
    phase = MODE["phase"]
    if phase == "throw":
        raise RuntimeError("the upstairs fell over")
    if phase == "paused":
        return {"on": True, "paused": True, "music": None, "clips": []}
    track = rec_b if phase == "track_b" else rec_a
    tid = "b" if phase == "track_b" else "a"
    return {"on": True, "paused": False,
            "music": {"id": tid, "path": str(track), "started": time.time(),
                      "title": f"Record {tid.upper()}", "artist": "Test"},
            "clips": []}


stream = S.StationStream(snapshot, bitrate=128)
sink = stream.attach()

counts: dict[str, int] = {}
stop = threading.Event()


def pull(label: str, seconds: float) -> int:
    got = 0
    end = time.time() + seconds
    while time.time() < end:
        chunk = sink.take(0.5)
        got += len(chunk)
    counts[label] = got
    return got


plan = [
    ("playing", "on air", 6),
    ("paused", "station PAUSED", 6),
    ("playing", "back on air", 5),
    ("track_b", "record turned over", 5),
    ("throw", "snapshot THROWING", 5),
    ("playing", "recovered", 5),
]

print(f"{'phase':<22} {'bytes':>9} {'kbit/s':>8}  open?")
ok = True
for mode, label, secs in plan:
    MODE["phase"] = mode
    got = pull(label, secs)
    kbit = got * 8 / secs / 1000
    print(f"{label:<22} {got:>9} {kbit:>8.1f}  {sink.open}")
    if got <= 0:
        print(f"   FAIL: the stream went silent-and-dead during {label}")
        ok = False
    if not sink.open:
        print(f"   FAIL: the socket CLOSED during {label}")
        ok = False

state = stream.state()
print("\nclips_aired:", state.get("clips_aired"),
      "encoder_restarts:", state.get("encoder_restarts"),
      "underruns:", state.get("underruns"))
print("last_error:", state.get("last_error") or "(none)")
wall = time.time() - started
print(f"produced={state.get('produced_seconds')}s  "
      f"up={state.get('up_seconds')}s")

stream.detach(sink)
stream.stop()
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
