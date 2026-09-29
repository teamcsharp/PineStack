"""[va-strips] Give the voice actor shell its profile-strip door
(desktop/renderer/voice-actor.js - the desk copy AND the kiosk's
app/src/main/assets/pine-views/voice-actor.js; run it on both).

Four small edits, nothing else in the shell moves:

  1. request(method, path, body, ms): an optional bound. The strips' sample
     is a real render on the one engine and can outlast the 9 s every other
     call keeps; nothing that passes three arguments changes.
  2. paintCast: after each seat row is built, the registered strips module
     (voice-actor-strips.js) is handed the row element and its seat model,
     guarded - a strip that throws never blanks the cast (the one-subscriber
     lesson). The module keeps its strip nodes, so a repaint re-attaches the
     same tiles instead of reloading pictures.
  3. stripCtx() + registerStrips(def): the context the module is handed -
     request, stationUrl, icon, say, isTablet, actors(), engines(),
     callers(), setSeat() (POST /api/voice-actor/seat, the panel's road) and
     setCallerVoice() (PUT /api/dj/callers/{id}, the Callers card's road),
     and pop() (the popup, where the audition sheet mounts).
  4. The public api gains registerStrips.

  python edit_voice_actor_strips_shell.py [--check|--apply] path/to/voice-actor.js

Marker-idempotent (marker `[va-strips]`): --check exits 0 = ready,
2 = applied, 1 = anchors missing. CRLF-aware: keeps the file's endings.
"""
from __future__ import annotations

import sys
from pathlib import Path

MARKER = "[va-strips]"

EDITS = [
    ("request-sig",
     "  function request(method, path, body) {\n    var b = bridge();\n",
     "  function request(method, path, body, ms) {\n"
     "    var bound = ms > 0 ? ms : REQUEST_MS;   /* [va-strips] a longer bound on request */\n"
     "    var b = bridge();\n"),
    ("request-bridge",
     "), REQUEST_MS, path);\n",
     "), bound, path);\n"),
    ("request-abort",
     "}, REQUEST_MS) : 0;\n",
     "}, bound) : 0;\n"),
    ("request-words",
     "Math.round(REQUEST_MS / 1000)",
     "Math.round(bound / 1000)"),
    ("cast-hook",
     "      host.appendChild(seat);\n",
     "      if (ui.stripDef) {                       /* [va-strips] the profile strip under this seat */\n"
     "        try { ui.stripDef.seat(seat, row, stripCtx()); }\n"
     "        catch (err) { if (root.console) root.console.error('[voice-actor] strip failed:', err); }\n"
     "      }\n"
     "      host.appendChild(seat);\n"),
    ("strip-door",
     "  function isTablet() {\n",
     "  /* [va-strips] The profile strips' context (voice-actor-strips.js). */\n"
     "  function stripCtx() {\n"
     "    return {\n"
     "      request: request,                    /* (method, path, body, ms?) -> Promise<json> */\n"
     "      stationUrl: stationUrl,\n"
     "      icon: icon,\n"
     "      say: say,\n"
     "      isTablet: isTablet(),\n"
     "      actors: function () { return (model.voices || []).slice(); },\n"
     "      engines: function () { return model.engines ? JSON.parse(JSON.stringify(model.engines)) : null; },\n"
     "      callers: function () { return ((model.callers && model.callers.callers) || []).slice(); },\n"
     "      /* the cast's own road: POST /api/voice-actor/seat (#820's cut included) */\n"
     "      setSeat: function (seat, vid) { return setSeatVoice(seat, vid); },\n"
     "      /* the Callers card's own road: the caller's pinned clone */\n"
     "      setCallerVoice: function (cid, vid) {\n"
     "        return request('PUT', '/api/dj/callers/' + encodeURIComponent(cid), {voice_id: String(vid || '')})\n"
     "          .then(function (ans) { refreshCast(); return ans; });\n"
     "      },\n"
     "      pop: function () { return ui.pop || null; }\n"
     "    };\n"
     "  }\n"
     "\n"
     "  /** The profile strips module's one registration door: def.seat(el, row, ctx). */\n"
     "  function registerStrips(def) {\n"
     "    if (!def || typeof def.seat !== 'function') return false;\n"
     "    ui.stripDef = def;\n"
     "    if (ui.visible) paint(true);\n"
     "    return true;\n"
     "  }\n"
     "\n"
     "  function isTablet() {\n"),
    ("api",
     "    registerExtraction: registerExtraction,\n",
     "    registerExtraction: registerExtraction,\n"
     "    registerStrips: registerStrips,         /* [va-strips] */\n"),
]


def state_of(text: str, eol: str) -> str:
    if MARKER in text:
        return "applied"
    bad = ["%s x%d" % (name, text.count(old.replace("\n", eol)))
           for name, old, _new in EDITS if text.count(old.replace("\n", eol)) != 1]
    return "ready" if not bad else "anchors: " + ", ".join(bad) + " (want 1 each)"


def main(argv: list[str]) -> int:
    do_apply = "--apply" in argv
    target = next((a for a in argv if not a.startswith("--")), "desktop/renderer/voice-actor.js")
    path = Path(target)
    text = path.read_bytes().decode("utf-8")
    eol = "\r\n" if "\r\n" in text else "\n"
    state = state_of(text, eol)
    if state == "applied":
        print("already applied")
        return 2
    if state != "ready":
        print("missing:", state)
        return 1
    if not do_apply:
        print("ready")
        return 0
    for name, old, new in EDITS:
        o, n = old.replace("\n", eol), new.replace("\n", eol)
        assert text.count(o) == 1, "%s: anchor count %d" % (name, text.count(o))
        text = text.replace(o, n)
    assert MARKER in text and "REQUEST_MS), path" not in text
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(text.encode("utf-8"))
    tmp.replace(path)
    print("APPLIED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
