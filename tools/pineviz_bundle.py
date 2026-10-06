#!/usr/bin/env python3
"""PineViz bundle - the modular sources in desktop/renderer/pipviz, concatenated in load order into one
file the station already serves from its vendor route (/vendor/pineviz.bundle.js) and the PiP panel
loads into the station page. The sources stay the truth; the bundle is a build artifact, committed so
a deploy needs no build step.

Usage:  pineviz_bundle.py            write desktop/renderer/pipviz/dist/pineviz.bundle.js
        pineviz_bundle.py --check    0 when the bundle matches the sources, 1 when it is stale
        pineviz_bundle.py --install  write it, then copy it into the station's vendor dir (data/vendor)
                                     through the container, which owns that directory
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "desktop" / "renderer" / "pipviz"
OUT = SRC / "dist" / "pineviz.bundle.js"
ORDER = [
    "core/PineViz.js", "core/Renderer.js", "core/VisualizerManager.js", "audio/Providers.js", "ui/Overlay.js",
    "visualizers/_shared.js", "visualizers/01-SmoothWave.js", "visualizers/02-ParticleFlow.js", "visualizers/03-LineSpectrum.js",
    "visualizers/04-GeometricSpace.js", "visualizers/05-SpeedLines.js", "visualizers/06-AnimeInk.js", "visualizers/07-AudioBars.js",
    "visualizers/08-LiquidGlass.js", "visualizers/09-RetroGrid.js", "visualizers/10-ShapeBurst.js",
]


def build() -> str:
    parts = []
    digest = hashlib.sha1()
    for name in ORDER:
        text = (SRC / name).read_text(encoding="utf-8").replace("\r\n", "\n")
        digest.update(text.encode("utf-8"))
        parts.append("/* ---- %s ---- */\n%s\n" % (name, text.rstrip("\n")))
    stamp = digest.hexdigest()[:12]
    head = ("/* PineViz bundle %s - built by tools/pineviz_bundle.py from desktop/renderer/pipviz; edit the sources, not this file. */\n"
            "/* pineviz-build:%s */\n" % (stamp, stamp))
    return head + "\n".join(parts)


def current_stamp(text: str) -> str:
    for line in text.splitlines()[:3]:
        if "pineviz-build:" in line:
            return line.split("pineviz-build:")[1].split(" ")[0].strip()
    return ""


def main(argv: list[str]) -> int:
    text = build()
    if "--check" in argv:
        have = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current_stamp(have) == current_stamp(text):
            print("bundle current (%s, %d bytes)" % (current_stamp(text), len(text)))
            return 0
        print("bundle STALE: sources are %s, bundle is %s" % (current_stamp(text), current_stamp(have) or "missing"))
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print("wrote %s (%s, %d bytes)" % (OUT, current_stamp(text), len(text)))
    if "--install" in argv:
        # data/vendor belongs to the container's user; the bind mount makes the repo /app inside it
        rel = OUT.relative_to(ROOT).as_posix()
        cmd = ["docker", "exec", "spark-agent", "sh", "-c", "cp /app/%s /app/data/vendor/pineviz.bundle.js && ls -la /app/data/vendor/pineviz.bundle.js" % rel]
        print(subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout.strip() or "installed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
