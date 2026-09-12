"""How long until a REAL record makes its first frame?

A gap at every track turnover would be a regression against the page, so
this measures the thing that would cause one: spawn, probe, seek, first
PCM. Run against whatever the station has on its local shelf.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, "/app")
import station_stream as S  # noqa: E402


def timed(path: str, offset: float) -> None:
    t0 = time.monotonic()
    dec = S._Decoder(path, offset)
    ok = dec.start()
    spawn = time.monotonic() - t0
    first = None
    filled = None
    while time.monotonic() - t0 < 20:
        frame, live = dec.read_frame()
        if live and frame != S.SILENCE and first is None:
            first = time.monotonic() - t0
        if dec.ready_bytes > 2_000_000 and filled is None:
            filled = time.monotonic() - t0
        if first and filled:
            break
        time.sleep(0.02)
    dec.close()
    name = Path(path).name[:44]
    print(f"  spawn={spawn * 1000:6.0f}ms  first_frame="
          f"{(first or -1) * 1000:7.0f}ms  12s_buffered="
          f"{(filled or -1) * 1000:7.0f}ms  ok={ok}  {name}")


hot = Path("/app/data/music_hot")
cands = []
if hot.is_dir():
    cands = sorted([p for p in hot.iterdir() if p.is_file()
                    and p.suffix.lower() in (".mp3", ".m4a", ".flac", ".wav")],
                   key=lambda p: -p.stat().st_size)[:3]
print(f"local shelf ({hot}): {len(cands)} candidate(s)")
for c in cands:
    timed(str(c), 0.0)
    timed(str(c), 61.5)

lo = Path("/app/data/music_lo")
if lo.is_dir():
    small = sorted([p for p in lo.iterdir() if p.is_file()],
                   key=lambda p: -p.stat().st_size)[:2]
    print(f"low-rate cache ({lo}): {len(small)} candidate(s)")
    for c in small:
        timed(str(c), 30.0)
