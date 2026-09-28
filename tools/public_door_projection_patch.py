#!/usr/bin/env python3
"""[public-door] The listener door answers with the listener's cut, and only
the door can say who came through it.

"right now, anyone on the Tailscale Funnel can GET /api/dj through the public
 listener door (127.0.0.1:8097 on the host) without a token. It returns the
 full dj_state(): 476 KB, including standing orders, personas, prompts and
 traces. ... The listener page, car-diag.js, sfx-tv.js, the slideshow and
 tune-messenger.js must keep working exactly as they do now: find every field
 they read, allow exactly those, and nothing else." (2026-09-28)

Measured through :8097 on 2026-09-28 before this tool, with no token:
  GET /api/dj            531,652 bytes, 61 keys, 240 chat rows carrying trace
                         (trace.written.prompt: personas, "STANDING ORDERS FROM
                         THE OPERATOR"), system3 seed + config_hash, analysis,
                         model, query, rule, scenario, sfx_match_why ...
  GET /api/dj?lean=1      36-47 KB, the same row keys on the last 20 rows
  GET /api/pinelink/frame.jpg with the one header "x-pinebox-public: 0" and no
                         token: 200 image/jpeg - the studio camera. The gate
                         APPENDS its mark and Starlette's headers.get() returns
                         the FIRST header of a name, so the caller's own
                         "x-pinebox-public: 0" won every `== "1"` check behind
                         the door (the camera's #1354d refusal, /tune's
                         full-scope panel refusal, the upload receipt's UNC
                         path, and this tool's projections alike).

What changes (app.py unless marked):
  gate            PublicListenerGate drops any x-pinebox-public the caller sent
                  before it appends its own: the door's mark is the only one.
  dj-public       dj_state_public(): an ALLOW list of what the listener page
                  reads off /api/dj (the only public page that reads it; car-
                  diag.js, sfx-tv.js, the slideshow and tune-messenger.js read
                  none of it), leaves only, the chat's last DJ_LEAN_CHAT rows as
                  {id, ts, text, who}. Plus the door's allow list for
                  /api/stream/state (STREAM_PUBLIC_KEYS).
  dj-route-*      /api/dj through the door: the tune-in token (every other road
                  of the page asks for it; the page sends ?t= on every call) and
                  the listener's cut, lean or not. The house answer is untouched.
  join-public     POST /api/dj/join through the door answers {welcome,
                  listeners}: it spread the whole dj_state() into its answer.
  stream-*        GET /api/stream/state through the door answers aggregates:
                  it listed every other listener's address and token tail
                  (hls_listeners), the spool paths and the lanes' errors.
  ads-public      POST /api/listener/ads through the door answers {ok,
                  message}: `ad` is the gallery's record (the reference clip's
                  sample name and folder, queue ids, the written copy).
  A LINK THAT RAN OUT (2026-09-28: a remote listener "can't hear" - every
  share link but three had expired; a dead link got raw JSON on /tune/, a 401
  on the stream, and a page left open went silent without a word):
  tune-gone       /tune/{expired|revoked} draws LINK_GONE_HTML - one sentence,
                  LINK_GONE_SAY - with the same 403 and nothing about the link.
  link-road/door  GET /api/listen/link?t= (on the door, GET only): is the link
                  this page holds still honoured - {live, expires} or 403.
  page-*          the tune page (RADIO_PAGE_HTML) asks that road when any road
                  it uses answers 401/403 (api(): the state, the clock, the next
                  line, the picture; streamProbe(): the stream), at most every
                  15 s, and on a no puts LINK_GONE_SAY in place of the player
                  and stops asking; the camera's 403 is not a question. Three
                  days before the pass runs out it says so under the station
                  line, and when it runs out it asks the station at once.
  share-expired*  /api/share lists the links that ran out apart, in `expired`
                  (`links` stays live-only for every reader); panel-expired
                  draws them in the panel's share list marked EXPIRED, with a
                  cross that clears one.
  system3_runtime.py (RUNTIME_EDITS, the same tool pointed at that file):
  s3-listener-*   /api/system3/public/lines answers from _listener_compact():
                  no `topic` (for most roads it is the road's prompt - the news
                  podcast brief, the SCHEDULE (#843) entry, the memo's brief), an
                  obligated CTS step reads "the step as planned" (its label is
                  the running order's direction to the writer), a FAV pick reads
                  "a favourite" with no reel (the operator's own words), the
                  speaker box keeps its mode only (no material file names), the
                  SFX node keeps play/placement (no intent words), and only the
                  listener's decision families. _compact() - the desk's reading
                  for feed_lines and the glass - is unchanged, and the listener
                  cut keeps its own cache so the two never share an entry.

Contract (tools/cast_names2_patch.py's): EDITS = [(name, old, new, count)] is
the app.py list; --check <path> exits 0 ready / 2 applied / 1 missing (named);
--apply <path> is idempotent, asserts every anchor count, refuses a result that
does not parse, and writes LF only, atomically. plan() picks APP_EDITS or
RUNTIME_EDITS by the file it is given. Every anchor is unique, starts a line,
and is inside no other tool's stored text (checked against tools/*.py). Apply
AFTER tools/tune_messenger_patch.py (wave A, app.py sha1 f42f230659f9):

    python3 tools/public_door_projection_patch.py app.py --apply
    python3 tools/public_door_projection_patch.py system3_runtime.py --apply
"""
import ast
import os
import shutil
import sys
import tempfile
from pathlib import Path

