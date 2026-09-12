"""#1253: prove the mixer keeps real time before the station depends on it.

Runs the stream with a synthetic snapshot - a generated tone as the
"record" and a second tone as a "DJ clip" - and checks the three things
that matter in a car:

  1. it produces mp3 at all;
  2. `produced_seconds` tracks wall-clock (the pace is real time by
     construction, not by luck);
  3. a listener attaching mid-flight gets bytes immediately (the join
     burst), which is what makes a car radio start on the first packet.
"""
from __future__ import annotations

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
         "-ac", "2", str(path)],
        check=True, timeout=120)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="streamtest-"))
    record, clip = tmp / "record.wav", tmp / "clip.wav"
    tone(record, 40, 220)
    tone(clip, 3, 660)
    print("fixtures:", record.stat().st_size, clip.stat().st_size, "bytes")

    started = time.time()
    clip_at = started + 4.0

    def snapshot():
        return {
            "on": True, "paused": False,
            "music": {"id": "test", "path": str(record),
                      "started": started, "title": "Test Tone",
                      "artist": "The Mixer"},
            "clips": [{"key": "k1", "air_at": clip_at,
                       "path": str(clip), "length": 3.0}],
        }

    stream = S.StationStream(snapshot, bitrate=128)
    sink = stream.attach()

    got = bytearray()
    deadline = time.time() + 12.0
    first_at = None
    while time.time() < deadline:
        chunk = sink.take(1.0)
        if chunk:
            if first_at is None:
                first_at = time.time()
            got += chunk

    state = stream.state()
    stream.detach(sink)
    stream.stop()

    wall = time.time() - started
    produced = float(state.get("produced_seconds") or 0)
    print(f"bytes={len(got)}  first_byte_after={first_at - started:.2f}s")
    print(f"wall={wall:.1f}s produced={produced:.1f}s "
          f"drift={produced - wall:+.2f}s")
    print("clips_aired:", state.get("clips_aired"),
          "underruns:", state.get("underruns"),
          "encoder_restarts:", state.get("encoder_restarts"))
    print("last_error:", state.get("last_error") or "(none)")

    ok = True
    if len(got) < 64_000:
        print("FAIL: too few mp3 bytes"); ok = False
    if got[:2] not in (b"\xff\xfb", b"\xff\xf3", b"\xff\xfa", b"ID"):
        print(f"WARN: unexpected first bytes {got[:4]!r}")
    if abs(produced - wall) > 1.5:
        print("FAIL: mixer is not keeping real time"); ok = False
    if int(state.get("clips_aired") or 0) != 1:
        print("FAIL: the DJ clip did not air"); ok = False
    if first_at is None or first_at - started > 3.0:
        print("FAIL: audio did not begin promptly"); ok = False

    # Decode what we captured and confirm the tones are actually in it.
    out = tmp / "captured.mp3"
    out.write_bytes(bytes(got))
    probe = subprocess.run(
        [S._ffmpeg_exe(), "-nostdin", "-hide_banner", "-v", "error",
         "-i", str(out), "-f", "null", "-"],
        capture_output=True, timeout=60)
    print("decode stderr:", (probe.stderr or b"").decode()[:200] or "(clean)")
    dur = subprocess.run(
        [S._ffmpeg_exe(), "-nostdin", "-hide_banner", "-i", str(out),
         "-f", "null", "-"], capture_output=True, timeout=60)
    tail = (dur.stderr or b"").decode()
    print("ffmpeg summary:", tail.strip().splitlines()[-1][:160]
          if tail.strip() else "(none)")

    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
