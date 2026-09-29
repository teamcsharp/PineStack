"""PINESTREAM - the PineTab's or the Pine app's own screen, as a small picture
in the corner of the listeners' page.  [pinestream]

"add a section here for enabling a pip stream of the pinetab / pineapp to be
 streamed to the stream page. I want users able to enable and disable it at
 will like the pinecam and call it pinestream."        (operator, 2026-09-29)

THE ROAD, CHEAPEST FIRST.
  The screen being streamed encodes its own JPEGs and POSTs them here: the
  tablet natively (PineStreamPush.kt - a VirtualDisplay mirror into an
  ImageReader, on the same platform-signed CAPTURE_VIDEO_OUTPUT grant the
  rolling replay already uses, so no MediaProjection prompt), the desk in
  Electron's main process (pinestream-push.cjs, webContents.capturePage).
  One to five a second, at most 960 px wide. The station keeps ONE frame in
  memory and hands it out as it came: no encoder, no decoder, no disk, no
  thread, no timer. The DGX's heat budget belongs to the renders
  (pinned-memory-froze-the-box).

THE SWITCH IS THE MASTER. settings.stream_on lives with PineLive's settings,
  so the header switch rides /api/pinelive/settings - the same road as
  PineCam to live - and is remembered; PineLive counts its flips for the
  viewers' CRT. Off: every frame POST is answered keep:false (the source stops
  capturing at once), the held frame is dropped, frame.jpg is 404 and a
  viewer is told show:false. A viewer's own hide button only hides it on that
  one page.

PRIVATE. A source that is showing something it must not (a key field on the
  screen, the tablet asleep, the desk minimised) posts private=1 and no
  picture: the held frame is dropped at once and viewers see a veil saying so.

ROUTES (install):
  POST /api/pinestream/frame?source=pinetab|pineapp[&private=1&why=]
        house auth; body = one JPEG, or empty = "unchanged, still here".
        Answers {keep, on, source, fps, width, quality, say}.
  GET  /api/pinestream/state       house auth: status() for the panel
  GET  /api/pinestream/mine?t=     public: viewer() for this token
  GET  /api/pinestream/frame.jpg?t=|s=
        public with a live tune-in token; the house (reads open) with none;
        the panel's preview with the media signature `s`.
"""
from __future__ import annotations

import hmac
import threading
import time
from typing import Any, Callable

try:   # module level: the routes' annotations are resolved against these globals
    from fastapi import Header, HTTPException, Request
    from fastapi.responses import JSONResponse, Response
except Exception:  # noqa: BLE001  (a test without fastapi still imports the logic)
    Header = HTTPException = Request = JSONResponse = Response = None  # type: ignore

FRESH_S = 6.0            # a frame older than this is not live any more
MAX_BYTES = 700_000      # one JPEG; a 960 px screen at q90 is ~250 kB
VIEWER_S = 12.0          # a viewer who fetched within this is watching
SOURCES = {"pinetab": "the PineTab", "pineapp": "the Pine app"}
LIMITS = {"stream_fps": (1, 5, 2), "stream_width": (320, 960, 640),
          "stream_quality": (30, 90, 60)}
PREVIEW_KEY = "pinestream-preview"

def _placeholder() -> bytes:
    """What a private screen serves: PineLive's 160x90 dark frame."""
    try:
        import pinelive
        return bytes(pinelive.PLACEHOLDER_JPEG)
    except Exception:  # noqa: BLE001
        return b""


def jpeg_size(data: bytes) -> tuple[int, int]:
    """(width, height) from the first SOF marker, (0, 0) if there is none."""
    i = 2
    n = len(data)
    try:
        while i + 9 < n:
            if data[i] != 0xFF:
                i += 1
                continue
            m = data[i + 1]
            if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:
                i += 2
                continue
            seg = (data[i + 2] << 8) | data[i + 3]
            if m in (0xC0, 0xC1, 0xC2):
                return ((data[i + 7] << 8) | data[i + 8], (data[i + 5] << 8) | data[i + 6])
            i += 2 + seg
    except Exception:  # noqa: BLE001
        pass
    return (0, 0)


def clamp_choice(s: dict[str, Any]) -> dict[str, Any]:
    """The operator's choices, read defensively (settings may be older)."""
    out: dict[str, Any] = {"on": bool(s.get("stream_on"))}
    src = str(s.get("stream_source") or "pinetab")
    out["source"] = src if src in SOURCES else "pinetab"
    for key, (lo, hi, dflt) in LIMITS.items():
        try:
            v = int(round(float(s.get(key, dflt))))
        except Exception:  # noqa: BLE001
            v = dflt
        out[key.replace("stream_", "")] = max(lo, min(hi, v))
    return out