MARK = "[public-door]"


# --- the gate: the door's mark is the only one ------------------------------------
GATE_OLD = '''        headers = [(k, v) for (k, v) in scope.get("headers") or []
                   if k.lower() != b"authorization"]
        headers.append((b"x-pinebox-public", b"1"))
'''
GATE_NEW = '''        # [public-door] ...and any x-pinebox-public the CALLER sent. The mark
        # below is appended LAST and Starlette's headers.get() answers with
        # the FIRST header of a name, so a caller who sent
        # "x-pinebox-public: 0" was the house to every `== "1"` check behind
        # this door - measured 2026-09-28: GET :8097/api/pinelink/frame.jpg
        # with that one header and no token answered 200 with the studio
        # camera. The door's own mark is the only one a handler can see.
        headers = [(k, v) for (k, v) in scope.get("headers") or []
                   if k.lower() not in (b"authorization", b"x-pinebox-public")]
        headers.append((b"x-pinebox-public", b"1"))
'''


# --- the listener's cut of the state, beside the lean one --------------------------
PUBLIC_OLD = '''    if isinstance(chat, list) and len(chat) > DJ_LEAN_CHAT:
        lean["chat"] = chat[-DJ_LEAN_CHAT:]
    return lean
'''
PUBLIC_NEW = PUBLIC_OLD + r'''

# --- [public-door] WHAT THE LISTENER DOOR MAY SEE OF THE STATE --------------
# "right now, anyone on the Tailscale Funnel can GET /api/dj through the
#  public listener door without a token. It returns the full dj_state():
#  476 KB, including standing orders, personas, prompts and traces. ...
#  find every field they read, allow exactly those, and nothing else."
#  (2026-09-28)
#
# The lean cut above is a DENY list on purpose: the house page must never be
# starved of a key it starts reading. The door is the other way round - a
# key added upstairs must NOT reach the open internet until somebody decides
# it should. So this is an ALLOW list of exactly what the listener page reads
# off /api/dj. RADIO_PAGE_HTML is the only public page that asks for it (one
# call, pollOnce); car-diag.js reads page globals and the DOM, sfx-tv.js does
# not mount on a page with a gallery stage, the slideshow is slideshow.css
# only, and tune-messenger.js reads voiceCurrentClip - none of them reads it.
#
#   build                    pineBuildWatch     reload when the code changed
#   reload_at                pineReloadWatch    an asked-for reload
#   on, paused               sync, paintPaused  the dot, the title, the wake
#   elapsed                  sync               the clock and the bar
#   listeners, station       sync               "N listeners · <station>"
#   server_ms, started_ms    sync -> retime     the record's anchor
#   now.id title artist art seconds url
#                            sync, retime, paintMediaSession
#   gallery_now.images       renderGallery
#   chat[-20:]  id ts text who
#                            patter, patterKey, patterRow, s3Ask
#
# Every value is a leaf (a string, a number, a bool or null), so a structure
# grown under an allowed name upstairs still stays in the house. A new read
# on the page is a new name here, deliberately
# (tests/test_public_door_projection.py fails until it is).
DJ_PUBLIC_KEYS = ("build", "reload_at", "on", "paused", "elapsed", "listeners",
                  "station", "server_ms", "started_ms")
DJ_PUBLIC_NOW = ("id", "title", "artist", "art", "seconds", "url")
DJ_PUBLIC_CHAT = ("id", "ts", "text", "who")
# /api/stream/state through the door (no public page reads it; a repair rung
# only asks whether the door answers): whether the stream is up and how many
# are on it. Never hls_listeners (every listener's address and token tail),
# listener_rows, recent_sessions, the spool paths or the lanes' errors.
STREAM_PUBLIC_KEYS = ("running", "listeners", "mp3_listeners", "hls_active",
                      "bitrate", "join_burst_s", "title", "artist",
                      "up_seconds", "produced_seconds")


def dj_public_leaf(value: Any) -> Any:
    """[public-door] A value the door may pass: a leaf, never a structure."""
    return value if value is None or isinstance(value, (str, int, float, bool)) else None


def dj_state_public(state: dict[str, Any]) -> dict[str, Any]:
    """[public-door] dj_state() as the listener door answers it: the allow
    list above and nothing else, lean or not."""
    out: dict[str, Any] = {k: dj_public_leaf(state.get(k))
                           for k in DJ_PUBLIC_KEYS if k in state}
    now = state.get("now")
    out["now"] = ({k: dj_public_leaf(now[k]) for k in DJ_PUBLIC_NOW if k in now}
                  if isinstance(now, dict) else None)
    shown = state.get("gallery_now")
    names = shown.get("images") if isinstance(shown, dict) else None
    out["gallery_now"] = ({"images": [n for n in names if isinstance(n, str) and n]}
                          if isinstance(names, list) else None)
    chat = state.get("chat")
    out["chat"] = [{k: dj_public_leaf(row[k]) for k in DJ_PUBLIC_CHAT if k in row}
                   for row in (chat[-DJ_LEAN_CHAT:] if isinstance(chat, list) else [])
                   if isinstance(row, dict)]
    return out


# --- [public-door] A LINK THAT RAN OUT ---------------------------------------
# 2026-09-28, a remote listener "can't hear": every share link but three had
# expired (/api/share mints 168 h), and what a listener holding one got was a
# raw JSON 403 on /tune/, a 401 on the stream, and - on a page left open past
# the expiry - silence with no word at all. One sentence now, the same
# wherever a listener meets it: the page /tune/ draws for a dead link
# (LINK_GONE_HTML, still a 403), and the tune page's own notice when a road
# stops honouring its link (listen_link_api says whether it is dead).
# Expired and revoked are one answer: the page says nothing else about it.
LINK_GONE_SAY = "This link has expired - ask the station for a new one."
LINK_GONE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="robots" content="noindex">
<title>Pine Box FM</title>
<style>
  :root { color-scheme: dark; }
  html, body { margin: 0; min-height: 100%; background: #04060b; color: #e8eef2;
    font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
  main { min-height: 100vh; box-sizing: border-box; padding: 24px 16px;
    display: flex; flex-direction: column; align-items: center;
    justify-content: center; text-align: center; }
  h1 { margin: 0 0 14px; font-size: 18px; letter-spacing: .16em;
    text-transform: uppercase; color: #65c7da; }
  p { margin: 0 0 8px; max-width: 26em; }
  .muted { color: #8fa0ad; font-size: 14px; }
</style>
</head>
<body>
<main>
  <h1>Pine Box FM</h1>
  <p id="linkGone">__SAY__</p>
  <p class="muted">Whoever sent it to you can make you a fresh one.</p>
</main>
</body>
</html>
""".replace("__SAY__", LINK_GONE_SAY)
'''


