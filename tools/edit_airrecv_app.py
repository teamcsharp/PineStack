#!/usr/bin/env python3
"""[airplayers] app.py: a MULTI-select set of receivers that sound the station.

TARGET: app.py, tests/test_air_receivers_2026_09_29.py (new)
usage: edit_airrecv_app.py --check|--apply <repo root>

Adds GET/POST /api/air/receivers, the per-listener `hushed` on the clock,
pineSoloGate honouring it (panel + tune page), the exclusive refusing a
hushed page, the #1185 table nomination standing down while several
receivers are switched on, and `air_receivers` surviving validate_settings.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patchlib_air import run  # noqa: E402

VALIDATE = r'''def validate_air_receivers(raw: Any) -> dict[str, Any]:
    """[airplayers] the receivers switch's own memory (see air_flags).

    `web` and `car` are the out-loud switches for browser pages and for
    tune-in links through the public door; the PineTab and the app keep
    theirs in `terminals.<id>.play`. `speaker_streams` is what the Nabu /
    Pine Box speaker carried when it was switched off, so switching it
    back on restores exactly that."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for key in ("web", "car"):
        if key in raw:
            out[key] = bool(raw.get(key))
    streams = raw.get("speaker_streams")
    if isinstance(streams, list):
        out["speaker_streams"] = [s for s in ("music", "voice", "reply")
                                  if s in streams]
    return out


'''

VALIDATE_KEY_OLD = '''        "terminals": validate_terminals(data.get("terminals")),
'''
VALIDATE_KEY_NEW = '''        # [airplayers:key] the receivers switch - see validate_air_receivers
        "air_receivers": validate_air_receivers(data.get("air_receivers")),
'''

HELPERS = r'''# [airplayers] WHICH RECEIVERS SOUND THE STATION - A SET, NOT ONE.
#
# Operator, 2026-09-29: "i want to be able to enable and disable streams
# from there as well by enabling them from receiving a broadcast. For
# example the nabu is broadcasting. If it were listed, I would uncheck it
# from being audible and enable the pinetab to be the active radio. Also I
# would turn off the pine app audio for now since i am listening throuhg
# the pinetablet".
#
# #1008's exclusive hands ONE page the air. This is a switch per RECEIVER,
# any number on and any number off:
#   - a PAGE receiver (the PineTab, this app, web pages, the car's tune-in
#     page) is silenced AT ITS OWN END: the clock answers a hushed listener
#     `hushed: true` and its pineSoloGate mutes its elements exactly as the
#     exclusive does. Its acknowledgments then say muted / audible 0 and
#     never count as heard, while the audible receivers' acknowledgments
#     keep every receipt flowing - heard_at, _DIALOGUE_HEARD and the line
#     receipts all read AUDIBLE acks per listener, never "any ack".
#   - a SPEAKER receiver (the Nabu, the Pine Box) is "not sent to": its
#     streams are routed back to the pages through /api/dj/output itself.
# The last audible receiver cannot be switched off, and when nothing that
# is switched on is actually present (the tablet put away for 90 s) nobody
# is hushed - #1008's contract, the house is never left silent.
#
# Storage: the PineTab and the app keep their existing out-loud switch,
# `terminals.<id>.play` (#1161/#1185 - "check play FIRST"); web pages and
# the car live in settings `air_receivers`; the speakers ARE the routing.
AIR_PAGE_RECEIVERS = ("pinetab", "desktop", "web", "car")
AIR_SPEAKERS = ("nabu", "box")
AIR_STREAMS = ("music", "voice", "reply")
AIR_RECEIVER_LABEL = {
    "pinetab": "PineTab", "desktop": "This app", "web": "Web pages",
    "car": "Car / tune-in", "nabu": "Nabu", "box": "Pine Box speaker"}
AIR_RECEIVER_WHAT = {
    "pinetab": "the tablet - its speaker or its aux cable",
    "desktop": "the Pine Box app on the computer, every tab of it",
    "web": "browser pages on the house network",
    "car": "tune-in links through the public door (the Funnel)",
    "nabu": "the Home Assistant Voice speaker - the station sends it clips",
    "box": "the Pine Box's own speaker"}
