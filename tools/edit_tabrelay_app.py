#!/usr/bin/env python3
"""[tabrelay] app.py learns the PineTab's side of the camera relay.

  * POST /api/pinelink/relay/report - the tablet says what its side-link and
    relay are doing; the station writes data/pinelink_relay.json (plus the
    operator's last announce_at, which tools/pinelink.py reads as "the camera
    is wanted") and answers from the supervisor's state.json `source`:
    want / ssid / psk / bssid / mode / allow / ports / every_s.
  * GET  /api/pinelink/relay - the setting, the tablet's last report, the road.
  * POST /api/pinelink/relay - {"pref": "auto" | "always" | "never"} into
    data/pinelink_relay_pref.json (merged; `mode` udp|pass kept).
  * The camera's battery is asked through the tablet (http://<tablet>:8580/)
    while the supervisor's road is the tablet; otherwise exactly as before.

No tablet report, or a supervisor without the [tabrelay] edit: `want` is
false, and nothing else changes.

usage: edit_tabrelay_app.py --check|--apply [app.py]
exit 0 ready, 2 already applied, 1 anchor missing
"""
import sys
from pathlib import Path

MARK = "[tabrelay]"

BLOCK = r'''

# ------------------------------------------------------------- [tabrelay]
# THE PINETAB'S SIDE OF THE CAMERA RELAY.
#
# The tablet can join the camera's hotspot as a LOCAL-ONLY second Wi-Fi link
# (TacoNet stays its own) and relay it on TacoNet: rtsp://<tablet>:8554/live
# and http://<tablet>:8580/ (the camera's API). tools/pinelink.py owns the
# camera and decides which road reaches it (plan_source); this door is only
# the tablet's mailbox:
#   the tablet POSTs its report every 5-30 s -> data/pinelink_relay.json
#   (the station adds `at`, the operator's `announce_at` and the peer), and
#   the answer is read off the supervisor's state.json `source` block.
# The camera's password is handed out only while the tablet is WANTED, and
# only to a caller holding the key. A stale state file (the supervisor not
# running) or a tablet that says it cannot hold a local-only link is never
# wanted - so with no report, or no [tabrelay] supervisor, nothing changes.
PINELINK_RELAY_FILE = data_path("pinelink_relay.json")
PINELINK_RELAY_PREF_FILE = data_path("pinelink_relay_pref.json")
PINELINK_RELAY_PREFS = ("auto", "always", "never")
PINELINK_CAMERA_SSID = "H88_5c8e8bddfab1"
PINELINK_CAMERA_PSK = "12345678"
PINELINK_CAMERA_BSSID = "5c:8e:8b:dd:fa:b1"
PINELINK_CAMERA_HOST = "192.168.1.254"
PINELINK_RELAY_STALE_S = 30.0
PINELINK_RELAY_ALLOW = [a.strip() for a in
                        os.getenv("PINELINK_RELAY_ALLOW", "10.89.1.246").split(",")
                        if a.strip()]
_PINELINK_RELAY_IP = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")


def pinelink_relay_ip(raw: Any) -> str:
    """[tabrelay] a dotted IPv4 address, or ''."""
    s = str(raw or "").strip()
    if not _PINELINK_RELAY_IP.match(s):
        return ""
    return s if all(0 <= int(p) <= 255 for p in s.split(".")) else ""


def pinelink_relay_pref() -> dict[str, str]:
    """[tabrelay] the operator's setting; no file, or a bad one, is auto/udp."""
    try:
        got = json.loads(PINELINK_RELAY_PREF_FILE.read_text())
        got = got if isinstance(got, dict) else {}
    except Exception:  # noqa: BLE001
        got = {}
    pref = str(got.get("pref") or "auto")
    mode = str(got.get("mode") or "udp")
    return {"pref": pref if pref in PINELINK_RELAY_PREFS else "auto",
            "mode": mode if mode in ("udp", "pass") else "udp"}


def pinelink_relay_clean(body: Any, now: float, announce_at: float,
                         peer: str) -> dict[str, Any]:
    """[tabrelay] the tablet's report, kept to known fields and sizes."""
    body = body if isinstance(body, dict) else {}

    def small(d: Any, n: int = 24) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if not isinstance(d, dict):
            return out
        for k, v in list(d.items())[:n]:
            k = str(k)[:40]
            if isinstance(v, bool) or v is None:
                out[k] = v
            elif isinstance(v, (int, float)):
                out[k] = v if abs(v) < 1e15 else 0
            else:
                out[k] = str(v)[:240]
        return out

    link = small(body.get("link"))
    relay = small(body.get("relay"))
    link["joined"] = bool(link.get("joined"))
    relay["listening"] = bool(relay.get("listening"))
    try:
        link["signal"] = max(0, min(100, int(link.get("signal") or 0)))
    except Exception:  # noqa: BLE001
        link["signal"] = 0
    return {"v": int(body.get("v") or 0) if str(body.get("v") or "0").isdigit() else 0,
            "capable": bool(body.get("capable")),
            "ip": pinelink_relay_ip(body.get("ip")),
            "link": link, "relay": relay, "at": float(now),
            "announce_at": float(announce_at or 0), "peer": pinelink_relay_ip(peer)}


def pinelink_relay_reply(state: Any, report: dict[str, Any], now: float,
                         allow: list[str]) -> dict[str, Any]:
    """[tabrelay] What the tablet is told. Pure. `want` needs all of: a FRESH
    supervisor state, its [tabrelay] `source` block asking for the tablet,
    and a tablet that says it can hold a local-only link."""
    state = state if isinstance(state, dict) else {}
    src = state.get("source") if isinstance(state.get("source"), dict) else {}
    try:
        fresh = now - float(state.get("at") or 0) < PINELINK_RELAY_STALE_S
    except Exception:  # noqa: BLE001
        fresh = False
    capable = bool(report.get("capable"))
    if not src:
        why = "the camera's supervisor does not plan a relay yet"
    elif not fresh:
        why = "the camera's supervisor is not running"
    elif not capable:
        why = ("this tablet cannot hold a second, local-only Wi-Fi link: "
               + str((report.get("link") or {}).get("why") or "not supported"))[:240]
    else:
        why = str(src.get("why") or "")[:240]
    want = bool(src) and fresh and capable and bool(src.get("want_tablet"))
    use = str(src.get("use") or "dongle") if (src and fresh) else "dongle"
    try:
        rtsp_port = int(src.get("rtsp_port") or 8554)
        http_port = int(src.get("http_port") or 8580)
    except Exception:  # noqa: BLE001
        rtsp_port, http_port = 8554, 8580
    out: dict[str, Any] = {
        "ok": True, "want": want, "why": why, "use": use,
        "pref": str(src.get("pref") or pinelink_relay_pref()["pref"]),
        "mode": str(src.get("mode") or "udp") if str(src.get("mode") or "udp") in ("udp", "pass") else "udp",
        "every_s": 5 if (want or use in ("tablet", "wait")) else 30,
        "ssid": PINELINK_CAMERA_SSID, "bssid": PINELINK_CAMERA_BSSID,
        "camera": PINELINK_CAMERA_HOST, "rtsp_port": rtsp_port, "http_port": http_port,
        "allow": [a for a in dict.fromkeys(allow) if pinelink_relay_ip(a)],
    }
    if want:
        out["psk"] = PINELINK_CAMERA_PSK
    return out


def pinelink_battery_url(link: Any) -> str:
    """[tabrelay] the camera's battery through the road in force: the
    tablet's relay (:8580) while the supervisor reads the camera through it,
    otherwise the camera itself on the dongle's network, as before."""
    try:
        src = (link or {}).get("source") or {}
        ip = pinelink_relay_ip(src.get("ip"))
        if src.get("use") == "tablet" and ip:
            return "http://%s:%d/?custom=1&cmd=3019" % (ip, int(src.get("http_port") or 8580))
    except Exception:  # noqa: BLE001
        pass
    return PINELINK_BATTERY_URL


def _pinelink_relay_write(path: Path, got: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(got))
    os.replace(str(tmp), str(path))


def _pinelink_relay_state_raw() -> dict[str, Any]:
    try:
        got = json.loads(PINELINK_STATE.read_text())
        return got if isinstance(got, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def pinelink_relay_view(say: str = "") -> dict[str, Any]:
    """[tabrelay] GET /api/pinelink/relay: the setting, the report, the road.
    Never the camera's password."""
    now = time.time()
    try:
        rep = json.loads(PINELINK_RELAY_FILE.read_text())
        rep = rep if isinstance(rep, dict) else {}
    except Exception:  # noqa: BLE001
        rep = {}
    state = _pinelink_relay_state_raw()
    src = state.get("source") if isinstance(state.get("source"), dict) else None
    return {"ok": True, **pinelink_relay_pref(), "prefs": list(PINELINK_RELAY_PREFS),
            "report": rep, "report_age_s": round(now - float(rep.get("at") or 0), 1) if rep else None,
            "source": src, "say": say}


@app.post("/api/pinelink/relay/report")
async def pinelink_relay_report_api(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """[tabrelay] The PineTab's report, and the station's answer to it."""
    require_auth(authorization)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    now = time.time()
    peer = request.client.host if getattr(request, "client", None) else ""
    rep = pinelink_relay_clean(body, now, float(_PINELINK_ANNOUNCE.get("at") or 0), peer)

    def work() -> dict[str, Any]:
        _pinelink_relay_write(PINELINK_RELAY_FILE, rep)
        return _pinelink_relay_state_raw()

    try:
        state = await asyncio.to_thread(work)
    except Exception as err:  # noqa: BLE001
        return {"ok": False, "want": False, "why": "could not keep the report: " + str(err)[:160],
                "every_s": 30}
    allow = list(PINELINK_RELAY_ALLOW)
    host = pinelink_relay_ip(getattr(getattr(request, "url", None), "hostname", ""))
    if host:
        allow.insert(0, host)
    return pinelink_relay_reply(state, rep, now, allow)


@app.get("/api/pinelink/relay")
async def pinelink_relay_api(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """[tabrelay] Relay through the PineTab: the setting and the road."""
    require_read_auth(authorization)
    return await asyncio.to_thread(pinelink_relay_view)


@app.post("/api/pinelink/relay")
async def pinelink_relay_set_api(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """[tabrelay] {"pref": "auto" | "always" | "never", "mode"?: "udp" | "pass"}."""
    require_auth(authorization)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    body = body if isinstance(body, dict) else {}
    patch: dict[str, str] = {}
    if "pref" in body:
        pref = str(body.get("pref") or "").strip().lower()
        if pref not in PINELINK_RELAY_PREFS:
            return {**pinelink_relay_view(), "ok": False,
                    "say": "the relay setting is auto, always or never - not %r" % pref[:40]}
        patch["pref"] = pref
    if "mode" in body:
        mode = str(body.get("mode") or "").strip().lower()
        if mode not in ("udp", "pass"):
            return {**pinelink_relay_view(), "ok": False, "say": "the relay mode is udp or pass"}
        patch["mode"] = mode
    if not patch:
        return pinelink_relay_view("nothing to change")

    def work() -> None:
        try:
            got = json.loads(PINELINK_RELAY_PREF_FILE.read_text())
            got = got if isinstance(got, dict) else {}
        except Exception:  # noqa: BLE001
            got = {}
        got.update(patch)
        got["at"] = time.time()
        _pinelink_relay_write(PINELINK_RELAY_PREF_FILE, got)

    try:
        await asyncio.to_thread(work)
    except Exception as err:  # noqa: BLE001
        return {**pinelink_relay_view(), "ok": False,
                "say": "could not remember that: " + str(err)[:160]}
    said = {"auto": "the PineTab relays the camera when it can reach it better",
            "always": "the camera is read through the PineTab only (the dongle stays off)",
            "never": "the camera is read through the Spark's dongle only"}.get(
                patch.get("pref", ""), "relay mode %s" % patch.get("mode", ""))
    try:
        pipeline_log("air", "pine cam relay: " + said + " [tabrelay]")
    except Exception:  # noqa: BLE001
        pass
    return pinelink_relay_view(said)
'''