# --- /api/dj: the token and the cut through the door -------------------------------
ROUTE_SIG_OLD = '''@app.get("/api/dj")
async def dj_status(
    request: Request,
    listener: str = "",
    lean: str = "",
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    require_read_auth(authorization)
'''
ROUTE_SIG_NEW = '''@app.get("/api/dj")
async def dj_status(
    request: Request,
    listener: str = "",
    lean: str = "",
    t: str = "",
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    # [public-door] Through the listener door this is a LISTENER's road:
    # the tune-in token, as every other road of the page asks (the door
    # strips Authorization, so require_read_auth there was open to anyone
    # while reads are unlocked; the page's api() sends ?t= on every call),
    # and the door's own cut of the state below. The house is unchanged.
    public = request.headers.get("x-pinebox-public") == "1"
    if public:
        require_listen_auth(t, authorization)
    else:
        require_read_auth(authorization)
'''

ROUTE_TAIL_OLD = '''    state = dj_state()
    # A string, not a bool: FastAPI would 422 a listener who sent
    # anything unexpected, and this is the page's only status route.
'''
ROUTE_TAIL_NEW = '''    state = dj_state()
    if public:                                            # [public-door]
        return dj_state_public(state)
    # A string, not a bool: FastAPI would 422 a listener who sent
    # anything unexpected, and this is the page's only status route.
'''