AIR_STREAM_WORD = {"music": "records", "voice": "DJs", "reply": "replies"}
_AIR_RECV_CACHE: dict[str, Any] = {"at": 0.0, "flags": {}, "eff_at": 0.0,
                                   "eff": {}, "rescued": False}


def air_receiver_for(kind: str, device: str) -> str:
    """Which receiver a roster surface belongs to."""
    if device == "pinetab" or kind == "pinetab":
        return "pinetab"
    if device == "desktop" or kind == "app":
        return "desktop"
    if kind == "tune":
        return "car"
    return "web"


def air_flags(fresh: bool = False) -> dict[str, bool]:
    """The out-loud switch of every page receiver. Cached like
    terminal_rows(): the clock asks for it on every poll of every page."""
    now = time.time()
    if (not fresh and now - float(_AIR_RECV_CACHE.get("at") or 0)
            <= TERMINALS_TTL and _AIR_RECV_CACHE.get("flags")):
        return dict(_AIR_RECV_CACHE.get("flags") or {})
    try:
        settings = load_settings() or {}
    except Exception:  # noqa: BLE001
        settings = {}
    table = settings.get("terminals")
    table = table if isinstance(table, dict) else {}
    stored = settings.get("air_receivers")
    stored = stored if isinstance(stored, dict) else {}
    flags: dict[str, bool] = {}
    for rid in AIR_PAGE_RECEIVERS:
        if rid in ("pinetab", "desktop"):
            row = table.get(rid)
            flags[rid] = bool(row.get("play")) if isinstance(row, dict) else True
        else:
            flags[rid] = bool(stored.get(rid, True))
    # Web pages switched on BY HAND count as a choice; the default (never
    # touched) keeps the old rule - they follow the exclusive.
    _AIR_RECV_CACHE.update({"at": now, "flags": dict(flags), "eff_at": 0.0,
                            "web_chosen": stored.get("web") is True})
    return flags


def air_speakers() -> dict[str, dict[str, Any]]:
    """Is the Nabu / the Pine Box speaker being SENT anything, and what.
    One box road: `voice_device` says which of the two it reaches."""
    on_nabu = str(_RADIO.get("voice_device") or "") == "nabu"
    talk = bool(_RADIO.get("box_talk", True))
    carried = []
    for stream in AIR_STREAMS:
        route = str(_RADIO.get(stream + "_to") or "")
        if route in ("box", "both", "nabu") and (stream == "music" or talk):
            carried.append(stream)
    out: dict[str, dict[str, Any]] = {}
    for sid in AIR_SPEAKERS:
        mine = (sid == "nabu") == on_nabu
        out[sid] = {"audible": bool(carried) and mine,
                    "streams": list(carried) if mine else []}
    return out


def _air_rid_of(who: str, away: bool = False) -> str:
    seen = _LISTENER_SEEN.get(who) or {}
    kind = listener_kind(who, str(seen.get("agent") or ""),
                         bool(seen.get("public")) or bool(away))
    device = listener_device(kind, str(seen.get("addr") or ""),
                             terminal_rows(), who)
    return air_receiver_for(kind, device)


def air_present() -> dict[str, list[str]]:
    """Live listener ids per page receiver (the same 90 s life #1008 uses,
    so a page reloading is still present)."""
    out: dict[str, list[str]] = {rid: [] for rid in AIR_PAGE_RECEIVERS}
    for who in _listeners_live():
        if str(who).startswith("sfx-tv-"):
            continue            # a video set's own receipts, not a player
        out.setdefault(_air_rid_of(who), []).append(who)
    return out


