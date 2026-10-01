"""[show-doctor] "where are the DJs?" walks the troubleshooting tree and fixes it.

2026-09-30, the operator: "I want to be able to ask the LLM what happened to the
show or where are the DJs? Or I'm not hearing any DJs or what happened to the
broadcast on the tablet. And it basically goes through a troubleshooting tree
to get the system working and getting the DJs back playing."

The tree, in the order today's faults were found, each a check and - where the
station owns the cure - the cure:
  1. ON AIR      switched off / paused -> said (how long), never resumed behind
                 the operator's back;
  2. LISTENERS   which surfaces are connected (the PineTab by name);
  3. HEARD       lines going out that nobody hears ([unheard-air]) or no owner
                 while several surfaces listen -> the air goes to the device
                 that plays out loud, its rest lifted;
  4. TALK        no dialogue for minutes ([dialogue-clock]) -> the reason the
                 station gave (bare arrivals, live writing refused, an empty
                 cupboard) and one live round asked for now;
  5. VOICES      renders tried but none finished lately -> said;
  6. ROUTING     voices routed to the box alone while the box is not heard.
The answer is two or three spoken sentences; the whole walk goes on the
orchestrator's line. It runs before the script report's "what happened", and
only for the show, the DJs, the broadcast, the voices or the dialogue.

Usage (ON THE HOST): python3 tools/show_doctor_patch.py --check|--apply app.py
"""
import ast
import shutil
import sys

MARK = "[show-doctor]"