# --- POST /api/dj/join spread the whole state into its answer ----------------------
JOIN_OLD = '''    return {"welcome": line, "listeners": _radio_listeners(), **dj_state()}
'''
JOIN_NEW = '''    if request.headers.get("x-pinebox-public") == "1":   # [public-door]
        # The page reads `welcome` off this answer. The rest is the house
        # panel's dj_state() - the booth's prompts, personas and traces.
        return {"welcome": line, "listeners": _radio_listeners()}
    return {"welcome": line, "listeners": _radio_listeners(), **dj_state()}
'''


# --- GET /api/stream/state listed every listener --------------------------------
STREAM_SIG_OLD = '''async def station_stream_state(
    t: str = "",
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
'''
STREAM_SIG_NEW = '''async def station_stream_state(
    request: Request,
    t: str = "",
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
'''

STREAM_RET_OLD = '''    require_listen_auth(t, authorization)
    return STATION_STREAM.state()
'''
STREAM_RET_NEW = '''    require_listen_auth(t, authorization)
    state = STATION_STREAM.state()
    if request.headers.get("x-pinebox-public") == "1":   # [public-door]
        # A tune-in link is anybody's: through the door, whether the stream
        # is up and how many are on it - never hls_listeners (each
        # listener's address and token tail), the sessions, the spool paths
        # or the lanes' errors (STREAM_PUBLIC_KEYS).
        return {k: dj_public_leaf(state[k]) for k in STREAM_PUBLIC_KEYS if k in state}
    return state
'''


# --- POST /api/listener/ads handed back the gallery's record -----------------------
ADS_OLD = '''    message, ad = await voice_ad_render(goal)
    return {"ok": True, "message": message, "ad": ad}
'''
ADS_NEW = '''    message, ad = await voice_ad_render(goal)
    if request.headers.get("x-pinebox-public") == "1":   # [public-door]
        # The page shows `message`. `ad` is the gallery's record - the
        # reference clip's sample name and folder, the queue ids, the
        # written copy - and stays in the house.
        return {"ok": True, "message": message}
    return {"ok": True, "message": message, "ad": ad}
'''


# --- a link that ran out: the page, the question, the list --------------------------
TUNE_GONE_OLD = '''    scope = token_scope(token)
    if not scope:
        raise HTTPException(
            status_code=403,
            detail="That tune-in link has expired or been revoked.")
'''
TUNE_GONE_NEW = '''    scope = token_scope(token)
    if not scope:
        # [public-door] a person holding a dead link gets a page that says
        # so in one sentence (LINK_GONE_HTML), not raw JSON: the same 403,
        # and nothing about the link - expired and revoked read alike.
        return HTMLResponse(LINK_GONE_HTML, status_code=403,
                            headers={"Cache-Control": "no-store",
                                     "Pragma": "no-cache"})
'''

LINK_ROAD_OLD = '''        headers={"Cache-Control": "no-store, no-cache, must-revalidate",
                 "Pragma": "no-cache"})


@app.post("/api/dj/shout")
'''
LINK_ROAD_NEW = '''        headers={"Cache-Control": "no-store, no-cache, must-revalidate",
                 "Pragma": "no-cache"})


@app.get("/api/listen/link")
async def listen_link_api(t: str = "") -> Response:
    """[public-door] Is the tune-in link this page holds still honoured?

    The tune page asks when a road it uses answers 401 or 403 (the stream,
    the clock, the state, the next line, the picture) and puts
    LINK_GONE_SAY in place of the player only on a no from here: one road
    refusing for its own reasons - the camera for an unticked listener, a
    lock on reads - is not a dead link. It answers about the caller's own
    link and nothing else: live and when it runs out (the first field of
    the pass the caller already holds), or 403."""
    if not (t and token_scope(t)):
        return Response(content=json.dumps({"live": False, "say": LINK_GONE_SAY}),
                        status_code=403, media_type="application/json",
                        headers={"Cache-Control": "no-store"})
    try:
        expires = int(str(t).split(".", 1)[0])
    except ValueError:
        expires = 0
    return Response(content=json.dumps({"live": True, "expires": expires}),
                    media_type="application/json",
                    headers={"Cache-Control": "no-store"})


@app.post("/api/dj/shout")
'''

LINK_DOOR_OLD = '''    if method == "POST":
        return path in _PUBLIC_POST
    return False


class PublicListenerGate:
'''
LINK_DOOR_NEW = '''    if method == "POST":
        return path in _PUBLIC_POST
    return False


# [public-door] the tune page's own question - is my link still honoured?
# (listen_link_api). GET only; it answers about the caller's link alone.
_PUBLIC_GET |= {"/api/listen/link"}


class PublicListenerGate:
'''

