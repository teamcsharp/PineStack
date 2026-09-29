#!/usr/bin/env python3
"""[tabrelay] tools/pinelink.py learns a second road to the camera: the PineTab.

The tablet joins the camera's hotspot as a local-only second Wi-Fi network and
relays it on TacoNet (rtsp://<tablet>:8554/live, http://<tablet>:8580/). This
edit teaches the supervisor to:

  * read the tablet's report (data/pinelink_relay.json, written by the station
    from POST /api/pinelink/relay/report) and the operator's setting
    (data/pinelink_relay_pref.json: auto / always / never, default auto);
  * choose the road each pass with plan_source() - a pure function, unit
    tested - and say which in state.json `source` (the station tells the
    tablet whether it is wanted from that block, and draws the path);
  * read the relay over TCP (ffmpeg's -rtsp_transport tcp; the relay asks the
    camera for UDP on its own side, so the camera's 30 s interleaved cut does
    not apply), never rescan or re-join the dongle while the tablet holds the
    camera, and let the dongle go (nmcli device disconnect) when the tablet
    needs the camera's one client slot;
  * restart ffmpeg on the new road when the road changes (a short gap, named
    "switching", never classified as a fault or a transport rotation).

usage: edit_tabrelay_pinelink.py --check|--apply <tools/pinelink.py>
exit 0 ready, 2 already applied, 1 anchor missing
"""
import sys
from pathlib import Path

MARK = "[tabrelay]"