ANNOUNCE = ('    _PINELINK_ANNOUNCE["at"] = time.time()\n'
            '    return {"ok": True, "at": _PINELINK_ANNOUNCE["at"]}\n')

EDITS = [
    (ANNOUNCE, ANNOUNCE + BLOCK),
    ('def _pinelink_battery_poll() -> None:\n',
     'def _pinelink_battery_poll(url: str = "") -> None:   # [tabrelay] url: the road in force\n'),
    ('        with opener.open(PINELINK_BATTERY_URL, timeout=4.0) as r:\n',
     '        with opener.open(url or PINELINK_BATTERY_URL, timeout=4.0) as r:   # [tabrelay]\n'),
    ('                _CambattThread(target=_pinelink_battery_poll, name="pinelink-battery",\n'
     '                               daemon=True).start()\n',
     '                _CambattThread(target=_pinelink_battery_poll, name="pinelink-battery",\n'
     '                               args=(pinelink_battery_url(link),),   # [tabrelay]\n'
     '                               daemon=True).start()\n'),
]


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"
    p = Path(sys.argv[2] if len(sys.argv) > 2 else "app.py")
    raw = p.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    text = raw.replace("\r\n", "\n")
    if "pinelink_relay_report_api" in text or "def pinelink_battery_url" in text:
        print("%s app.py already applied" % MARK)
        return 2
    bad = ["%d x (want 1): %s" % (text.count(a), a.strip()[:80]) for a, _n in EDITS if text.count(a) != 1]
    if bad:
        print("%s app.py anchor missing:\n  %s" % (MARK, "\n  ".join(bad)))
        return 1
    if mode != "--apply":
        print("%s app.py ready" % MARK)
        return 0
    for a, n in EDITS:
        text = text.replace(a, n)
    compile(text, str(p), "exec")
    if crlf:
        text = text.replace("\n", "\r\n")
    tmp = p.with_name(p.name + ".tabrelay-tmp")
    tmp.write_bytes(text.encode("utf-8"))
    tmp.replace(p)
    print("%s app.py applied" % MARK)
    return 2


if __name__ == "__main__":
    sys.exit(main())