SHARE_LOOP_OLD = '''    now = time.time()
    out = []
    for tag, row in (rows.get("links") or {}).items():
        left = float(row.get("expires") or 0) - now
        if left <= 0:
            continue
'''
SHARE_LOOP_NEW = '''    now = time.time()
    out = []
    gone = []                                             # [public-door]
    for tag, row in (rows.get("links") or {}).items():
        left = float(row.get("expires") or 0) - now
        if left <= 0:
            # [public-door] ...listed apart, and marked. A link that stopped
            # opening used to leave this list without a word: on 2026-09-28
            # "a listener", "the radio" and "the car" had run out 6-35 days
            # earlier and nothing here said so. No url: it opens nothing.
            gone.append({"tag": tag, "label": row.get("label") or "",
                         "expires": int(row.get("expires") or 0),
                         "expired": True,
                         "hours_ago": round(-left / 3600, 1),
                         "scope": row.get("scope") or "listen",
                         "for": str(row.get("for") or "")})
            continue
'''

SHARE_RETURN_OLD = '''    return {"links": sorted(out, key=lambda r: -r["expires"])}
'''
SHARE_RETURN_NEW = '''    return {"links": sorted(out, key=lambda r: -r["expires"]),
            # [public-door] the ones that ran out, newest first - apart from
            # `links`, which every reader takes as live (the desk's public
            # link, the "open the station" button's pick, the header dot).
            "expired": sorted(gone, key=lambda r: -r["expires"])[:40]}
'''

PANEL_EXPIRED_OLD = '''    if (!(got.links || []).length) {
      live.appendChild(el("div", "muted", "No links out."));
      live.lastChild.style.fontSize = "11px";
    }
'''
PANEL_EXPIRED_NEW = '''    if (!(got.links || []).length) {
      live.appendChild(el("div", "muted", "No links out."));
      live.lastChild.style.fontSize = "11px";
    }
    /* [public-door] AND THE LINKS THAT RAN OUT, MARKED SO. They used to
     * leave this list without a word, so a link that had quietly expired
     * looked like one never made - while the person holding it heard
     * nothing. The cross clears one for good. */
    (got.expired || []).forEach((l) => {
      const line = el("div", "phrase-row", "");
      line.dataset.expired = "1";
      line.style.cssText = "align-items:baseline;gap:8px;opacity:.72";
      const hours = Number(l.hours_ago || 0);
      const days = Math.floor(hours / 24);
      const ago = days >= 1 ? days + (days === 1 ? " day" : " days") + " ago"
        : Math.max(1, Math.round(hours)) + "h ago";
      const mark = el("span", "", "EXPIRED");
      mark.style.cssText = "font-size:9px;font-weight:700;letter-spacing:.08em;"
        + "color:#ffb27a;border:1px solid #6b4a2c;border-radius:4px;padding:0 4px";
      const name = el("span", "", (l.label || "a link") + " \\u00b7 expired " + ago
        + (l.scope === "full" ? " \\u00b7 full access" : ""));
      name.style.cssText = "flex:1;font-size:11px;text-decoration:line-through";
      name.title = "This link no longer opens. Make a new one for whoever had it.";
      const kill = el("button", "", "\\u2715");
      kill.style.fontSize = "11px";
      kill.title = "Clear this expired link from the list";
      kill.onclick = async () => {
        try {
          await api("/api/share/revoke", {method: "POST",
            body: JSON.stringify({tag: l.tag})});
          drawLinks();
        } catch (e) {}
      };
      line.appendChild(mark); line.appendChild(name); line.appendChild(kill);
      live.appendChild(line);
    });
'''

# --- the tune page: say it, before and after ------------------------------------
PAGE_API_HEAD_OLD = '''async function api(path, options = {}) {
  let url = path;
  if (GUEST) {
'''
PAGE_API_HEAD_NEW = '''async function api(path, options = {}) {
  /* [public-door] once the station has said this page's link is dead,
   * nothing more is asked of it: the loops tick on, the network is left
   * alone (linkGoneShow). */
  if (linkGone) throw new Error(LINK_GONE_SAY);
  let url = path;
  if (GUEST) {
'''

PAGE_API_FETCH_OLD = '''    const response = await fetch(url, _sent);
    const data = await response.json().catch(() => ({}));
'''
PAGE_API_FETCH_NEW = '''    const response = await fetch(url, _sent);
    /* [public-door] a road that no longer honours this page's link: ask
     * the station whether the link itself is dead (linkSuspect) rather
     * than fail on in silence. The camera answers 403 to a live link it
     * was not shared with, so its answers are not a question. */
    if (GUEST && (response.status === 401 || response.status === 403)
        && String(path).indexOf("/api/pinelink/") !== 0) linkSuspect(path);
    const data = await response.json().catch(() => ({}));
'''

