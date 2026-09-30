"""[screen-export] "export the last X minutes of the pine tab" / "... of the
pine app" / "... of the visual broadcast".

2026-09-30, the operator: "if i tell the Pine Agent to 'export the last X
minutes of the pine tab' i want an export of the last x minutes of the screen
display placed in the pine box recordings folder at
\\\\10.89.1.125\\QuickSwap\\PineBoxRecordings ... 'export the last X minutes of
the pine app' and exports the last x minutes of the screen display on the pine
app" - and "'export the last 5 minutes of the visual broadcast' for the video,
'... of the audio broadcast' or just 'broadcast' for the audio".

Every piece of the road already existed except the order: both surfaces hold a
screen ring and answer pineDesktop.replayExport({seconds, upload}) (the tablet
20 min, PineDesktopBridge; the desk 10 min, main.js replay:export); the upload
lands on PUT /api/export/upload and rides the courier (#1114) to
export_desk_dir. The station cannot reach either surface, so the order is a
REQUEST on the state both panels already poll (like reload_at / kiosk_kick):
the matching surface claims it once (/api/export/screen/claim), cuts and
uploads, and reports (/api/export/screen/done).

"visual broadcast" is the PineTab's screen WITH its sound: nothing in the
station records the picture of the air, and the tablet is the surface that
shows it. "audio broadcast" / "broadcast" keep the audio cut (#1025).

Usage (ON THE HOST): python3 tools/screen_export_patch.py --check|--apply app.py
"""
import ast
import shutil
import sys

PARSER_AT = "def parse_export_command(text: str) -> dict[str, Any] | None:\n"
PARSER_NEW = '''# [screen-export] which screen a window is cut from: the PineTab ("pine tab",
# "the tablet", "the visual broadcast" - the surface that shows the air) or
# the desk ("pine app", "the desktop app"). None = the audio cut (#1025).
_EXPORT_SCREEN_RX = re.compile(
    r"\\b(?:of|from|on|off)\\s+(?:the\\s+|my\\s+|this\\s+)?(?P<t>"
    r"pine\\s*tab(?:let)?|pinetab|tablet|"
    r"(?:visual|video|picture)\\s+(?:broadcast|show|radio|air)|"
    r"broadcast(?:'?s)?\\s+(?:video|picture|visuals?)|"
    r"pine\\s*(?:box\\s+)?app|pinebox\\s+app|desk(?:top)?(?:\\s+app)?)"
    r"(?:'?s)?(?:\\s+(?:screen|display))?\\b")


def export_screen_target(lowered: str) -> str:
    """[screen-export] 'tab' | 'app' | '' for an export order's words."""
    got = _EXPORT_SCREEN_RX.search(str(lowered or ""))
    if not got:
        return ""
    said = got.group("t")
    return "app" if re.search(r"\\bapp\\b|desk", said) else "tab"


'''

WINDOW_OLD = '''    seconds = int(round(seconds))
    if seconds < 10 or seconds > 3600:
        return None
    subject = str(got.group("subject") or "")
'''
WINDOW_NEW = '''    seconds = int(round(seconds))
    if seconds < 10 or seconds > 3600:
        return None
    screen = export_screen_target(lowered)                 # [screen-export]
    if screen:
        return {"seconds": seconds, "screen": screen}
    subject = str(got.group("subject") or "")
'''

RUN_OLD = '''    box SAYS. The cut runs behind the reply (#1153 pattern)."""
    if cmd.get("dir"):
'''
RUN_NEW = '''    box SAYS. The cut runs behind the reply (#1153 pattern)."""
    if cmd.get("screen"):                                    # [screen-export]
        return export_screen_request(cmd)
    if cmd.get("dir"):
'''

STATE_OLD = '''    base["kiosk_kick"] = float(_RADIO.get("kiosk_kick") or 0)
    track = _RADIO.get("now") or {}
'''
STATE_NEW = '''    base["kiosk_kick"] = float(_RADIO.get("kiosk_kick") or 0)
    # [screen-export] an asked-for screen export rides the same state
    base["screen_export"] = export_screen_public()
    track = _RADIO.get("now") or {}
'''