BLOCK = r'''
# ---------------------------------------------------------------------------
# [tabrelay] THE PINETAB AS THE CAMERA'S RELAY.
#
# The camera's radio is weak and the dongle is fixed to the DGX; the operator
# carries the PineTab and the camera together, and the tablet is on TacoNet
# everywhere. So the tablet can join the camera's hotspot as a LOCAL-ONLY
# second Wi-Fi network (TacoNet stays its own) and relay it:
#     rtsp://<tablet>:8554/live   (read over TCP; the relay asks the camera for
#                                  UDP itself, dodging the 30 s interleaved cut)
#     http://<tablet>:8580/       (the camera's API: the battery)
#
# WHO DECIDES. This process: it owns the camera. The tablet reports what it can
# do and is doing (the station writes it to RELAY_FILE); the operator's setting
# is RELAY_PREF_FILE; plan_source() picks the road and say() publishes it as
# `source`, which is what the station answers the tablet with. One writer per
# file, as everywhere here.
#
# THE ONE CLIENT SLOT. The camera's hotspot is believed to admit one client
# (#1349's doctor says so). So a handoff tries make-before-break first
# (RELAY_MBB_S: the tablet asks while the dongle still streams - if the camera
# takes two, there is no gap at all), then break-before-make (the dongle lets
# go for RELAY_BBM_S), and a tablet that still cannot join is left alone for
# RELAY_BACKOFF_S while the dongle carries the picture.
# ---------------------------------------------------------------------------
RELAY_FILE = ROOT / "data" / "pinelink_relay.json"
RELAY_PREF_FILE = ROOT / "data" / "pinelink_relay_pref.json"
RELAY_PREFS = ("auto", "always", "never")
RELAY_RTSP_PORT, RELAY_HTTP_PORT = 8554, 8580
RELAY_FRESH_S = 20.0        # a report older than this is a tablet that is not there
RELAY_MBB_S = 20.0          # the tablet's first try, with the dongle still streaming
RELAY_BBM_S = 45.0          # then the dongle lets go for this long
RELAY_LOSS_S = 12.0         # a tablet that lost the camera gets this long to rejoin
RELAY_BACKOFF_S = (120.0, 300.0, 900.0)
RELAY_WANTED_S = 1800.0     # "the camera is wanted": announced or relayed this recently
_SRC: dict = {"use": "dongle", "why": "", "want_tablet": False,
              "release_dongle": False, "pref": "auto", "ip": "", "url": RTSP,
              "at": 0.0, "running": ""}
_SRC_MEM: dict = {}
_DONGLE_LET_GO = [False]


def relay_pref() -> dict:
    """[tabrelay] {"pref": auto|always|never, "mode": udp|pass}. No file, or a
    file that cannot be read, is auto/udp."""
    try:
        got = json.loads(RELAY_PREF_FILE.read_text())
        pref = str(got.get("pref") or "auto")
        mode = str(got.get("mode") or "udp")
        return {"pref": pref if pref in RELAY_PREFS else "auto",
                "mode": mode if mode in ("udp", "pass") else "udp"}
    except Exception:  # noqa: BLE001
        return {"pref": "auto", "mode": "udp"}


def relay_report() -> dict:
    """[tabrelay] The tablet's last report as the station wrote it, or {}."""
    try:
        got = json.loads(RELAY_FILE.read_text())
        return got if isinstance(got, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def plan_source(pref: str, rep: dict, now: float, mem: dict,
                wanted: bool) -> dict:
    """[tabrelay] Which road reaches the camera now. Pure but for `mem`, the
    handoff's own memory (try_at, fail_until, fails, ok_at, was_joined).

    -> {"use": "tablet" | "dongle" | "wait", "want_tablet": bool,
        "release_dongle": bool, "why": str, "ip": str}
    `wait` = neither road is up yet and the dongle must not take the camera.
    """
    rep = rep if isinstance(rep, dict) else {}
    fresh = bool(rep) and now - float(rep.get("at") or 0) <= RELAY_FRESH_S
    link = rep.get("link") if isinstance(rep.get("link"), dict) else {}
    relay = rep.get("relay") if isinstance(rep.get("relay"), dict) else {}
    ip = str(rep.get("ip") or "") if fresh else ""
    capable = fresh and bool(rep.get("capable")) and bool(ip)
    joined = capable and bool(link.get("joined")) and bool(relay.get("listening"))

    def out(use, want, release, why):
        return {"use": use, "want_tablet": bool(want), "release_dongle": bool(release),
                "why": why, "ip": ip}

    if joined:
        mem.update({"ok_at": now, "was_joined": True, "try_at": 0.0, "fails": 0})
    if pref == "never":
        mem.clear()
        return out("dongle", False, False, "relay through the PineTab is off")
    if not fresh:
        tablet = "the PineTab is not reporting"
    elif not capable:
        tablet = ("the PineTab cannot run a second Wi-Fi link: "
                  + str(link.get("why") or "no reason given"))[:240]
    else:
        tablet = ""
    if pref == "always":
        if joined:
            return out("tablet", True, True, "via the PineTab (always)")
        return out("wait", capable, True, (tablet or "waiting for the PineTab to join the camera")
                   + " - the dongle stays off (always)")
    # auto
    if joined:
        return out("tablet", True, True, "via the PineTab")
    if not capable:
        return out("dongle", False, False, tablet)
    if mem.get("was_joined"):
        if now - float(mem.get("ok_at") or 0) < RELAY_LOSS_S:
            return out("wait", True, True, "the PineTab lost the camera - rejoining")
        mem["was_joined"] = False
        mem["try_at"] = 0.0
        mem["fails"] = int(mem.get("fails") or 0) + 1
        mem["fail_until"] = now + RELAY_BACKOFF_S[min(mem["fails"], len(RELAY_BACKOFF_S)) - 1]
    if now < float(mem.get("fail_until") or 0):
        return out("dongle", False, False, "the PineTab could not hold the camera; the "
                   "dongle carries it - next try in %d s" % int(float(mem["fail_until"]) - now))
    if not wanted:
        return out("dongle", False, False, "the camera is not wanted yet (not seen, "
                   "not announced) - the PineTab is asked when it is")
    if not mem.get("try_at"):
        mem["try_at"] = now
    t = now - float(mem["try_at"])
    if t < RELAY_MBB_S:
        return out("dongle", True, False, "the PineTab is joining the camera; the dongle "
                   "keeps the picture meanwhile")
    if t < RELAY_MBB_S + RELAY_BBM_S:
        return out("wait", True, True, "the dongle let go so the PineTab can join (the "
                   "camera takes one client at a time)")
    mem["try_at"] = 0.0
    mem["fails"] = int(mem.get("fails") or 0) + 1
    mem["fail_until"] = now + RELAY_BACKOFF_S[min(mem["fails"], len(RELAY_BACKOFF_S)) - 1]
    return out("dongle", False, False, "the PineTab could not join the camera; the dongle "
               "again - next try in %d s" % int(float(mem["fail_until"]) - now))


def camera_wanted(rep: dict, now: float) -> bool:
    """[tabrelay] Is there a camera worth asking the tablet to join? The
    dongle sees or holds it, the operator announced it (the radio icon), or
    the tablet carried it recently. A tablet is not sent hunting for a camera
    that nobody switched on."""
    try:
        if _LAST_SEEN.get("seen") or linked():
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        if now - float((rep or {}).get("announce_at") or 0) < RELAY_WANTED_S:
            return True
    except Exception:  # noqa: BLE001
        pass
    return now - float(_SRC_MEM.get("ok_at") or 0) < RELAY_WANTED_S


def on_tablet() -> bool:
    return _SRC.get("use") in ("tablet", "wait")


def cam_rtsp() -> str:
    """[tabrelay] The RTSP URL of the road in force."""
    if _SRC.get("use") == "tablet" and _SRC.get("ip"):
        return "rtsp://%s:%d/live" % (_SRC["ip"], RELAY_RTSP_PORT)
    return RTSP


def source_turn() -> dict:
    """[tabrelay] Plan this pass and act on the dongle side of it."""
    now = time.time()
    pref = relay_pref()
    rep = relay_report()
    # camera_wanted() runs `ip` - only asked when a capable tablet is reporting
    wanted = bool(rep.get("capable")) and camera_wanted(rep, now)
    plan = plan_source(pref["pref"], rep, now, _SRC_MEM, wanted)
    if plan["release_dongle"] and not _DONGLE_LET_GO[0]:
        # Let the camera's one client slot go. `device disconnect` also stops
        # NetworkManager auto-joining it again; join() asks explicitly later.
        run(["nmcli", "device", "disconnect", SPARE_IF], 20)
        _DONGLE_LET_GO[0] = True
        print("PineLink: the dongle let the camera go - %s" % plan["why"], flush=True)
    if plan["use"] == "dongle":
        _DONGLE_LET_GO[0] = False
    _SRC.update(plan)
    _SRC.update({"pref": pref["pref"], "mode": pref["mode"], "at": now})
    _SRC["url"] = cam_rtsp()
    return plan


def source_moved() -> bool:
    """[tabrelay] While ffmpeg runs: has the road changed under it?"""
    try:
        plan = source_turn()
    except Exception:  # noqa: BLE001
        return False
    running = _SRC.get("running") or ""
    return bool(running) and plan["use"] != running


def source_view() -> dict:
    """[tabrelay] The block say() carries. Never raises."""
    try:
        rep = relay_report()
        link = rep.get("link") if isinstance(rep.get("link"), dict) else {}
        return {**{k: _SRC.get(k) for k in ("use", "why", "want_tablet", "release_dongle",
                                            "pref", "mode", "ip", "url", "at", "running")},
                "rtsp_port": RELAY_RTSP_PORT, "http_port": RELAY_HTTP_PORT,
                "tablet_signal": int(link.get("signal") or 0),
                "tablet_link_mbps": int(link.get("link_mbps") or 0),
                "tablet_state": str(link.get("state") or ""),
                "report_at": float(rep.get("at") or 0)}
    except Exception:  # noqa: BLE001
        return {"use": "dongle"}


def source_report() -> dict:
    """[tabrelay] --source: the setting, the tablet's report and the plan this
    pass would make, WITHOUT acting on the dongle."""
    now = time.time()
    rep = relay_report()
    mem = dict(_SRC_MEM)
    return {"pref": relay_pref(), "report": rep,
            "report_age_s": round(now - float(rep.get("at") or 0), 1) if rep else None,
            "plan": plan_source(relay_pref()["pref"], rep, now, mem, camera_wanted(rep, now))}
'''