PAGE_PROBE_OLD = '''    carMark("stream_probe", {why: why, status: r.status, ms: Date.now() - now,
                             online: navigator.onLine, road: currentRoad()});
'''
PAGE_PROBE_NEW = '''    carMark("stream_probe", {why: why, status: r.status, ms: Date.now() - now,
                             online: navigator.onLine, road: currentRoad()});
    /* [public-door] the stream refusing the link is the loudest sign it
     * has run out - and an <audio> error never says so by itself. */
    if (r.status === 401 || r.status === 403) linkSuspect("stream");
'''

PAGE_BLOCK_OLD = '''/* #632: the room can shout back. A reaction is a mood the show can feel; a
 * line is read out on air and answered by name. */
function shout(react) {
'''
PAGE_BLOCK_NEW = r'''/* [public-door] THE LINK THAT RAN OUT.
 *
 * "a tune page left open past its link's expiry just goes SILENT, with no
 *  message" (2026-09-28). A tune-in link carries its own expiry (the first
 * field of the pass) and the station stops honouring it then - or at once,
 * when it is revoked. So:
 *   - a few days before, the page says so, gently (linkNotice);
 *   - when a road the page uses answers 401 or 403 - the stream, the clock,
 *     the state, the next line, the picture - it asks the station whether
 *     the link itself is dead (GET /api/listen/link, at most every 15 s),
 *     and only a no from there takes the player off the page and puts the
 *     station's own sentence in its place (linkGoneShow);
 *   - when the pass runs out by its own clock the station is asked too, so
 *     a page nobody is touching still says it.
 * `var` on purpose: api() reads linkGone, and code that runs before this
 * block calls api(). */
var LINK_GONE_SAY = "This link has expired - ask the station for a new one.";
var LINK_WARN_DAYS = 3;
var linkGone = false;
var linkAskedAt = 0;

function linkExpiresMs() {
  if (!GUEST) return 0;
  const m = /^(\d{9,11})\./.exec(String(KEY || ""));
  return m ? Number(m[1]) * 1000 : 0;
}

function linkSuspect(why) {
  if (!GUEST || linkGone) return;
  const now = Date.now();
  if (now - Number(linkAskedAt || 0) < 15000) return;
  linkAskedAt = now;
  fetch("/api/listen/link?t=" + encodeURIComponent(KEY), {cache: "no-store"})
    .then((r) => { if (r.status === 401 || r.status === 403) linkGoneShow(why); })
    .catch(() => { /* no answer is not a dead link */ });
}

function linkGoneShow(why) {
  if (linkGone) return;
  linkGone = true;
  try { if (playing) tune(); } catch (e) {}
  try { stopEverything(); } catch (e) {}
  try { carMark("link_gone", {why: String(why || "").slice(0, 80)}); } catch (e) {}
  const set = document.querySelector(".set");
  if (set) {
    Array.from(set.children).forEach((n) => {
      if (n.tagName !== "H1") n.style.setProperty("display", "none", "important");
    });
    const box = document.createElement("div");
    box.id = "linkGone";
    box.setAttribute("role", "alert");
    box.style.cssText = "margin:28px 0 12px;font-size:17px;line-height:1.5";
    box.textContent = LINK_GONE_SAY;
    const more = document.createElement("div");
    more.style.cssText = "margin-top:8px;font-size:13px;opacity:.7";
    more.textContent = "Whoever sent it to you can make you a fresh one.";
    box.appendChild(more);
    set.appendChild(box);
  }
  ["upFab", "upSheet", "carToggle"].forEach((id) => {
    const n = document.getElementById(id);
    if (n) n.style.setProperty("display", "none", "important");
  });
  try { if ("mediaSession" in navigator) navigator.mediaSession.playbackState = "none"; } catch (e) {}
}

function linkNotice() {
  const at = linkExpiresMs();
  let box = document.getElementById("linkSoon");
  const left = at - Date.now();
  if (!at || linkGone || left <= 0 || left > LINK_WARN_DAYS * 86400000) {
    if (box) box.remove();
    return;
  }
  if (!box) {
    const sub = document.getElementById("sub");
    if (!sub || !sub.parentNode) return;
    box = document.createElement("div");
    box.id = "linkSoon";
    box.setAttribute("role", "status");
    box.style.cssText = "margin:4px 0 10px;font-size:13px;line-height:1.45;color:#e8c27a";
    sub.parentNode.insertBefore(box, sub.nextSibling);
  }
  const days = Math.floor(left / 86400000);
  const hours = Math.floor(left / 3600000);
  const when = days >= 1 ? days + (days === 1 ? " day" : " days")
    : hours >= 1 ? hours + (hours === 1 ? " hour" : " hours") : "less than an hour";
  box.textContent = "This link stops working in " + when
    + " - ask the station for a new one before then.";
}

try {
  linkNotice();
  setInterval(() => { try { linkNotice(); } catch (e) {} }, 600000);
  const due = linkExpiresMs() - Date.now();
  if (due > 0 && due < 2147000000) {
    setTimeout(() => { try { linkAskedAt = 0; linkSuspect("expired"); } catch (e) {} }, due + 2000);
  }
} catch (e) { /* the page plays on */ }

/* #632: the room can shout back. A reaction is a mood the show can feel; a
 * line is read out on air and answered by name. */
function shout(react) {
'''