def air_effective() -> dict[str, bool]:
    """The switches as they apply RIGHT NOW: if nothing switched on is
    actually here to sound, nobody is hushed (the house is never silent)."""
    now = time.time()
    if now - float(_AIR_RECV_CACHE.get("eff_at") or 0) <= 2.0 \
            and _AIR_RECV_CACHE.get("eff"):
        return dict(_AIR_RECV_CACHE.get("eff") or {})
    flags = air_flags()
    eff = dict(flags)
    rescued = False
    try:
        if not any(v["audible"] for v in air_speakers().values()):
            present = air_present()
            if not any(flags.get(r) and present.get(r)
                       for r in AIR_PAGE_RECEIVERS):
                eff = {r: True for r in AIR_PAGE_RECEIVERS}
                rescued = any(present.values())
    except Exception:  # noqa: BLE001
        eff = {r: True for r in AIR_PAGE_RECEIVERS}
    _AIR_RECV_CACHE.update({"eff_at": now, "eff": dict(eff),
                            "rescued": rescued})
    return eff


def air_hushed(who: str, away: bool = False) -> bool:
    """Is this listener's receiver switched off? Never raises: a failure
    here must not gag a page."""
    if not who:
        return False
    try:
        return not air_effective().get(_air_rid_of(who, away), True)
    except Exception:  # noqa: BLE001
        return False


def air_several_audible() -> bool:
    """More than one receiver IN THE HOUSE switched on and present. The
    #1185 table nomination stands down then: the operator chose several.
    Web pages count only when switched on by hand: on a station where
    nobody has touched the switch they are gagged by the device that holds
    the air, exactly as before this build."""
    try:
        eff = air_effective()
        present = air_present()
        rooms = ["pinetab", "desktop"]
        if _AIR_RECV_CACHE.get("web_chosen"):
            rooms.append("web")
        return sum(1 for r in rooms if eff.get(r) and present.get(r)) > 1
    except Exception:  # noqa: BLE001
        return False


def air_receivers_state() -> dict[str, Any]:
    """[airplayers] Every receiver, whether it is switched on, whether it is
    sounding, when it last reported hearing the station, and which one is
    the active radio."""
    now = time.time()
    flags = air_flags(fresh=True)
    eff = air_effective()
    owner = audio_owner()
    roster = listener_roster()
    speakers = air_speakers()
    heard: dict[str, float] = {}
    for ev in list(_PAGE_ACK_EVENTS[-300:]):
        try:
            if ev.get("muted") or float(ev.get("audible_volume") or 0) <= 0:
                continue
            lid = str(ev.get("listener_id") or "")
            heard[lid] = max(heard.get(lid, 0.0), float(ev.get("at") or 0))
        except (TypeError, ValueError, AttributeError):
            continue
    here = [s for s in AIR_STREAMS
            if str(_RADIO.get(s + "_to") or "") == "here"]
    rows: list[dict[str, Any]] = []
    for rid in AIR_PAGE_RECEIVERS:
        mine = [r for r in roster
                if air_receiver_for(str(r.get("kind") or ""),
                                    str(r.get("device") or "")) == rid]
        ids = [str(i) for r in mine
               for i in (r.get("ids") or [r.get("listener")]) if i]
        last = max([heard.get(i, 0.0) for i in ids] or [0.0])
        bits = []
        for r in mine[:3]:
            bits.append(" · ".join(b for b in (
                str(r.get("addr") or ""),
                ("%d tabs" % int(r.get("surfaces") or 1))
                if int(r.get("surfaces") or 1) > 1 else "",
                "%ds ago" % round(float(r.get("seen") or 0))) if b))
        gagged = bool(owner) and owner not in ids and rid != "car"
        rows.append({
            "id": rid, "kind": "page", "label": AIR_RECEIVER_LABEL[rid],
            "what": AIR_RECEIVER_WHAT[rid],
            "audible": bool(flags.get(rid)),
            "sounding": bool(eff.get(rid)) and bool(mine) and not gagged,
            "present": bool(mine),
            "listeners": [str(r.get("listener") or "") for r in mine],
            "owns_air": bool(owner) and owner in ids,
            "carries": [AIR_STREAM_WORD[s] for s in here],
            "detail": "; ".join(b for b in bits if b) or "not open",
            "heard_ago": round(now - last, 1) if last else None,
        })
    box_ok = float(_BOX_LAST_OK[0] or 0)
    for sid in AIR_SPEAKERS:
        sp = speakers[sid]
        rows.append({
            "id": sid, "kind": "speaker", "label": AIR_RECEIVER_LABEL[sid],
            "what": AIR_RECEIVER_WHAT[sid],
            "audible": bool(sp["audible"]), "sounding": bool(sp["audible"]),
            "present": True, "listeners": [], "owns_air": False,
            "carries": [AIR_STREAM_WORD[s] for s in sp["streams"]],
            "detail": ("carries the " + ", ".join(
                AIR_STREAM_WORD[s] for s in sp["streams"]))
            if sp["streams"] else "not sent to",
            "heard_ago": (round(now - box_ok, 1)
                          if sp["streams"] and box_ok else None),
        })
    active = next((r["id"] for r in rows if r["owns_air"]), "")
    if not active:
        sounding = [r for r in rows if r["sounding"]]
        pages = [r for r in sounding if r["kind"] == "page"]
        if len(sounding) == 1:
            active = sounding[0]["id"]
        elif sounding:
            best = max(sounding, key=lambda r: -1e9 if r["heard_ago"] is None
                       else -float(r["heard_ago"]))
            active = best["id"] if best["heard_ago"] is not None else (
                pages[0]["id"] if pages else sounding[0]["id"])
    for r in rows:
        r["active"] = r["id"] == active
    on = [r["label"] for r in rows if r["sounding"]]
    say = ("nothing is sounding the station" if not on else
           "sounding: " + ", ".join(on)
           + ((" - " + AIR_RECEIVER_LABEL.get(active, active)
               + " is the active radio") if active else ""))
    if _AIR_RECV_CACHE.get("rescued"):
        say += (" - nothing switched on is here, so every page may sound"
                " until one is")
    return {"receivers": rows, "active": active, "owner": owner,
            "rescued": bool(_AIR_RECV_CACHE.get("rescued")), "say": say,
            "routing": {s: str(_RADIO.get(s + "_to") or "")
                        for s in AIR_STREAMS},
            "voice_device": str(_RADIO.get("voice_device") or "")}


