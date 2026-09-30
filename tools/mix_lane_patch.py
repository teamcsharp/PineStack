"""[mix-lane] A listener moving the tune page's sliders must not cut the audio.

2026-09-30 (#1418-#1420): a phone on the Funnel dragged its sliders four
times in a minute. Every position is its own ABR lane (one ffmpeg); a lane
asked for within HLS_LANE_BUSY_S (60 s) cannot be evicted, so the lanes the
phone had JUST left filled the cap of six, the fourth mix was REFUSED, and the
master route spun its 15 s wait for a master that could never come - the
phone gave up at 8 s and sat on an empty buffer. And every applied change
emptied the player before the new lane existed.

  station_stream  StationStream.hls_release(): retire the lane a listener left.
  app.py          ONE LANE PER LISTENER (token tail + address): moving to a new
                  mix releases the lane it left, unless another listener is on
                  it - BEFORE the new lane is admitted, so there is a slot.
                  A refused lane answers 503 at once, with the reason.
  tune page       the new lane is asked for FIRST while the current mix keeps
                  playing; the player swaps only when it answers, and a refusal
                  keeps the old mix playing with a note.
Anchor-asserted; run on the host."""
import ast
import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".")


def sub(text, old, new, name):
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"anchor {name}: found {n} times")
    return text.replace(old, new)


# ------------------------------------------------------ station_stream.py --
q = ROOT / "station_stream.py"
s = q.read_text()
if "[mix-lane]" in s:
    raise SystemExit("station_stream.py already patched")
s = sub(s, '''    def hls_existing(self, bitrate: Any, mix: Any = None,
''', '''    def hls_release(self, mix: Any = None, split: bool = False,
                    why: str = "its listener moved to another mix") -> bool:
        """[mix-lane] Retire the lane a listener has just LEFT for another mix.

        Left alone it stays "busy" for HLS_LANE_BUSY_S and held for ten
        minutes, so a thumb dragging a slider fills HLS_MAX_LANES with lanes
        nobody is on and the next mix is refused. Never the default lane,
        never a warm one. True when a lane went."""
        key = self._hls_key(split, mix)
        if key == _DEFAULT_LANE:
            return False
        with self._lock:
            lane = self._hls.get(key)
            if lane is None or lane.warm:
                return False
            self._hls_retire(key, lane, time.time(), why)
        return True

    def hls_existing(self, bitrate: Any, mix: Any = None,
''', "release")
ast.parse(s)

# ---------------------------------------------------------------- app.py --
p = ROOT / "app.py"
a = p.read_text()
if "[mix-lane]" in a:
    raise SystemExit("app.py already patched")
