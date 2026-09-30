"""[levels-one] app.py: the one set of levels on the station, and the panel's
gain stages reading level x master from the bus.

  import levels                 the store (levels.py; data/levels.json)
  GET  /api/levels              {levels | None, rev, at, by, kinds, ceil, box}
  POST /api/levels              {levels: {kind: v}, by}   an operator's move
  POST /api/levels/adopt        {levels, by}              a surface joining (the quieter wins)
  panel: djApplyGain / djVoicePlay / pineLevelStored use pineLevels.effective()
         (the raw levels stay on the sliders; the SOUND is level x master)

Usage (ON THE HOST): python3 tools/levels_one_app_patch.py --check|--apply
"""
import ast
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARK = "[levels-one]"

ROUTES = '''# --- [levels-one] THE ONE SET OF LEVELS, ON THE STATION ---------------------------
# "the goal with the audio is to unify and have it all controlled by a single
# unified system." One set, station-wide; a master everything follows; the pads
# their own row; the Pine Box speaker a Box route beside them (its levels stay
# /api/dj/output's, shown here so one popup holds everything). levels.py.
LEVELS_PATH = data_path("levels.json")


def levels_box() -> dict[str, Any]:
    """The Pine Box / Nabu speaker's own levels, in the shape PineAudioLaw.levelOf reads."""
    s = dj_settings()
    return {"voice_device": _RADIO.get("voice_device") or "nabu",
            "music_to": _RADIO.get("music_to") or "here", "voice_to": _RADIO.get("voice_to") or "box",
            "reply_to": _RADIO.get("reply_to") or "box",
            "music_level": round(music_box_level(), 3),
            "nabu_music_level": float(s.get("nabu_music_level", music_box_level())),
            "nabu_voice_level": float(s.get("nabu_voice_level", 0.5)),
            "nabu_reply_level": float(s.get("nabu_reply_level", 0.5))}


def levels_view(got: dict[str, Any]) -> dict[str, Any]:
    out = dict(got)
    out.update({"ok": True, "kinds": list(_levels.KINDS), "ceil": dict(_levels.CEIL)})
    try:
        out["box"] = levels_box()
    except Exception:  # noqa: BLE001
        out["box"] = {}
    return out


@app.get("/api/levels")
async def levels_get_api(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_read_auth(authorization)
    return levels_view(await asyncio.to_thread(_levels.state, LEVELS_PATH))


async def _levels_body(request: Request) -> tuple[dict[str, Any], str]:
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    body = body if isinstance(body, dict) else {}
    vals = body.get("levels") if isinstance(body.get("levels"), dict) else {}
    return vals, str(body.get("by") or "")[:40]


@app.post("/api/levels")
async def levels_set_api(request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_auth(authorization)
    vals, by = await _levels_body(request)
    got = await asyncio.to_thread(_levels.write, LEVELS_PATH, vals, by)
    if got.get("changed"):
        pipeline_log("air", "levels: %s from %s (rev %d) [levels-one]" % (
            ", ".join("%s %d%%" % (k, round(got["levels"][k] * 100)) for k in got["changed"]),
            by or "a surface", got["rev"]))
    return levels_view(got)


@app.post("/api/levels/adopt")
async def levels_adopt_api(request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_auth(authorization)
    vals, by = await _levels_body(request)
    got = await asyncio.to_thread(_levels.adopt, LEVELS_PATH, vals, by)
    if got.get("seeded"):
        pipeline_log("air", "levels: the one set seeded by %s: %s [levels-one]" % (
            by or "a surface", ", ".join("%s %d%%" % (k, round(v * 100)) for k, v in got["levels"].items())))
    elif got.get("lowered"):
        pipeline_log("air", "levels: %s joined quieter on %s - the station follows it down [levels-one]" % (
            by or "a surface", ", ".join(got["lowered"])))
    return levels_view(got)


'''

EDITS = [
    ('''import emotion_engine as _emotion           # [emotion-engine] the emotion engine's own window
''', '''import emotion_engine as _emotion           # [emotion-engine] the emotion engine's own window
import levels as _levels                   # [levels-one] the one set of levels, on the station
''', 1),
    ('''@app.get("/api/slideshow/media/{filename}")
''', ROUTES + '''@app.get("/api/slideshow/media/{filename}")
''', 1),
    ('''  const sharedLevels = window.pineLevels && window.pineLevels.get
    ? window.pineLevels.get() : null;
''', '''  const sharedLevels = window.pineLevels && window.pineLevels.get
    ? window.pineLevels.get() : null;
  /* [levels-one] the sliders show the level; the SOUND is level x master */
  const effLevels = sharedLevels && typeof window.pineLevels.effective === "function"
    ? window.pineLevels.effective() : sharedLevels;
''', 1),
    ('''    const shared = unified ? Number(sharedLevels.music) : NaN;
''', '''    const shared = unified ? Number(effLevels.music) : NaN;
''', 1),
    ('''    const shared = sharedLevels;
    djVoiceEls.forEach((a, ix) => {
''', '''    const shared = effLevels;
    djVoiceEls.forEach((a, ix) => {
''', 1),
    ('''      player.volume = pineMixerVoiceLevel(player, Math.max(0, Math.min(1, djLevels().voice)));
''', '''      const _eff = window.pineLevels && typeof window.pineLevels.effective === "function"
        ? window.pineLevels.effective() : null;                       /* [levels-one] one bus */
      const _sting = !!(player.dataset && player.dataset.pineSting === "1");
      player.volume = _eff
        ? (Math.max(0, Math.min(1, Number(_eff[_sting ? "sfx" : "voice"]))) || 0)
        : pineMixerVoiceLevel(player, Math.max(0, Math.min(1, djLevels().voice)));
''', 1),
    ('''      const v = Number((bus.get() || {})[kind]);
      if (Number.isFinite(v)) return clamp(v);
''', '''      const v = Number(((typeof bus.effective === "function" ? bus.effective() : bus.get()) || {})[kind]);   /* [levels-one] */
      if (Number.isFinite(v)) return clamp(v);
''', 1),
]

if __name__ == "__main__":
    mode = sys.argv[1]
    path = ROOT + "/app.py"
    src = open(path, encoding="utf-8").read()
    if MARK in src:
        print(path + ": APPLIED")
        sys.exit(0)
    out = src
    for old, new, n in EDITS:
        got = out.count(old)
        assert got == n, "%r found %d, want %d" % (old[:60], got, n)
        out = out.replace(old, new)
    ast.parse(out)
    if mode == "--check":
        print(path + ": ready")
        sys.exit(0)
    shutil.copy(path, "/tmp/app.py.bak-levels-one")
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")
