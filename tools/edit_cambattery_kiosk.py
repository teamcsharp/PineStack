#!/usr/bin/env python3
"""[cambattery] the battery meter on the tablet's NATIVE Pine Cam surface.

    python3 edit_cambattery_kiosk.py --check <kiosk project root>   # 0 / 2 / 1
    python3 edit_cambattery_kiosk.py --apply <kiosk project root>

Root = the dir holding app/src/main/java/com/pinebox/kiosk (the kiosk project
C:\\_tools\\pinebox-android\\PineBoxKiosk, or the repo's app/ mirror's parent).

  * adds video/CamBatteryBadge.kt (a copy of ../kiosk/CamBatteryBadge.kt);
  * PineCamWall.kt: the badge as a child of the wall + fun battery(o);
  * PineDesktopBridge.kt: pineCam verb "battery" -> cam.battery(arg).
Marker-idempotent ([cambattery]); CRLF-aware (each file keeps its own
newlines); checks every anchor before writing anything.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

MARK = "[cambattery]"
HERE = Path(__file__).resolve().parent
BADGE_SRC = HERE.parent / "kiosk" / "CamBatteryBadge.kt"
PKG = Path("app/src/main/java/com/pinebox/kiosk")

WALL_EDITS = [
    ("the screen",
     "    private val screen = SurfaceView(context).apply { setZOrderMediaOverlay(true) }\n",
     "    private val screen = SurfaceView(context).apply { setZOrderMediaOverlay(true) }\n"
     "\n"
     "    /* [cambattery] the camera's battery in the picture's top-left: a\n"
     "     * z-on-top surface, the one layer above a media overlay. The page\n"
     "     * sends the reading (bridge verb `battery`); this is its child so it\n"
     "     * leaves with the picture. See CamBatteryBadge. */\n"
     "    private val badge = CamBatteryBadge(context)\n"),
    ("addView(screen)",
     "        addView(screen, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT))\n",
     "        addView(screen, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT))\n"
     "        addView(badge, LayoutParams(1, 1, Gravity.TOP or Gravity.START))   // [cambattery]\n"),
    ("fun free()",
     "    fun free() = menu(false)\n",
     "    fun free() = menu(false)\n"
     "\n"
     "    /** [cambattery] {on, text, bars, tone, pulse, stale, charging} from the page. */\n"
     "    fun battery(o: JSONObject) { onMain { badge.show(o) } }\n"),
]
BRIDGE_EDITS = [
    ("pineCam free",
     "                    \"free\" -> cam.free()\n",
     "                    \"free\" -> cam.free()\n"
     "                    \"battery\" -> cam.battery(arg ?: JSONObject())         // [cambattery]\n"),
]


def edit(text: str, edits) -> tuple[int, str, list[str]]:
    if MARK in text:
        return 2, text, []
    miss = [n for n, a, _ in edits if text.count(a) != 1]
    if miss:
        return 1, text, miss
    for _, a, n in edits:
        text = text.replace(a, n, 1)
    return 0, text, []


def load(p: Path) -> tuple[str, bool]:
    raw = p.read_bytes().decode("utf-8")
    return raw.replace("\r\n", "\n"), "\r\n" in raw


def save(p: Path, text: str, crlf: bool) -> None:
    if crlf:
        text = text.replace("\n", "\r\n")
    tmp = p.with_name(p.name + ".cambattery.tmp")
    tmp.write_bytes(text.encode("utf-8"))
    os.replace(tmp, p)
    print("%s: APPLIED" % p)


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    root = Path(argv[2]) / PKG
    wall_p = root / "video" / "PineCamWall.kt"
    bridge_p = root / "bridge" / "PineDesktopBridge.kt"
    badge_p = root / "video" / "CamBatteryBadge.kt"
    plan = []
    worst = []
    for p, edits in ((wall_p, WALL_EDITS), (bridge_p, BRIDGE_EDITS)):
        text, crlf = load(p)
        code, out, miss = edit(text, edits)
        print("%s: %s" % (p, {0: "ok", 2: "already applied"}.get(code, "anchor missing: " + ", ".join(miss))))
        worst.append(code)
        plan.append((p, code, out, crlf))
    badge_new = not badge_p.exists()
    print("%s: %s" % (badge_p, "new" if badge_new else "present"))
    if 1 in worst:
        return 1
    if worst == [2, 2] and not badge_new:
        return 2
    if argv[1] == "--check":
        return 0
    for p, code, out, crlf in plan:
        if code == 0:
            save(p, out, crlf)
    if badge_new:
        _, crlf = load(wall_p)
        save(badge_p, BADGE_SRC.read_bytes().decode("utf-8").replace("\r\n", "\n"), crlf)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