EDITS = [
    ("tree",
     '''def parse_what_happened(text: str) -> bool:
''',
     '''# [show-doctor] "where are the DJs / I'm not hearing the DJs / what happened to
# the show" - a troubleshooting tree that fixes what the station owns
_SHOW_DOCTOR_RX = re.compile(
    r"where (?:are|did|is|have) (?:the |my |our )?(?:djs?|hosts?|show|voices?|dialogue)"
    r"|(?:not|n't|never|no one|nobody)\\b.{0,12}\\b(?:hear|hearing)\\b.{0,40}\\b"
    r"(?:djs?|hosts?|voices?|talk\\w*|dialogue|show|broadcast|them|anyone|anybody)"
    r"|\\bno (?:djs?|dialogue|talking|voices|hosts)\\b"
    r"|what(?:'s| is| has)? (?:happen(?:ed|ing)?|wrong|going on) (?:to|with) (?:the |my |our )?"
    r"(?:show|broadcast|djs?|station|hosts?|dialogue|voices?|radio)"
    r"|(?:fix|get back|bring back|restart|troubleshoot|diagnose) (?:the |my )?(?:show|djs?|broadcast|dialogue|hosts?|voices?)"
    r"|(?:djs?|hosts?|show|broadcast|dialogue|voices?) (?:(?:are|is|went|has gone|have gone) )?"
    r"(?:quiet|silent|gone|missing|not talking|stopped|dead|off)", re.I)


def parse_show_doctor(text: str) -> bool:
    t = " ".join(str(text or "").lower().split())
    return bool(t) and len(t) < 220 and bool(_SHOW_DOCTOR_RX.search(t))


async def show_doctor() -> str:
    """[show-doctor] walk the tree, cure what the station owns, say it plainly."""
    now = time.time()
    found: list[str] = []
    did: list[str] = []
    # 1. on air
    if not _RADIO.get("on"):
        say = "The station is switched off, so nobody is talking. Say start the radio to bring the DJs back."
        pipeline_log("air", "show doctor: the station is off [show-doctor]")
        return say
    if radio_paused():
        mins = int(radio_paused_for() // 60)
        say = ("The station is paused%s, so the DJs are off air while the rooms work. "
               "Say resume the show to bring them back." % ((" for %d minutes" % mins) if mins else ""))
        pipeline_log("air", "show doctor: paused %d min [show-doctor]" % mins)
        return say
    # 2. listeners
    try:
        roster = listener_roster()
    except Exception:  # noqa: BLE001
        roster = []
    kinds = sorted({str(r.get("what") or r.get("kind") or "a page") for r in roster})
    tablet_here = any(str(r.get("kind") or "") == "pinetab" for r in roster)
    if not roster:
        found.append("no screen or speaker is connected to the station")
    elif not tablet_here:
        found.append("the PineTab is not connected")
    # 3. heard
    try:
        chk = unheard_air_check(now)
    except Exception:  # noqa: BLE001
        chk = None
    owner = ""
    try:
        owner = audio_owner()
    except Exception:  # noqa: BLE001
        pass
    if chk or (not owner and len(roster) > 1):
        if chk:
            found.append("%d lines went out and nobody heard them" % chk["lines"])
        else:
            found.append("nobody owned the air while %d screens were listening" % len(roster))
        try:
            gave = unheard_air_rescue(chk or {})
        except Exception:  # noqa: BLE001
            gave = ""
        if gave:
            _UNHEARD["rescued_at"] = now
            did.append("gave the air to " + gave.split(" (")[0])
    # 4. talk
    try:
        quiet = int(now - float(_DIALOGUE_AT[0] or 0))
    except Exception:  # noqa: BLE001
        quiet = 0
    if quiet >= 150:
        why = ""
        for row in reversed(list(_RADIO.get("pipeline") or [])[-80:]):
            text = str(row.get("text") or "")
            if any(k in text for k in ("live writing is refused", "cupboard is empty", "BARE ARRIVAL",
                                       "produced no audio", "withheld")):
                why = text
                break
        found.append("nobody has talked for %d minutes%s" % (max(1, quiet // 60),
                     (" - " + (why if len(why) <= 120 else why[:120].rsplit(" ", 1)[0] + "...")) if why else ""))
        _STARVED_WRITE_AT[0] = 0.0
        _DIALOGUE_AT[0] = min(float(_DIALOGUE_AT[0] or 0), now - DIALOGUE_STARVED_AFTER - 1)
        did.append("asked the writers for a live round right now")
    # 5. voices
    try:
        tried, done = float(_SYNTH_TRIED[0] or 0), float(_LAST_SYNTH[0] or 0)
        if tried and now - tried < 300 and now - done > 300:
            found.append("the voice engine has been asked for voices but has not finished one in five minutes")
    except Exception:  # noqa: BLE001
        pass
    # 6. routing
    if str(_RADIO.get("voice_to") or "") == "box" and not _RADIO.get("box_audible", True):
        found.append("the voices are routed to the box alone and the box is not being heard")
    pipeline_log("air", "show doctor: found %s; did %s; listening: %s [show-doctor]"
                 % ("; ".join(found) or "nothing wrong", "; ".join(did) or "nothing",
                    ", ".join(kinds) or "nobody"))
    if not found:
        return ("The show is on and being heard on %s, and the DJs are talking. If you still hear nothing, "
                "check the volume on that screen." % (", ".join(kinds) or "the station"))
    say = "Here is what I found: " + "; ".join(found[:3]) + "."
    if did:
        say += " I " + " and ".join(did) + ", so the DJs should be back within a minute or two."
    else:
        say += " That one needs a hand on the device itself."
    return say


def parse_what_happened(text: str) -> bool:
'''),
    ("hook",
     '''    if parse_what_happened(user_text):
''',
     '''    if parse_show_doctor(user_text):                                     # [show-doctor]
        feature_meta["system_status_used"] = True
        return (await show_doctor()), {
            **feature_meta,
            "active_prompt": prompt_entry["name"],
            "model": "show-doctor",
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }
    if parse_what_happened(user_text):
'''),
]


def main() -> None:
    mode, path = sys.argv[1], sys.argv[2]
    src = open(path, encoding="utf-8").read()
    if MARK in src:
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
    shutil.copy(path, "/tmp/app.py.bak-show-doctor")
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src, "app.py changed underfoot"
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    main()