ROUTES_AT = '''@app.put("/api/export/upload")
async def export_upload_api(
'''
ROUTES_NEW = '''# [screen-export] "export the last X minutes of the pine tab / pine app / the
# visual broadcast". One request at a time; the surface it names claims it
# once, cuts its own screen ring (pineDesktop.replayExport, upload: true) and
# reports. The upload above carries the file to export_desk_dir.
_SCREEN_EXPORT: dict[str, Any] = {}
_SCREEN_EXPORT_LOCK = RLock()
SCREEN_EXPORT_HOLD = {"tab": 1200, "app": 600}   # what each ring holds, seconds
SCREEN_EXPORT_LIFE = 180.0                       # an unclaimed order expires
SCREEN_EXPORT_NAMES = {"tab": "the PineTab's screen", "app": "the Pine Box app's screen"}


def _screen_export_minutes(seconds: float) -> str:
    s = int(round(float(seconds or 0)))
    if s % 60 == 0:
        m = s // 60
        return "%d minute%s" % (m, "" if m == 1 else "s")
    return "%d seconds" % s if s < 120 else "%.1f minutes" % (s / 60.0)


def export_screen_request(cmd: dict[str, Any]) -> str:
    target = "app" if cmd.get("screen") == "app" else "tab"
    asked = int(cmd.get("seconds") or 60)
    hold = SCREEN_EXPORT_HOLD[target]
    want = max(10, min(asked, hold))
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = "%s-last-%s-%s.mp4" % ("pinetab" if target == "tab" else "pineapp",
                                  ("%dmin" % (want // 60)) if want % 60 == 0 else ("%ds" % want), stamp)
    with _SCREEN_EXPORT_LOCK:
        _SCREEN_EXPORT.clear()
        _SCREEN_EXPORT.update({"id": uuid.uuid4().hex[:12], "target": target, "seconds": want,
                               "asked": asked, "name": name, "at": time.time(),
                               "claimed_by": "", "claimed_at": 0.0, "done": False, "result": None})
    dest = export_desk_dir()
    pipeline_log("air", "spoken: export the last %ss of %s (%s)" % (want, SCREEN_EXPORT_NAMES[target], name))
    words = "Exporting the last %s of %s%s. " % (
        _screen_export_minutes(want), SCREEN_EXPORT_NAMES[target],
        " with its sound" if target == "tab" else "")
    if asked > hold:
        words += "It only keeps the last %s, so that is what it will cut. " % _screen_export_minutes(hold)
    who = "The tablet" if target == "tab" else "The Pine Box app"
    if dest:
        words += ("%s cuts it from its replay ring and the Pine Box desk carries it to %s "
                  "as %s." % (who, dest, name))
    else:
        words += ("%s cuts it from its replay ring; no export folder is set, so it stays in "
                  "data/exports as %s." % (who, name))
    return words


def export_screen_public() -> dict[str, Any] | None:
    """The order a surface may still claim, or None."""
    with _SCREEN_EXPORT_LOCK:
        row = dict(_SCREEN_EXPORT)
    if not row or row.get("done") or row.get("claimed_by"):
        return None
    if time.time() - float(row.get("at") or 0) > SCREEN_EXPORT_LIFE:
        return None
    return {"id": row["id"], "target": row["target"], "seconds": row["seconds"]}


@app.get("/api/export/screen")
async def export_screen_state_api(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_read_auth(authorization)
    with _SCREEN_EXPORT_LOCK:
        return {"ok": True, "order": dict(_SCREEN_EXPORT) or None}


@app.post("/api/export/screen/claim")
async def export_screen_claim_api(request: Request,
                                  authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_auth(authorization)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    rid = str((body or {}).get("id") or "")
    device = str((body or {}).get("device") or "")[:24]
    with _SCREEN_EXPORT_LOCK:
        row = _SCREEN_EXPORT
        fresh = time.time() - float(row.get("at") or 0) <= SCREEN_EXPORT_LIFE
        if (not row or row.get("id") != rid or row.get("done") or row.get("claimed_by")
                or not fresh or device != row.get("target")):
            return {"ok": True, "go": False}
        row["claimed_by"] = device
        row["claimed_at"] = time.time()
        return {"ok": True, "go": True, "seconds": row["seconds"], "name": row["name"]}


@app.post("/api/export/screen/done")
async def export_screen_done_api(request: Request,
                                 authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_auth(authorization)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    body = body if isinstance(body, dict) else {}
    rid = str(body.get("id") or "")
    result = body.get("result") if isinstance(body.get("result"), dict) else {}
    with _SCREEN_EXPORT_LOCK:
        if _SCREEN_EXPORT.get("id") != rid:
            return {"ok": False, "detail": "not the open order"}
        _SCREEN_EXPORT["done"] = True
        _SCREEN_EXPORT["result"] = {"ok": bool(body.get("ok")),
                                    "seconds": result.get("seconds"),
                                    "uploaded": result.get("uploaded"),
                                    "detail": str(body.get("detail") or result.get("detail") or "")[:300]}
        row = dict(_SCREEN_EXPORT)
    what = SCREEN_EXPORT_NAMES.get(row.get("target"), "the screen")
    if row["result"]["ok"]:
        note_action("exported %ss of %s as %s - the desk carries it to %s" % (
            int(float(result.get("seconds") or row.get("seconds") or 0)), what, row.get("name"),
            export_desk_dir() or "data/exports"))
    else:
        note_action("the screen export of %s did not finish: %s" % (what, row["result"]["detail"] or "no reason given"))
    return {"ok": True}


'''