# --- system3_runtime.py: the listener feed's own cut of a round --------------------
LISTENER_METHODS_OLD = '''    def public_lines(self, ids):
'''
LISTENER_METHODS_NEW = r'''    # [public-door] THE LISTENER DOOR'S CUT OF A ROUND. /api/system3/public/lines
    # answers anybody holding a tune-in link, and _compact() is the DESK's
    # reading (feed_lines, the glass). Measured 2026-09-28, it carried the
    # round's `topic` - for most roads the road's own prompt ("A news moment
    # between records, and it runs like a late-night podcast: ...", the
    # SCHEDULE (#843) entry, the memo's brief, the caller's scene) - an
    # obligated CTS step's label, which is the running order's direction to
    # the writer, a FAV pick's label and reel, which are the operator's own
    # favourites, the speaker box's material file names and the SFX node's
    # intent words. The listener keeps the dice - family, d100, where it
    # landed, the reel it rolled through, the rule - and the turn's shape, cut
    # the way tune_messenger.py cuts the same record for the Messenger.
    LISTENER_FAMILIES = frozenset({"CTS", "ES", "RS", "IRS", "FL", "SPEAKERBOX", "SFX", "SFXGUY",
                                   "TOPIC", "TRACK_TALK", "FAV", "TEMPER", "INTERJECT", "MENTION",
                                   "SHOCK", "LINE"})

    def _listener_compact(self, conv):
        """[public-door] _compact() as the listener door may carry it."""
        comp = self._compact(conv)
        events = {e.get("event_id"): e for e in conv.get("decision_events") or [] if isinstance(e, dict)}
        turns = {}
        for tid, turn in (comp.get("turns") or {}).items():
            rolls = []
            for roll in turn.get("rolls") or []:
                fam = str(roll.get("family") or "")
                if fam not in self.LISTENER_FAMILIES:
                    continue
                ev = events.get(roll.get("event_id")) or {}
                sel = ev.get("selected") if isinstance(ev.get("selected"), dict) else {}
                roll = dict(roll)
                if fam == "FAV" and str(sel.get("id") or "") not in ("", "NONE"):
                    roll.update(label="a favourite", category="", reel=[])
                elif fam == "CTS" and not any(isinstance(st, dict) and st.get("stage") in ("item", "mode")
                                              for st in ev.get("stages") or []):
                    roll.update(label="the step as planned", category="", reel=[])
                rolls.append(roll)
            turns[tid] = dict(turn, rolls=rolls,
                              speakerbox=[{"mode": sb.get("mode")} for sb in turn.get("speakerbox") or []],
                              sfx={k: (turn.get("sfx") or {}).get(k) for k in ("play", "placement")})
        return {"conversation_id": comp.get("conversation_id"), "mode": comp.get("mode"),
                "road": comp.get("road"), "turns": turns}

    def public_lines(self, ids):
'''

LISTENER_CACHE_OLD = '''        reader thread only; the cache is that thread's alone."""
        cache = self.__dict__.setdefault("_public_cache", collections.OrderedDict())
'''
LISTENER_CACHE_NEW = '''        reader thread only; the cache is that thread's alone. [public-door]
        Its own cache: _compact_cached() keeps the desk's reading in
        _public_cache, and a listener must never be answered out of it."""
        cache = self.__dict__.setdefault("_listener_cache", collections.OrderedDict())
'''

LISTENER_BUILD_OLD = '''                hit = (time.time(), self._compact(conv) if conv else None)
'''
LISTENER_BUILD_NEW = '''                hit = (time.time(), self._listener_compact(conv) if conv else None)   # [public-door]
'''