class PineStream:
    def __init__(self, settings: Callable[[], dict] | None = None,
                 flips: Callable[[], int] | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        self._settings_fn = settings
        self._flips_fn = flips
        self.clock = clock
        self.lock = threading.Lock()
        self.viewers: dict[str, float] = {}
        self.frames_total = 0
        self.sign: Callable[[str], str] = lambda key: ""
        self._reset()

    def _reset(self) -> None:
        self.jpeg = b""
        self.at = 0.0
        self.source = ""
        self.private = False
        self.why = ""
        self.frames = 0
        self.bytes = 0
        self.started = 0.0
        self.pushed_at = 0.0
        self.agent = ""
        self.size = (0, 0)

    # -- what the operator chose ------------------------------------------------
    def settings(self) -> dict[str, Any]:
        fn = self._settings_fn
        try:
            if fn is not None:
                return dict(fn() or {})
            import pinelive
            return dict(pinelive.PL.settings or {})
        except Exception:  # noqa: BLE001
            return {}

    def flips(self) -> int:
        try:
            if self._flips_fn is not None:
                return int(self._flips_fn() or 0)
            import pinelive
            return int(getattr(pinelive.PL, "stream_flips", 0) or 0)
        except Exception:  # noqa: BLE001
            return 0

    def choice(self) -> dict[str, Any]:
        return clamp_choice(self.settings())

    def _drop_if_off(self, on: bool) -> None:
        if not on and (self.jpeg or self.source):
            with self.lock:
                self._reset()

    # -- the source's road --------------------------------------------------------
    def accept(self, source: str, body: bytes, private: bool = False, why: str = "",
               agent: str = "") -> tuple[int, dict[str, Any]]:
        c = self.choice()
        now = self.clock()
        out = {"on": c["on"], "source": c["source"], "fps": c["fps"],
               "width": c["width"], "quality": c["quality"]}
        if not c["on"]:
            self._drop_if_off(False)
            return 200, dict(out, keep=False, say="PineStream is off - capture nothing")
        if source != c["source"]:
            return 200, dict(out, keep=False, say="PineStream is showing %s, not this screen"
                             % SOURCES[c["source"]])
        body = bytes(body or b"")
        if body:
            if len(body) > MAX_BYTES:
                return 413, dict(out, keep=True, say="a frame is at most %d kB" % (MAX_BYTES // 1000))
            if body[:2] != b"\xff\xd8" or body[-2:] != b"\xff\xd9":
                return 400, dict(out, keep=True, say="a frame is one whole JPEG")
        with self.lock:
            if self.source != source:
                self._reset()
                self.source = source
                self.started = now
            self.pushed_at = now
            self.agent = str(agent or "")[:80]
            if private:
                self.private = True
                self.why = str(why or "a private screen")[:120]
                self.jpeg = b""
                self.at = now
            elif body:
                self.private = False
                self.why = ""
                self.jpeg = body
                self.at = now
                self.frames += 1
                self.bytes += len(body)
                self.frames_total += 1
                self.size = jpeg_size(body)
            elif self.jpeg or self.private:
                self.at = now          # unchanged screen / still private: still here
        return 200, dict(out, keep=True, say="")

    # -- the viewers' road ----------------------------------------------------------
    def picture(self) -> str:
        """off | waiting | private | live - what a viewer would see now."""
        c = self.choice()
        if not c["on"]:
            self._drop_if_off(False)
            return "off"
        now = self.clock()
        with self.lock:
            if self.source != c["source"] or now - self.at > FRESH_S:
                return "waiting"
            if self.private:
                return "private"
            return "live" if self.jpeg else "waiting"

    def frame(self) -> tuple[bytes | None, str]:
        state = self.picture()
        if state == "private":
            return (_placeholder() or None), state
        if state != "live":
            return None, state
        with self.lock:
            return self.jpeg, state

    def seen(self, who: str) -> None:
        if not who:
            return
        now = self.clock()
        with self.lock:
            self.viewers[who] = now
            if len(self.viewers) > 64:
                for k in [k for k, at in self.viewers.items() if now - at > VIEWER_S]:
                    self.viewers.pop(k, None)

    def watching(self) -> int:
        now = self.clock()
        with self.lock:
            return sum(1 for at in self.viewers.values() if now - at <= VIEWER_S)

    def viewer(self, may: bool) -> dict[str, Any]:
        """What a tune page needs: whether to show the window, what is in it,
        and the switch's flips (so a page replays each one on its CRT)."""
        c = self.choice()
        state = self.picture() if may else "off"
        return {"show": bool(may and c["on"]), "state": state,
                "fps": c["fps"], "source": c["source"],
                "source_name": SOURCES[c["source"]],
                "why": self.why if state == "private" else "",
                "switch": {"on": c["on"], "flips": self.flips(), "yours": bool(may)}}

    def status(self) -> dict[str, Any]:
        """The panel's picture of it (house only)."""
        c = self.choice()
        state = self.picture()
        now = self.clock()
        with self.lock:
            age = round(now - self.at, 1) if self.at else None
            fresh = self.source == c["source"]
            out = {"on": c["on"], "source": c["source"], "source_name": SOURCES[c["source"]],
                   "fps": c["fps"], "width": c["width"], "quality": c["quality"],
                   "flips": self.flips(), "picture": state,
                   "private": bool(self.private and fresh), "why": self.why if fresh else "",
                   "frame_age": age if fresh else None,
                   "frames": self.frames if fresh else 0,
                   "kb": round(len(self.jpeg) / 1000.0, 1) if (fresh and self.jpeg) else 0,
                   "size": list(self.size) if fresh else [0, 0],
                   "agent": self.agent if fresh else "",
                   "since": self.started if fresh else 0}
        out["watching"] = self.watching()
        sig = ""
        try:
            sig = self.sign(PREVIEW_KEY)
        except Exception:  # noqa: BLE001
            sig = ""
        out["preview"] = ("/api/pinestream/frame.jpg?s=" + sig) if sig else ""
        return out


PS = PineStream()


def status() -> dict[str, Any]:
    try:
        return PS.status()
    except Exception:  # noqa: BLE001
        return {"on": False, "picture": "off"}


def mine_for(t: str, public: bool) -> dict[str, Any]:
    """The pinestream block of /api/pinelink/mine: the tune page's existing
    poll carries it, so PineStream adds no request to a listener's page."""
    try:
        if t:
            fn = _G.get("listen_ok")
            may = bool(fn(t)) if callable(fn) else False
        else:
            may = not public            # the house; its reads were checked by the caller
        ans = PS.viewer(may)
        ans["frame"] = "/api/pinestream/frame.jpg" + ("?t=" + t if t else "")
        return ans
    except Exception:  # noqa: BLE001
        return {"show": False, "state": "off", "switch": {"on": False, "flips": 0, "yours": False}}


_G: dict[str, Any] = {}


def install(app: Any, app_globals: dict[str, Any]) -> None:
    """Register the /api/pinestream routes. Nothing starts: no task, no
    thread, no timer - every cost here is paid per request."""
    global _G
    _G = app_globals

    def sign(key: str) -> str:
        fn = app_globals.get("media_sign")
        return str(fn(key)) if callable(fn) else ""

    PS.sign = sign

    def auth(authorization: str | None) -> None:
        app_globals["require_auth"](authorization)

    def read_auth(authorization: str | None) -> None:
        app_globals["require_read_auth"](authorization)

    def listen_ok(t: str) -> bool:
        fn = app_globals.get("listen_ok")
        return bool(fn(t)) if callable(fn) else False

    def tag_of(t: str) -> str:
        fn = app_globals.get("token_tag")
        try:
            return str(fn(t)) if callable(fn) else ""
        except Exception:  # noqa: BLE001
            return ""

    no_store = {"Cache-Control": "no-store"}

    @app.post("/api/pinestream/frame")
    async def pinestream_frame_post(request: Request, source: str = "", private: int = 0,
                                    why: str = "",
                                    authorization: str | None = Header(default=None)) -> Any:
        auth(authorization)
        body = await request.body()
        code, ans = PS.accept(source, body, bool(private), why,
                              request.headers.get("x-pinestream-agent", ""))
        return JSONResponse(ans, status_code=code, headers=no_store)

    @app.get("/api/pinestream/state")
    async def pinestream_state_api(authorization: str | None = Header(default=None)) -> Any:
        auth(authorization)
        return JSONResponse(PS.status(), headers=no_store)

    @app.get("/api/pinestream/mine")
    async def pinestream_mine_api(request: Request, t: str = "",
                                  authorization: str | None = Header(default=None)) -> Any:
        public = request.headers.get("x-pinebox-public") == "1"
        if not t and not public:
            read_auth(authorization)
        return JSONResponse(mine_for(t, public), headers=no_store)

    @app.get("/api/pinestream/frame.jpg")
    async def pinestream_frame_get(request: Request, t: str = "", s: str = "",
                                   authorization: str | None = Header(default=None)) -> Any:
        public = request.headers.get("x-pinebox-public") == "1"
        who = ""
        if t:
            if not listen_ok(t):
                raise HTTPException(status_code=403, detail="a live tune-in link is required")
            who = "t:" + (tag_of(t) or t[-12:])
        elif s and not public:
            want = sign(PREVIEW_KEY)
            if not (want and hmac.compare_digest(str(s), want)):
                raise HTTPException(status_code=403, detail="that preview link is not this station's")
        else:
            if public:
                raise HTTPException(status_code=403, detail="a tune-in link is required here")
            read_auth(authorization)
            who = "h:" + str(getattr(request.client, "host", "") or "")
        jpeg, state = PS.frame()
        if jpeg is None:
            return Response(status_code=404, headers=dict(no_store, **{"X-PineStream": state}))
        PS.seen(who)
        return Response(content=jpeg, media_type="image/jpeg",
                        headers=dict(no_store, **{"X-PineStream": state}))