JS_POLL_OLD = '''    try { panelReloadWatch(state); } catch (e) { /* the panel still reads */ }
    djRender(state);
'''
JS_POLL_NEW = '''    try { panelReloadWatch(state); } catch (e) { /* the panel still reads */ }
    try { screenExportWatch(state); } catch (e) { /* [screen-export] */ }
    djRender(state);
'''
JS_FN_AT = '''async function pollDJ() {
  try {
    const state = await api("/api/dj");
'''
JS_FN_NEW = '''/* [screen-export] "export the last X minutes of the pine tab / pine app / the
 * visual broadcast": the station posts the order on /api/dj; the surface it
 * names (the kiosk's bridge says __pineKiosk -> the tab; the desk -> the app)
 * claims it once, cuts its own screen ring and uploads it (the courier takes
 * it to the export folder), then reports. Every other window lets it pass. */
let screenExportSeen = "";
async function screenExportWatch(state) {
  const order = state && state.screen_export;
  if (!order || !order.id || order.id === screenExportSeen) return;
  const desk = window.pineDesktop;
  if (!desk || typeof desk.replayExport !== "function") return;
  const mine = desk.__pineKiosk ? "tab" : "app";
  if (order.target !== mine) return;
  screenExportSeen = order.id;
  let claim = null;
  try { claim = await api("/api/export/screen/claim", {id: order.id, device: mine}); } catch (e) { return; }
  if (!claim || !claim.go) return;
  let got = null, why = "";
  try { got = await desk.replayExport({seconds: claim.seconds, upload: true, name: claim.name}); }
  catch (e) { why = String((e && e.message) || e); }
  const up = got && got.uploaded;
  const ok = !!(got && got.ok !== false && up && up.ok !== false);
  try {
    await api("/api/export/screen/done", {id: order.id, device: mine, ok: ok,
      result: got || {}, detail: why || (up && up.detail) || (got && got.detail) || ""});
  } catch (e) { /* the station hears nothing; the order expires */ }
}

async function pollDJ() {
  try {
    const state = await api("/api/dj");
'''

EDITS = [
    ("parser helper", PARSER_AT, PARSER_NEW + PARSER_AT),
    ("parser window", WINDOW_OLD, WINDOW_NEW),
    ("runner", RUN_OLD, RUN_NEW),
    ("state", STATE_OLD, STATE_NEW),
    ("routes", ROUTES_AT, ROUTES_NEW + ROUTES_AT),
    ("panel poll", JS_POLL_OLD, JS_POLL_NEW),
    ("panel watcher", JS_FN_AT, JS_FN_NEW),
]


def main() -> None:
    mode, path = sys.argv[1], sys.argv[2]
    src = open(path, encoding="utf-8").read()
    if "[screen-export]" in src:
        print(path + ": APPLIED")
        return
    out = src
    for label, old, new in EDITS:
        n = out.count(old)
        assert n == 1, "%s: anchor found %d times" % (label, n)
        out = out.replace(old, new)
    ast.parse(out)
    if mode == "--check":
        print(path + ": ready (%d edits)" % len(EDITS))
        return
    shutil.copy(path, "/tmp/app.py.bak-screen-export")
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src, "app.py changed underfoot"
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    main()
