"""#1253: is the AUDIO ITSELF glitching, at a resolution that can stutter?

The envelope probe measures one-second RMS. A stutter is 50-200 ms. So a
clean envelope report proves almost nothing about the complaint - a hole
every second would be averaged into invisibility.

This looks for the two things the mixer can actually do wrong:

  * DIGITAL SILENCE mid-programme. The decoder read_frame() pads a short
    read with zeros and reports it as live audio, so a starved decoder
    inserts a hole with no telemetry at all. Any run of exact zeros
    longer than a few milliseconds, surrounded by audio, is one of those.
  * DISCONTINUITY. A sample-to-sample jump far outside the local
    distribution is a splice - a frame dropped, a decoder respawned
    mid-record, or two sources crossed.

Reports both with timestamps, so a fault can be tied to what the station
was doing at that instant.
"""
from __future__ import annotations

import subprocess
import sys

import numpy as np

sys.path.insert(0, "/app")
import station_stream as S  # noqa: E402

src = sys.argv[1] if len(sys.argv) > 1 else "/tmp/cap.mp3"

raw = subprocess.run(
    [S._ffmpeg_exe(), "-nostdin", "-hide_banner", "-v", "error",
     "-i", src, "-f", "s16le", "-ar", "44100", "-ac", "1", "pipe:1"],
    capture_output=True, timeout=300).stdout

x = np.frombuffer(raw, dtype="<i2").astype(np.float32)
SR = 44100
dur = len(x) / SR
print(f"decoded {dur:.1f}s")
if dur < 1:
    print("RESULT: FAIL (nothing decoded)")
    raise SystemExit(1)

# ---- 1. runs of exact digital silence ------------------------------------
zero = (x == 0)
# run-length encode the zero mask
idx = np.flatnonzero(np.diff(zero.astype(np.int8)))
edges = np.concatenate(([0], idx + 1, [len(zero)]))
runs = []
for a, b in zip(edges[:-1], edges[1:]):
    if zero[a] and (b - a) >= SR * 0.010:        # >= 10 ms of pure zero
        runs.append((a / SR, (b - a) / SR))

# a leading/trailing zero run is just the edge of the capture
inner = [r for r in runs if r[0] > 0.5 and r[0] + r[1] < dur - 0.5]
print(f"\ndigital-silence runs >=10ms (mid-programme): {len(inner)}")
total_hole = sum(r[1] for r in inner)
for at, ln in inner[:15]:
    print(f"    at {at:7.2f}s  for {ln * 1000:7.1f} ms")
if inner:
    print(f"    total {total_hole * 1000:.0f} ms of holes "
          f"({total_hole / dur * 100:.2f}% of the capture)")

# ---- 2. sample-to-sample discontinuities ---------------------------------
d = np.abs(np.diff(x))
# a splice shows as a jump far outside the local distribution
med = float(np.median(d)) or 1.0
thresh = max(2000.0, med * 60)
jumps = np.flatnonzero(d > thresh)
# cluster adjacent reports
clustered = []
last = -SR
for j in jumps:
    if j - last > SR * 0.05:
        clustered.append(j)
    last = j
print(f"\ndiscontinuities (|jump| > {thresh:.0f}): {len(clustered)}")
for j in clustered[:15]:
    print(f"    at {j / SR:7.2f}s  jump {d[j]:.0f}")

# ---- 3. level in 50 ms blocks: where does it actually drop out? ----------
blk = int(SR * 0.05)
n = len(x) // blk
lv = np.sqrt(np.mean((x[:n * blk].reshape(n, blk)) ** 2, axis=1))
floor = np.percentile(lv, 5)
quiet = np.flatnonzero(lv < max(1.0, floor * 0.02))
print(f"\n50ms blocks far below the floor: {len(quiet)} of {n} "
      f"({len(quiet) / max(1, n) * 100:.2f}%)")

ok = (not inner) and len(clustered) < 3
print("\nRESULT:", "PASS - the mix is continuous" if ok
      else "FAIL - the audio itself has holes/splices")
raise SystemExit(0 if ok else 1)