'''

MULTI_GUARD_ANCHOR = '''        # Nobody nominated, or the nomination is gone for good: the
'''
MULTI_GUARD = '''        # [airplayers:multi] SEVERAL RECEIVERS SWITCHED ON IS A CHOICE NOW.
        # The operator asked for a set ("several players can be on, and any
        # can be off"), so the table no longer picks one of them to gag the
        # rest. Switched-off receivers are silenced by `hushed`, not by
        # somebody else holding the air. An explicit hand-over (solo, or
        # "only" on /api/air/receivers) still stands above. Looked up, not
        # named: tests exec this function on its own.
        _several = globals().get("air_several_audible")
        if _several is not None and _several():
            if who:
                _AUDIO_OWNER.clear()
            return ""
'''

CLOCK_OLD = '''        "audio_owner": "" if _away else audio_owner(),
'''
CLOCK_NEW = '''        # [airplayers:clock] this listener's receiver is switched off: it
        # mutes itself (pineSoloGate), as a gagged page does.
        "hushed": air_hushed(listener[:64], _away) if listener else False,
'''

GATE_OLD = '''    const gagged = !!owner && !!me && owner !== me;
'''
GATE_NEW = '''    /* [airplayers:gate] a receiver switched off in the drawer is hushed
     * by the clock and mutes itself exactly as a gagged page does. */
    const gagged = !!(clock && clock.hushed)
      || (!!owner && !!me && owner !== me);