LISTENER_TOPIC_OLD = '''                        "road": comp["road"], "topic": comp["topic"],
                        "turn": comp["turns"].get(str(got.get("turn_id") or ""))})
'''
LISTENER_TOPIC_NEW = '''                        "road": comp["road"],   # [public-door] no topic: the road's prompt
                        "turn": comp["turns"].get(str(got.get("turn_id") or ""))})
'''


# (name, old, new, count)
APP_EDITS = [
    ("gate", GATE_OLD, GATE_NEW, 1),
    ("dj-public", PUBLIC_OLD, PUBLIC_NEW, 1),
    ("dj-route-sig", ROUTE_SIG_OLD, ROUTE_SIG_NEW, 1),
    ("dj-route-tail", ROUTE_TAIL_OLD, ROUTE_TAIL_NEW, 1),
    ("join-public", JOIN_OLD, JOIN_NEW, 1),
    ("stream-sig", STREAM_SIG_OLD, STREAM_SIG_NEW, 1),
    ("stream-public", STREAM_RET_OLD, STREAM_RET_NEW, 1),
    ("ads-public", ADS_OLD, ADS_NEW, 1),
    ("tune-gone", TUNE_GONE_OLD, TUNE_GONE_NEW, 1),
    ("link-road", LINK_ROAD_OLD, LINK_ROAD_NEW, 1),
    ("link-door", LINK_DOOR_OLD, LINK_DOOR_NEW, 1),
    ("share-expired", SHARE_LOOP_OLD, SHARE_LOOP_NEW, 1),
    ("share-expired-list", SHARE_RETURN_OLD, SHARE_RETURN_NEW, 1),
    ("panel-expired", PANEL_EXPIRED_OLD, PANEL_EXPIRED_NEW, 1),
    ("page-api-gone", PAGE_API_HEAD_OLD, PAGE_API_HEAD_NEW, 1),
    ("page-api-ask", PAGE_API_FETCH_OLD, PAGE_API_FETCH_NEW, 1),
    ("page-stream-ask", PAGE_PROBE_OLD, PAGE_PROBE_NEW, 1),
    ("page-link", PAGE_BLOCK_OLD, PAGE_BLOCK_NEW, 1),
]
RUNTIME_EDITS = [
    ("s3-listener-methods", LISTENER_METHODS_OLD, LISTENER_METHODS_NEW, 1),
    ("s3-listener-cache", LISTENER_CACHE_OLD, LISTENER_CACHE_NEW, 1),
    ("s3-listener-build", LISTENER_BUILD_OLD, LISTENER_BUILD_NEW, 1),
    ("s3-listener-topic", LISTENER_TOPIC_OLD, LISTENER_TOPIC_NEW, 1),
]
EDITS = APP_EDITS  # the integrate.py contract reads EDITS for app.py


def plan(text):
    """The edits for this file: system3_runtime.py is told by its public_lines
    method (the patched one keeps the line), anything else is app.py."""
    if "    def public_lines(self, ids):\n" in text and "class " in text and "RADIO_PAGE_HTML" not in text:
        return list(RUNTIME_EDITS)
    return list(APP_EDITS)


def state_of(text, old, new, count):
    n_new = text.count(new)
    n_old = text.count(old)
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


def _read(path):
    return Path(path).read_bytes().decode("utf-8").replace("\r\n", "\n")


def apply(path):
    path = Path(path)
    text = _read(path)
    applied, missing = check(text)
    edits = plan(text)
    if applied == len(edits):
        return 2
    if missing:
        for m in missing:
            print("missing:", m)
        return 1
    for name, old, new, count in edits:
        if state_of(text, old, new, count) == "applied":
            continue
        assert text.count(old) == count, "%s: anchor found %d times" % (name, text.count(old))
        text = text.replace(old, new)
        assert state_of(text, old, new, count) == "applied", "%s did not land" % name
    assert "\r" not in text
    try:
        ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        print("REFUSED: the patched file does not parse: %s" % exc)
        return 1
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(text.encode("utf-8"))
        try:
            shutil.copymode(str(path), tmp)
        except OSError:
            pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return 0


def main(argv):
    do_apply = "--apply" in argv
    target = next((a for a in argv if not a.startswith("--")), "app.py")
    if not Path(target).is_file():
        print("no such file:", target)
        return 1
    if do_apply:
        code = apply(target)
        print({0: "APPLIED", 1: "ANCHORS MISSING - nothing written", 2: "already applied"}[code])
        return code
    text = _read(target)
    applied, missing = check(text)
    total = len(plan(text))
    if missing:
        for m in missing:
            print("missing:", m)
        print("%d of %d applied" % (applied, total))
        return 1
    if applied == total:
        print("already applied (%d edits)" % total)
        return 2
    print("ready: %d edits, %d already in" % (total, applied))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
