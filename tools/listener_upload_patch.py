"""[listener-uploads] The tune page's plus: a listener sends in media.

"through the tail scale page allow users to submit video and upload them (as
 long as they are under 20mb) and they get posted to the
 \\\\10.89.1.125\\QuickSwap\\samples_grabbed\\user ... Make it a plus icon on
 the page that a user can click and then upload a file from their phone /
 computer ... and audio. Just media in general"

app.py gains:
  - POST /api/listener/upload (raw body, <= 20 MB, sniffed by
    listener_uploads.sniff, staged in data/uploads/outbox) and
    GET /api/listener/upload/status (the courier's receipt), both behind the
    tune-in token and both on the public door's allowlist;
  - on the tune page (RADIO_PAGE_HTML): a round plus at the bottom left
    (Carbon's "add" glyph), a file picker for video, audio and pictures, a
    small sheet with a progress bar and the station's answer.
The host courier (tools/uploads_courier.py, pinebox-uploads.service) carries
staged files to the share.

--check exits 0 ready / 2 applied / 1 missing; --apply writes LF atomically.
ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

DOOR = r'''# --- [listener-uploads] A LISTENER SENDS MEDIA IN -------------------------------
#
# "through the tail scale page allow users to submit video and upload them (as
#  long as they are under 20mb) and they get posted to the
#  \\10.89.1.125\QuickSwap\samples_grabbed\user ... a plus icon on the page
#  ... and audio. Just media in general"
#
# The body is read with a hard cap, sniffed for what it IS (listener_uploads:
# a video, a sound or a picture - never the name or the browser's word for
# it), named and staged whole in data/uploads/outbox. The host courier
# (tools/uploads_courier.py, the pinebox-uploads service) carries it to the
# share through a read-write mount of that ONE folder and leaves a receipt;
# the station's own view of QuickSwap stays read-only. samples_grabbed is a
# drop folder (SFX_DROP_FOLDERS), so a playable clip is in the SFX draw a
# couple of minutes after it lands.
_LISTENER_UPLOADS_DIR = DATA_DIR / "uploads"
_LISTENER_UPLOAD_LOG: list[tuple[float, str, int]] = []
_LISTENER_UPLOAD_BUSY = [0]


def _listener_upload_key(request: Request, t: str) -> str:
    """Whose allowance an upload spends: the link it came in on, else the
    address it came from."""
    tag = token_tag(t) if t else ""
    if tag:
        return "link:" + tag
    hop = ""
    try:
        hop = str(request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    except Exception:  # noqa: BLE001
        hop = ""
    if not hop:
        try:
            hop = str(getattr(request.client, "host", "") or "")
        except Exception:  # noqa: BLE001
            hop = ""
    return "addr:" + (hop or "unknown")


@app.post("/api/listener/upload")
async def listener_upload_api(
    request: Request, t: str = "", name: str = "", who: str = "",
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """[listener-uploads] One video, sound or picture from a listener's phone
    or computer, at most 20 MB, for QuickSwap/samples_grabbed/user."""
    require_listen_auth(t, authorization)
    import listener_uploads as lu
    public = request.headers.get("x-pinebox-public") == "1"
    person = str(who or "").strip() or (token_tag(t) if t else "") or ("listener" if t else "operator")
    key = _listener_upload_key(request, t)
    try:
        declared = int(request.headers.get("content-length") or 0)
    except ValueError:
        declared = 0
    if declared > lu.MAX_BYTES:
        raise HTTPException(status_code=413, detail="That file is %.1f MB. The limit is 20 MB."
                            % (declared / 1048576.0))
    why = lu.throttle(_LISTENER_UPLOAD_LOG, key, declared, time.time())
    if why:
        raise HTTPException(status_code=429, detail=why)
    if _LISTENER_UPLOAD_BUSY[0] >= lu.CONCURRENT:
        raise HTTPException(status_code=429,
                            detail="two uploads are already coming in - try again in a moment")
    outbox = str(_LISTENER_UPLOADS_DIR / "outbox")
    if await asyncio.to_thread(lu.outbox_bytes, outbox) > lu.OUTBOX_CAP_BYTES:
        raise HTTPException(status_code=503,
                            detail="the station's upload tray is full until the courier catches up")
    _LISTENER_UPLOAD_BUSY[0] += 1
    buf = bytearray()
    try:
        async for chunk in request.stream():
            buf.extend(chunk)
            if len(buf) > lu.MAX_BYTES:
                raise HTTPException(status_code=413,
                                    detail="That file is over 20 MB. The limit is 20 MB.")
    finally:
        _LISTENER_UPLOAD_BUSY[0] -= 1
    if not buf:
        raise HTTPException(status_code=400, detail="Nothing arrived - choose the file and send it again.")
    got = lu.sniff(bytes(buf[:4096]))
    if not got:
        raise HTTPException(status_code=415,
                            detail="That is not a video, a sound or a picture the station can take.")
    kind, ext = got
    now = time.time()
    try:
        path = await asyncio.to_thread(lu.stage, outbox, lu.upload_name(person, name, ext, now), bytes(buf))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500,
                            detail="The station could not keep it (%s)." % type(exc).__name__) from exc
    staged = os.path.basename(path)
    _LISTENER_UPLOAD_LOG.append((now, key, len(buf)))
    try:
        pipeline_log("uploads", "%s sent %s (%s, %.1f MB, %s) - on its way to QuickSwap samples_grabbed/user"
                     % (person[:40], staged, kind, len(buf) / 1048576.0, _request_road(request)))
    except Exception:  # noqa: BLE001
        pass
    out: dict[str, Any] = {"ok": True, "name": staged, "kind": kind, "bytes": len(buf), "state": "queued",
                           "say": "Sent. It goes into the station's samples folder in a few seconds."}
    if not public:
        out["dest"] = lu.DEST_UNC + "\\" + staged
    return out


@app.get("/api/listener/upload/status")
async def listener_upload_status_api(
    request: Request, t: str = "", name: str = "",
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """[listener-uploads] Where an upload is: queued, delivered, waiting or
    failed - the courier's receipt. Through the public door the share's own
    path is left out."""
    require_listen_auth(t, authorization)
    import listener_uploads as lu
    got = await asyncio.to_thread(lu.receipt, str(_LISTENER_UPLOADS_DIR / "receipts"),
                                  str(_LISTENER_UPLOADS_DIR / "outbox"), str(name or ""))
    if request.headers.get("x-pinebox-public") == "1":
        got = {k: v for k, v in got.items() if k not in ("dest", "file")}
    return got


'''

CSS = r'''  /* [listener-uploads] the plus: bottom left, clear of the camera box at the
     bottom right; hidden in the driving layout like every other considered tap */
  body { padding-bottom: calc(max(24px, env(safe-area-inset-bottom)) + 76px); }
  .up-fab { position: fixed; left: max(14px, env(safe-area-inset-left));
    bottom: max(14px, env(safe-area-inset-bottom)); z-index: 45;
    width: 56px; height: 56px; border-radius: 50%; padding: 0;
    display: grid; place-items: center; background: #2f7d52;
    border: 1px solid #3fbf7f; color: #fff; cursor: pointer;
    box-shadow: 0 6px 20px rgba(0, 0, 0, .55); }
  .up-fab svg { width: 28px; height: 28px; fill: currentColor; }
  .up-fab:active { transform: scale(.96); }
  body.car .up-fab, body.car .up-sheet { display: none; }
  .up-sheet { position: fixed; z-index: 46;
    left: max(14px, env(safe-area-inset-left));
    bottom: calc(max(14px, env(safe-area-inset-bottom)) + 66px);
    width: min(360px, calc(100vw - 28px)); padding: 12px;
    background: #0b111b; border: 1px solid #27405a; border-radius: 12px;
    box-shadow: 0 10px 30px rgba(0, 0, 0, .65); font-size: 14px; }
  .up-sheet[hidden] { display: none; }
  .up-head { display: flex; align-items: center; gap: 8px; }
  .up-head b { flex: 1; }
  .up-x { width: 34px; height: 34px; padding: 0; display: grid; place-items: center; }
  .up-x svg { width: 18px; height: 18px; fill: currentColor; }
  .up-file { margin: 8px 0 6px; color: #dce8f5; overflow-wrap: anywhere; font-size: 13px; }
  .up-bar { height: 6px; border-radius: 3px; background: #1b2735; overflow: hidden; }
  .up-fill { height: 100%; width: 0; background: #3fbf7f; transition: width .2s linear; }
  .up-say { margin: 8px 0; color: #9fb0c4; font-size: 13px; overflow-wrap: anywhere; }
  .up-say.bad { color: #ffb4a8; }
  .up-say.good { color: #9fe0b9; }
  .up-row { display: flex; gap: 8px; }
  .up-row button { flex: 1; min-height: 40px; }
  .up-row button[hidden] { display: none; }
'''

MARKUP = r'''<!-- [listener-uploads] "a plus icon on the page that a user can click and
     then upload a file from their phone / computer": a video, a sound or a
     picture, up to 20 MB, into the station's samples folder. -->
<button id="upFab" class="up-fab" type="button" onclick="upPick()"
        aria-label="Send the station a video, a sound or a picture"
        title="Send the station a video, a sound or a picture (up to 20 MB)"><svg
        viewBox="0 0 32 32" aria-hidden="true" focusable="false"><path
        d="M17 15V8h-2v7H8v2h7v7h2v-7h7v-2z"/></svg></button>
<input id="upFile" type="file" accept="video/*,audio/*,image/*" hidden>
<div id="upSheet" class="up-sheet" role="dialog" aria-labelledby="upTitle" hidden>
  <div class="up-head"><b id="upTitle">Send it to the station</b>
    <button type="button" class="up-x" onclick="upClose()" aria-label="Close"><svg
      viewBox="0 0 32 32" aria-hidden="true" focusable="false"><path
      d="M17.4141 16L24 9.4141 22.5859 8 16 14.5859 9.4143 8 8 9.4141 14.5859 16 8 22.5859 9.4143 24 16 17.4141 22.5859 24 24 22.5859 17.4141 16z"/></svg></button></div>
  <div class="up-file" id="upName"></div>
  <div class="up-bar"><div class="up-fill" id="upFill"></div></div>
  <div class="up-say" id="upSay">A video, a sound or a picture, up to 20 MB. It goes into the station's samples folder.</div>
  <div class="up-row"><button type="button" id="upAgain" onclick="upPick()">Choose a file</button>
    <button type="button" id="upStop" onclick="upCancel()" hidden>Stop</button></div>
</div>
'''

JS = r'''/* [listener-uploads] "a plus icon on the page that a user can click and then
 * upload a file from their phone / computer" - a video, a sound or a picture,
 * up to 20 MB, into the station's samples folder (samples_grabbed/user). The
 * server sniffs what the bytes are; the checks here only save a wasted send. */
const UP_MAX = 20 * 1024 * 1024;
let upXhr = null;
function upMB(n) { return (n / 1048576).toFixed(n < 10485760 ? 1 : 0) + " MB"; }
function upEl(id) { return document.getElementById(id); }
function upShow(on) { const s = upEl("upSheet"); if (s) s.hidden = !on; }
function upSay(text, cls) {
  const n = upEl("upSay");
  if (n) { n.textContent = text; n.className = "up-say" + (cls ? " " + cls : ""); }
}
function upBusy(on) { upEl("upStop").hidden = !on; upEl("upAgain").hidden = on; }
function upPick() { upShow(true); const i = upEl("upFile"); if (i) i.click(); }
function upCancel() {
  if (upXhr) { try { upXhr.abort(); } catch (e) {} upXhr = null; }
  upBusy(false);
  upSay("Stopped. Nothing was kept.", "bad");
}
function upClose() { if (upXhr) upCancel(); upShow(false); }
function upUrl(path) {
  return GUEST ? path + (path.indexOf("?") >= 0 ? "&" : "?") + "t=" + encodeURIComponent(KEY) : path;
}
function upSend(f) {
  upShow(true);
  upEl("upName").textContent = f.name + " - " + upMB(f.size);
  upEl("upFill").style.width = "0%";
  if (f.size > UP_MAX) {
    upSay("That file is " + upMB(f.size) + ". The limit is 20 MB - trim it or send a shorter one.", "bad");
    return;
  }
  if (f.type && !/^(video|audio|image)\//.test(f.type)) {
    upSay("That is not a video, a sound or a picture.", "bad");
    return;
  }
  let who = "";
  try { who = String(localStorage.pbfmName || "").trim(); } catch (e) {}
  const xhr = new XMLHttpRequest();
  upXhr = xhr;
  xhr.open("POST", upUrl("/api/listener/upload?name=" + encodeURIComponent(f.name)
    + (who ? "&who=" + encodeURIComponent(who) : "")));
  if (!GUEST) xhr.setRequestHeader("Authorization", "Bearer " + KEY);
  xhr.setRequestHeader("Content-Type", f.type || "application/octet-stream");
  xhr.upload.onprogress = (e) => {
    if (!e.lengthComputable) return;
    const k = Math.round(100 * e.loaded / e.total);
    upEl("upFill").style.width = k + "%";
    upSay("Sending... " + k + "%");
  };
  xhr.onload = () => {
    upXhr = null;
    upBusy(false);
    let data = {};
    try { data = JSON.parse(xhr.responseText || "{}"); } catch (e) {}
    if (xhr.status >= 200 && xhr.status < 300) {
      upEl("upFill").style.width = "100%";
      upSay(data.say || "Sent.", "good");
      if (data.name) upWatch(data.name, 0);
    } else {
      upSay(data.detail || ("The station did not take it (" + xhr.status + ")."), "bad");
    }
  };
  xhr.onerror = () => {
    upXhr = null;
    upBusy(false);
    upSay("It did not get through - check the connection and try again.", "bad");
  };
  upBusy(true);
  upSay("Sending...");
  xhr.send(f);
}
function upWatch(name, n) {
  if (n > 20) return;
  setTimeout(() => {
    api("/api/listener/upload/status?name=" + encodeURIComponent(name)).then((r) => {
      if (r.state === "delivered") upSay("It is in the station's samples folder now.", "good");
      else if (r.state === "failed") upSay("The station kept it but could not file it: " + (r.why || "no reason given"), "bad");
      else upWatch(name, n + 1);
    }).catch(() => upWatch(name, n + 1));
  }, 3000);
}
(function upInit() {
  const i = upEl("upFile");
  if (i) i.addEventListener("change", () => {
    const f = i.files && i.files[0];
    i.value = "";
    if (f) upSend(f);
  });
})();

'''

EDITS = [
    ("the-public-door-takes-uploads",
     '                "/api/car/report"}\n',
     '                "/api/car/report",\n'
     '                # [listener-uploads] a listener\'s video, sound or picture:\n'
     '                # token-gated, capped at 20 MB and sniffed inside\n'
     '                "/api/listener/upload"}\n', 1),
    ("the-public-door-reports-them",
     '               "/car-diag.js",\n'
     '               "/api/car/blob"}\n',
     '               "/car-diag.js",\n'
     '               "/api/car/blob",\n'
     '               # [listener-uploads] where a listener\'s upload is\n'
     '               "/api/listener/upload/status"}\n', 1),
    ("the-upload-door",
     '@app.post("/api/car/report")\n',
     DOOR + '@app.post("/api/car/report")\n', 1),
    ("the-page-styles-the-plus",
     '  #carToggle { position: fixed; top: max(10px, env(safe-area-inset-top));\n',
     CSS + '  #carToggle { position: fixed; top: max(10px, env(safe-area-inset-top));\n', 1),
    ("the-page-carries-the-plus",
     '<button id="carToggle" onclick="toggleCar()"\n',
     MARKUP + '<button id="carToggle" onclick="toggleCar()"\n', 1),
    ("the-page-sends-the-file",
     'function toggleCar(force) {\n',
     JS + 'function toggleCar(force) {\n', 1),
]


def plan(text):
    return list(EDITS)


def state_of(text, old, new, count):
    n_new, n_old = text.count(new), text.count(old)
    if n_new >= 1 and n_old == new.count(old) * n_new:
        return "applied"
    if n_new == 0 and n_old == count:
        return "ready"
    return "anchor found %d times, wanted %d; replacement found %d times" % (n_old, count, n_new)


def check(text):
    applied, missing = 0, []
    for name, old, new, count in plan(text):
        state = state_of(text, old, new, count)
        if state == "applied":
            applied += 1
        elif state != "ready":
            missing.append("%s (%s)" % (name, state))
    return applied, missing


def apply(path):
    path = Path(path)
    text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    applied, missing = check(text)
    if applied == len(plan(text)):
        return 2
    if missing:
        for m in missing:
            print("missing:", m)
        return 1
    for name, old, new, count in plan(text):
        if state_of(text, old, new, count) == "applied":
            continue
        text = text.replace(old, new)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    with os.fdopen(fd, "wb") as fh:
        fh.write(text.encode("utf-8"))
    os.replace(tmp, path)
    return 0


def main(argv):
    target = next((a for a in argv if not a.startswith("--")), "app.py")
    if "--apply" in argv:
        code = apply(target)
        print({0: "APPLIED", 1: "ANCHORS MISSING - nothing written", 2: "already applied"}[code])
        return code
    text = Path(target).read_bytes().decode("utf-8").replace("\r\n", "\n")
    applied, missing = check(text)
    if missing:
        for m in missing:
            print("missing:", m)
        return 1
    if applied == len(plan(text)):
        print("already applied")
        return 2
    print("ready")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