'''

SOLO_ANCHOR = '''    _AUDIO_OWNER.clear()
    _AUDIO_OWNER.update({"who": who, "at": time.time()})
    pipeline_log("air", f"{who} has the air - every other player mutes "
'''
SOLO_GUARD = '''    # [airplayers:solo] nor may a page whose receiver is switched off: it
    # would gag every audible page for one that has muted itself.
    if air_hushed(who):
        return {"audio_owner": audio_owner(), "listeners": listener_roster(),
                "refused": who,
                "why": "that receiver is switched off in Playing it - switch "
                       "it on first"}
'''

ROUTES_ANCHOR = '''@app.post("/api/radio/solo")
'''
ROUTES = r'''class _AirAsk:
    """[airplayers] the receivers switch asking /api/dj/output to move a
    speaker's streams - the routing handler reads a request, so this is
    one: the same validation, the same ledger, the same save."""

    def __init__(self, body: dict[str, Any], client: Any = None) -> None:
        self._body = dict(body)
        self.client = client
        self.headers = {"user-agent": "the Playing it switch"}

    async def json(self) -> dict[str, Any]:
        return dict(self._body)


def air_speaker_route(sid: str, on: bool, remembered: list[str]) -> dict[str, Any]:
    """[airplayers] the /api/dj/output body that switches a speaker."""
    if not on:
        return {s: "here" for s in AIR_STREAMS
                if str(_RADIO.get(s + "_to") or "") in ("box", "both", "nabu")}
    streams = [s for s in (remembered or ["voice", "reply"]) if s in AIR_STREAMS]
    body: dict[str, Any] = {s: "box" for s in (streams or ["voice", "reply"])}
    body["voice_device"] = "nabu" if sid == "nabu" else "pine"
    return body


@app.get("/api/air/receivers")
async def air_receivers_api(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """[airplayers] every receiver of the broadcast and its out-loud switch."""
    require_read_auth(authorization)
    return air_receivers_state()


@app.post("/api/air/receivers")
async def air_receivers_set_api(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """[airplayers] {"id": "<receiver>", "audible": true|false} switches one;
    {"only": "<receiver>"} makes it the only one sounding in the house (the
    car keeps its own switch - it is not in the room, #1253). Answers with
    the fresh state, so a client paints the station's word, not its wish."""
    require_auth(authorization)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    body = body if isinstance(body, dict) else {}
    everyone = AIR_PAGE_RECEIVERS + AIR_SPEAKERS
    only = str(body.get("only") or "").strip().lower()
    rid = str(body.get("id") or "").strip().lower()
    want: dict[str, bool] = {}
    want_speaker: dict[str, bool] = {}
    if only:
        if only not in everyone:
            raise HTTPException(status_code=400, detail="no such receiver: "
                                + only + " (" + ", ".join(everyone) + ")")
        want = {r: r == only for r in ("pinetab", "desktop", "web")}
        want_speaker = {s: s == only for s in AIR_SPEAKERS}
    else:
        if rid not in everyone or not isinstance(body.get("audible"), bool):
            raise HTTPException(status_code=400, detail="name a receiver ("
                                + ", ".join(everyone)
                                + ") and audible true or false, or send only")
        (want_speaker if rid in AIR_SPEAKERS else want)[rid] = body["audible"]
    flags = air_flags(fresh=True)
    speakers = air_speakers()
    pages_next = dict(flags)
    pages_next.update(want)
    speak_next = {s: bool(speakers[s]["audible"]) for s in AIR_SPEAKERS}
    speak_next.update(want_speaker)
    if not any(pages_next.values()) and not any(speak_next.values()):
        out = air_receivers_state()
        out.update({"ok": False, "refused": only or rid,
                    "why": "that would leave nothing sounding the station - "
                           "switch another receiver on first"})
        return out
    changed = {r: v for r, v in want.items() if bool(flags.get(r)) != v}
    settings = load_settings()
    store = dict(settings.get("air_receivers") or {})
    if changed:
        table = dict(settings.get("terminals") or {})
        for r, v in changed.items():
            if r in ("pinetab", "desktop"):
                row = dict(table.get(r) or {"name": AIR_RECEIVER_LABEL[r]})
                row["play"] = v
                table[r] = row
            else:
                store[r] = v
        settings["terminals"] = table
    for sid, v in want_speaker.items():
        if not v and speakers[sid]["streams"]:
            store["speaker_streams"] = list(speakers[sid]["streams"])
    if changed or "speaker_streams" in store:
        settings["air_receivers"] = store
        save_settings(settings)
    _TERMINALS_CACHE["at"] = 0.0
    _AIR_RECV_CACHE.update({"at": 0.0, "eff_at": 0.0})
    if changed:
        pipeline_log("air", "Playing it: " + ", ".join(
            "%s %s" % (AIR_RECEIVER_LABEL[r], "on" if v else "off")
            for r, v in changed.items()) + " (airplayers)")
    # The exclusive never rests on a receiver that has muted itself; "only"
    # hands it to the one receiver left, which is what makes it the radio.
    held = str(_AUDIO_OWNER.get("who") or "")
    if held and air_hushed(held):
        _AUDIO_OWNER.clear()
    # A second receiver switched ON means both sound: the exclusive that
    # gagged it (usually the #1185 table's pick) gives way to the choice.
    if not only and any(changed.values()) and air_several_audible():
        _AUDIO_OWNER.clear()
    if only in ("pinetab", "desktop", "web"):
        ids = air_present().get(only) or []
        best = max(ids, default="", key=lambda w: float(
            (_LISTENER_SEEN.get(w) or {}).get("at") or 0))
        if best and not _owner_resting(best):
            _AUDIO_OWNER.clear()
            _AUDIO_OWNER.update({"who": best, "at": time.time()})
    elif only:
        _AUDIO_OWNER.clear()
    routed = []
    for sid in AIR_SPEAKERS:
        v = want_speaker.get(sid)
        if v is None or v == bool(speakers[sid]["audible"]):
            continue
        if not v and speak_next.get("nabu" if sid == "box" else "box"):
            continue                 # the other device took the road already
        ask = air_speaker_route(sid, v, list(store.get("speaker_streams") or []))
        if len(ask) > (1 if v else 0):
            await dj_output_api(_AirAsk(ask, getattr(request, "client", None)),
                                authorization)
            routed.append("%s %s" % (AIR_RECEIVER_LABEL[sid], "on" if v else "off"))
    out = air_receivers_state()
    out["ok"] = True
    if routed:
        out["routed"] = routed
    return out


'''

EDITS = [
    ("def validate_air_receivers(", "def validate_terminals(raw: Any) -> dict[str, Any]:\n",
     VALIDATE, "before", 1),
    ("[airplayers:key]", VALIDATE_KEY_OLD, VALIDATE_KEY_NEW, "after", 1),
    ("def air_receivers_state(", "def listener_census(rows: list[dict[str, Any]]) -> str:\n",
     HELPERS, "before", 1),
    ("[airplayers:multi]", MULTI_GUARD_ANCHOR, MULTI_GUARD, "before", 1),
    ("[airplayers:clock]", CLOCK_OLD, CLOCK_NEW, "after", 1),
    ("[airplayers:gate]", GATE_OLD, GATE_NEW, "replace", 2),
    ("[airplayers:solo]", SOLO_ANCHOR, SOLO_GUARD, "before", 1),
    ('@app.post("/api/air/receivers")', ROUTES_ANCHOR, ROUTES, "before", 1),
]

TEST = "tests/test_air_receivers_2026_09_29.py"


def main(argv):
    code = run("app.py", EDITS, argv)
    if code in (1, 64) or len(argv) != 2:
        return code
    mode, root = argv
    src = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.path.basename(TEST))
    dst = os.path.join(root, TEST)
    with open(src, "rb") as fh:
        want = fh.read().replace(b"\r\n", b"\n")
    have = open(dst, "rb").read().replace(b"\r\n", b"\n") if os.path.exists(dst) else None
    if have == want:
        print(TEST + ": APPLIED")
        return code
    if have is not None:
        print(TEST + ": MISSING (a different file is there)")
        return 1
    if mode == "--check":
        print(TEST + ": READY (new file)")
        return 0
    with open(dst, "wb") as fh:
        fh.write(want)
    print(TEST + ": APPLIED (new file)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
