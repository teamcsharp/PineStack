"""Two /api/dj/video routes existed. Keep the better one, widen its door.

A concurrent pass built #1263 - the video ring, the panel's draggable CRT
(sfx-tv), and a /api/dj/video route - while this one was building the same
feature for the TUNE page. FastAPI binds the FIRST route registered, so the
second was dead code that merely looked like it worked.

Their route is the one to keep: same ring, same cut, same staleness rule,
and it already refuses a clip that has missed its moment. The only thing
wrong with it for this purpose is the DOOR - `require_read_auth` reads an
Authorization header, and the public listener gate strips that before the
request ever lands. A guest on a tune-in link could never have called it.

So: the duplicate goes, and the survivor learns the `?t=` token every other
route on that page already takes. The two sets stay separate on purpose -
the panel's is a draggable CRT over a desktop shell, and the tune page
takes over the artwork frame, which is what was actually asked for
("I'm not seeing the comfy UI picture in picture get replaced").
"""
import pathlib
import re

p = pathlib.Path("app.py")
src = p.read_text(encoding="utf-8")
orig = src

# --- 1. remove THIS pass's duplicate route -------------------------------
start = src.find('@app.get("/api/dj/video")\nasync def dj_video_now(')
assert start != -1, "own route not found"
end = src.find('@app.get("/api/dj/reacts")', start)
assert end != -1 and end > start, "own route end not found"
removed = src[start:end]
assert "videos" in removed and len(removed) < 4000, "refusing to cut that much"
src = src[:start] + src[end:]
print(f"removed the duplicate route ({len(removed)} chars)")

# --- 2. widen the survivor's door ----------------------------------------
old = '''async def dj_video_api(
    since: int = 0,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:'''
assert src.count(old) == 1, "survivor signature"
src = src.replace(old, '''async def dj_video_api(
    since: int = 0,
    t: str = "",
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:''', 1)

old_auth = '''    A clip that has missed its moment is NOT offered: the set coming on
    over whatever is airing now is worse than the clip being missed."""
    require_read_auth(authorization)'''
assert src.count(old_auth) == 1, "survivor auth"
src = src.replace(old_auth, '''    A clip that has missed its moment is NOT offered: the set coming on
    over whatever is airing now is worse than the clip being missed.

    The door takes a tune-in token as well as the key. The public gate
    strips Authorization before a request reaches any handler, so a
    header-only check meant the listener page - the one surface that
    most wants a picture, in a car, on a phone - could never call this
    at all. Same contract as every other route that page uses."""
    require_listen_auth(t, authorization)''', 1)

# --- 3. the page reads the survivor's shape ------------------------------
old_poll = '''  tvSkew = Number(data.server_ms || Date.now()) - Date.now();
  const lagMs = tvLagSeconds() * 1000;
  const now = Date.now();
  let best = null;
  (data.videos || []).forEach((v) => {
    if (!v.url || !v.seconds) return;'''
assert src.count(old_poll) == 1, "page poll shape"
src = src.replace(old_poll, '''  tvSkew = Number(data.server_ms || Date.now()) - Date.now();
  const lagMs = tvLagSeconds() * 1000;
  const now = Date.now();
  let best = null;
  /* The station's own video ring (#1263) - `clips`, not `videos`. */
  (data.clips || []).forEach((c) => {
    const v = {url: c.url, seconds: Number(c.seconds || 0),
               broadcast_ms: Number(c.broadcast_ms || 0),
               name: String(c.sting || c.text || "")};
    if (!v.url || !v.seconds) return;''', 1)

# the closure below referenced `v` already, so only the tail needs the fix
old_tail = '''    if (into >= -0.5 && into < Number(v.seconds) + 0.5) {
      if (!best || Number(v.broadcast_ms) > Number(best.v.broadcast_ms)) {
        best = {v: v, into: into};
      }
    }
  });'''
assert src.count(old_tail) == 1, "page poll tail"
src = src.replace(old_tail, '''    if (into >= -0.5 && into < v.seconds + 0.5) {
      if (!best || v.broadcast_ms > best.v.broadcast_ms) {
        best = {v: v, into: into};
      }
    }
  });''', 1)

assert src != orig
p.write_text(src, encoding="utf-8")
print("reconciled: one route, one door, the page reads the real shape")