EDITS = [
    # the block, after the camera's own address
    ('RTSP = "rtsp://%s:554/live" % CAMERA\n',
     'RTSP = "rtsp://%s:554/live" % CAMERA\n' + BLOCK),
    # say() carries the road
    ('            "crop": crop,                                   # [pincrop]\n',
     '            "crop": crop,                                   # [pincrop]\n'
     '            "source": source_view(),                        # [tabrelay]\n'),
    # the relay is read over TCP, and only the dongle's road rotates transports
    ('    return TRANSPORTS[_TRANSPORT[0] % len(TRANSPORTS)]\n',
     '    if _SRC.get("use") == "tablet":        # [tabrelay] the relay is read over TCP\n'
     '        return "tcp"\n'
     '    return TRANSPORTS[_TRANSPORT[0] % len(TRANSPORTS)]\n'),
    # both ffmpeg commands read the road in force (2 occurrences)
    ('        "-i", RTSP,\n',
     '        "-i", cam_rtsp(),                   # [tabrelay] the road in force\n'),
    ('"-timeout", "4000000", "-show_streams", RTSP], 15)',
     '"-timeout", "4000000", "-show_streams", cam_rtsp()], 15)   # [tabrelay]'),
    # no dongle scans while the tablet holds the camera
    ('        if not quick:\n            _LAST_SEEN.update(seen_on_air())\n',
     '        if not quick and not on_tablet():      # [tabrelay] no dongle scan on the tablet\'s road\n'
     '            _LAST_SEEN.update(seen_on_air())\n'),
    ('        if (not quick) and ((not linked())                    # [pincrop]\n',
     '        if (not quick) and (not on_tablet()) and ((not linked())   # [pincrop] [tabrelay]\n'),
    # the road, before the dongle is joined
    ('        if not join():\n',
     '        # [tabrelay] which road reaches the camera this pass\n'
     '        try:\n'
     '            src = source_turn()\n'
     '        except Exception as err:  # noqa: BLE001\n'
     '            src = {"use": "dongle", "why": "planning failed: %s" % err}\n'
     '            _SRC.update(src)\n'
     '        if src["use"] == "wait":\n'
     '            say("waiting-tablet", why=src["why"])\n'
     '            if once:\n'
     '                return\n'
     '            time.sleep(3)\n'
     '            reframe = True\n'
     '            continue\n'
     '        if src["use"] != "tablet" and not join():\n'),
    # remember which road ffmpeg was started on
    ('        _STREAM["transport"] = rtsp_transport()               # #1250b\n',
     '        _STREAM["transport"] = rtsp_transport()               # #1250b\n'
     '        _SRC["running"] = _SRC.get("use") or "dongle"         # [tabrelay]\n'),
    # the watch loop notices a new road
    ('                # [pincrop] the operator moved the box: this ffmpeg stops\n',
     '                # [tabrelay] the road changed (the PineTab joined, or went):\n'
     '                # this ffmpeg stops and the next starts on the new road.\n'
     '                if source_moved():\n'
     '                    _SRC["switch"] = True\n'
     '                    stop_gently(proc, 3.0)\n'
     '                    break\n'
     '                # [pincrop] the operator moved the box: this ffmpeg stops\n'),
    ('        if stalled:\n',
     '        if _SRC.pop("switch", False):     # [tabrelay] a new road, not a fault\n'
     '            say("switching", why="the camera\'s road changed: %s" % _SRC.get("why", ""))\n'
     '            print("PineLink: switching road after %.0fs - %s" % (time.time() - began, _SRC.get("why", "")), flush=True)\n'
     '            if once:\n'
     '                return\n'
     '            reframe = True\n'
     '            continue\n'
     '        if stalled:\n'),
    ('        if 2.0 <= life < TRANSPORT_GOOD_S:\n',
     '        if 2.0 <= life < TRANSPORT_GOOD_S and _SRC.get("running") != "tablet":   # [tabrelay]\n'),
    # --source prints the plan
    ('    args = ap.parse_args()\n',
     '    ap.add_argument("--source", action="store_true",        # [tabrelay]\n'
     '                    help="print the relay setting, the PineTab report and the plan")\n'
     '    args = ap.parse_args()\n'),
    ('    if args.crop:\n',
     '    if args.source:                                           # [tabrelay]\n'
     '        print(json.dumps(source_report(), indent=2))\n'
     '        return\n'
     '    if args.crop:\n'),
]
COUNTS = {'        "-i", RTSP,\n': 2}


def check(text: str) -> list:
    bad = []
    for a, _n in EDITS:
        want = COUNTS.get(a, 1)
        if text.count(a) != want:
            bad.append("%d x (want %d): %s" % (text.count(a), want, a.strip()[:80]))
    return bad


def apply(text: str) -> str:
    for a, n in EDITS:
        text = text.replace(a, n)
    return text


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"
    p = Path(sys.argv[2] if len(sys.argv) > 2 else "tools/pinelink.py")
    raw = p.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    text = raw.replace("\r\n", "\n")
    if MARK in text:
        print("%s already applied" % MARK)
        return 2
    bad = check(text)
    if bad:
        print("%s anchor missing:\n  %s" % (MARK, "\n  ".join(bad)))
        return 1
    if mode != "--apply":
        print("%s ready" % MARK)
        return 0
    out = apply(text)
    compile(out, str(p), "exec")
    if crlf:
        out = out.replace("\n", "\r\n")
    tmp = p.with_name(p.name + ".tabrelay-tmp")
    tmp.write_bytes(out.encode("utf-8"))
    tmp.replace(p)
    print("%s applied" % MARK)
    return 2


if __name__ == "__main__":
    sys.exit(main())