a = sub(a, '''def _hls_query(token: str, mix: Any = None) -> str:
''', '''# [mix-lane] ONE LANE PER LISTENER. Who is on which personal mix, keyed by
# the token's tail and the address (a share link is often passed to several
# people, so the token alone is not a listener).
_HLS_LISTENER_MIX: dict[str, tuple[tuple[int, int, int], float]] = {}
HLS_LISTENER_MIX_KEEP_S = 6 * 3600.0


def _hls_mix_move(token: str, request: Request, mix: Any) -> None:
    """[mix-lane] This listener asked for `mix`; if it was on another personal
    mix a moment ago, that lane goes NOW - unless another listener is on it.
    Called before the new lane is admitted, so the slot it frees is the one
    the new lane takes. Never raises: a failure here must not cost the stream."""
    try:
        want = tuple(int(x) for x in mix)
        addr = ""
        try:
            addr = str(request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
            addr = addr or str(getattr(request.client, "host", "") or "")
        except Exception:  # noqa: BLE001
            addr = ""
        who = "%s|%s" % (str(token or "")[-12:], addr)
        now = time.time()
        prev = _HLS_LISTENER_MIX.get(who)
        _HLS_LISTENER_MIX[who] = (want, now)
        if len(_HLS_LISTENER_MIX) > 512:
            for k, (_m, at) in list(_HLS_LISTENER_MIX.items()):
                if now - at > HLS_LISTENER_MIX_KEEP_S:
                    _HLS_LISTENER_MIX.pop(k, None)
        if not prev or prev[0] == want:
            return
        old = prev[0]
        for k, (m, at) in _HLS_LISTENER_MIX.items():
            if k != who and m == old and now - at < HLS_LISTENER_MIX_KEEP_S:
                return                      # somebody else is on that mix
        fn = getattr(STATION_STREAM, "hls_release", None)
        if callable(fn):
            fn(mix=old)
    except Exception:  # noqa: BLE001
        pass


def _hls_refused(enc: Any) -> str:
    """[mix-lane] Why this lane was refused, or "". A refused lane is retired
    before it starts; waiting on it is fifteen seconds of nothing."""
    lane = getattr(enc, "lane", None)
    if lane is not None and getattr(lane, "retired", False):
        return str(getattr(lane, "last_error", "") or "the station is full")
    return ""


def _hls_query(token: str, mix: Any = None) -> str:
''', "helpers")
a = sub(a, '''    from station_stream import listener_mix
    personal_mix = listener_mix(mix)
    _t0 = time.monotonic()
''', '''    from station_stream import listener_mix
    personal_mix = listener_mix(mix)
    _t0 = time.monotonic()
    _hls_mix_move(t, request, personal_mix)                 # [mix-lane]
''', "route-move")
a = sub(a, '''        master_path = None
        try:
            STATION_STREAM.hls(br, mix=personal_mix)
            for _ in range(60):
''', '''        master_path = None
        _refused = ""
        try:
            _refused = _hls_refused(STATION_STREAM.hls(br, mix=personal_mix))
            for _ in range(0 if _refused else 60):             # [mix-lane]
''', "route-master")
a = sub(a, '''        except Exception:  # noqa: BLE001
            master_path = None
        master_raw = ""
''', '''        except Exception:  # noqa: BLE001
            master_path = None
        if _refused:                                         # [mix-lane]
            raise HTTPException(
                status_code=503, headers={"Retry-After": "5"},
                detail="that mix could not start: " + _refused)
        master_raw = ""
''', "route-refused")
a = sub(a, '''    enc = STATION_STREAM.hls(br, mix=personal_mix)
    # Wait for a modest initial HLS runway rather than handing a phone a
''', '''    enc = STATION_STREAM.hls(br, mix=personal_mix)
    if _hls_refused(enc):                                    # [mix-lane]
        raise HTTPException(
            status_code=503, headers={"Retry-After": "5"},
            detail="that mix could not start: " + _hls_refused(enc))
    # Wait for a modest initial HLS runway rather than handing a phone a
''', "route-single")
a = sub(a, '''  mixRestart = setTimeout(() => {
    mixRestart = null;
    if (!streamMode || !playing || mixWanted === streamMixApplied) return;
    startStream();
  }, 1500);
}
''', '''  mixRestart = setTimeout(() => {
    mixRestart = null;
    if (!streamMode || !playing || mixWanted === streamMixApplied) return;
    /* [mix-lane] ASK FOR THE NEW LANE FIRST. startStream() empties the
     * player; doing that before the new lane exists was a cut on every
     * slider move, and silence when the station could not start it. The
     * current mix keeps playing until the station has answered; a refusal
     * keeps it playing and says so. */
    const want = mixWanted;
    const ctl = (typeof AbortController === "function") ? new AbortController() : null;
    const guard = setTimeout(() => { try { ctl && ctl.abort(); } catch (e) {} }, 20000);
    fetch(streamUrl(), {cache: "no-store", signal: ctl ? ctl.signal : undefined})
      .then((r) => {
        clearTimeout(guard);
        if (!streamMode || !playing || personalMix() !== want) return;
        if (r.ok) { startStream(); return; }
        mixNotApplied("the station could not start that mix (" + r.status + ")");
      })
      .catch(() => {
        clearTimeout(guard);
        if (streamMode && playing && personalMix() === want) {
          mixNotApplied("the station did not answer");
        }
      });
  }, 1500);
}
function mixNotApplied(why) {
  const note = document.getElementById("note");
  if (note) note.textContent = why + " - still playing your last mix; move a slider to try again";
}
''', "page")
ast.parse(a)

q.write_text(s)
p.write_text(a)
print("patched station_stream.py and app.py")
