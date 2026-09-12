"""Per-second level of a captured stream: does the bed duck, and is the
voice actually on top of it?

A flat envelope means one of the two never made it into the mix. What we
want to see is a music bed at a steady level with louder passages where
the DJ is talking and the bed has dropped underneath.
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
    capture_output=True, timeout=180).stdout

pcm = np.frombuffer(raw, dtype="<i2").astype(np.float32)
sec = 44100
n = len(pcm) // sec
print(f"{len(pcm) / sec:.1f}s decoded")

levels = []
for i in range(n):
    block = pcm[i * sec:(i + 1) * sec]
    rms = float(np.sqrt(np.mean(block * block))) or 1.0
    levels.append(20 * np.log10(rms / 32768.0))

for i, db in enumerate(levels):
    bar = "#" * max(0, int((db + 60) / 1.4))
    print(f"{i:3d}s {db:7.1f} dBFS {bar}")

arr = np.array(levels)
quiet = arr[arr < np.median(arr)]
loud = arr[arr >= np.median(arr)]
print(f"\nmedian {np.median(arr):.1f} dBFS   "
      f"low half {quiet.mean():.1f}   high half {loud.mean():.1f}   "
      f"spread {loud.mean() - quiet.mean():.1f} dB")
print(f"min {arr.min():.1f}  max {arr.max():.1f}")
silent = int((arr < -55).sum())
print(f"near-silent seconds: {silent} of {n}")
