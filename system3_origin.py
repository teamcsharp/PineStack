"""[s3-account] System 3's ORIGIN LEDGER: every aired item, traceable forever.

"every system accountable under the system three node roulette RNG system ...
 we know and keep track of all of this information at all times. We never lose
 track of it ... trace its origin for each and every thing down to either a
 table that is accessed via a roulette option or whatever system is needing to
 encompass the rogue element."                         - the operator, 2026-09-28

One durable record per aired item (a line, a board clip, an SFX Guy quip, a
desk marker, a record on the deck, an operator send), keyed by its line id:

    verdict   rolled  - a System 3 node with the rolls that made it
              forced  - a NAMED forced node: road + trigger (the never-quiet
                        fillers, the operator's taps, the live set) - never
                        fake dice; any real roll inside it (which gold bar,
                        which reserve pair) is listed beside the reason
              rogue   - no System 3 origin: it aired (the air is never held)
                        and the record names the code path, and it sits on
                        the Untraced list - every one of them a bug to close
    joins     script ledger (block, ord, sid, segment), the air receipt,
              System 3 conversation / turn / decision ids, the tables and
              the dice, the store it was drawn from (kind, db, pool, key,
              file, folder), the forced reason / rogue code path

Retention (operator, binding): the FULL record (prompts, candidate lists,
decision bodies) is kept 7 days; then it is COMPACTED FOREVER to ids, tables,
rolls and store refs. The compactor runs on the station's hourly maintenance
cadence (airlog_compact_all), in a thread, never on the event loop.

The station feeds this from THE one hook that sees every ring append site
(airlog_keeper), in its thread; nothing here speaks or decides, and nothing
here may ever stop the air: every entry point swallows its own failure.

data/system3_origin.sqlite3   origin / convs / turns / reports / meta
data/system3_origin_reports/  one JSON coverage report per UTC day, kept
"""
from __future__ import annotations

import calendar
import collections
import json
import re
import sqlite3
import threading
import time
import zlib
from pathlib import Path
from typing import Any

SCHEMA = "system3.origin/1"
FULL_DAYS = 7.0                      # the full record, then compacted forever
SETTLE_S = 90.0                      # an unstamped row waits this long for its ledger row
MARKER_LINK_S = 900.0                # a desk marker links to the road it announces within this
PUB_STATES = ("published", "stream", "both", "box", "page", "airing")
SKIP_KINDS = frozenset({"chat", "image_analysis", "song_analysis", "hangup"})
HEARD_KEY = "heard_ack_at"
PUNCT = re.compile(r"^(.*)-punct-\d+$")

# Code paths that ARE a forced road: the never-quiet fillers, the operator's
# taps and sends, the desk's own noises, the live set. Matched against the
# ring append's frame chain (innermost first). No dice are invented for them.
FORCED_PATHS: dict[str, tuple[str, str]] = {
    "gold_fill_gap": ("gold", "never-quiet: a run of banked gold bars filled a gap"),
    "continuity_air": ("emergency_host", "never-quiet: the emergency host's recorded pair covered a silence"),
    "script_line_replay": ("operator", "the operator tapped Replay on a line in the script"),
    "response_bank_play_api": ("operator", "the operator played a response-bank take"),
    "response_bank_play": ("operator", "the operator played a response-bank take"),
    "gen_ads_send": ("operator", "the operator sent a generated ad to the air"),
    "gen_ads_broadcast": ("operator", "the operator broadcast a generated ad"),
    "sfx_video_cue_api": ("operator", "the operator cued a clip on the video wall"),
    "radio_next_api": ("operator", "the operator tapped Next"),
    "_desk_sound": ("desk", "the desk's own noise on the call road (a phone ringing, a receiver down)"),
    "dj_police_outside": ("operator", "the operator sent the officer outside (the megaphone)"),
    "pine_speak_ack": ("operator", "the station answering the operator's Pine Chat request"),
}
# Frames that carry every road's lines: never named as THE producer.
GENERIC_FRAMES = frozenset({
    "_dj_speak_floorless", "dj_speak", "ad_booth_row", "_speak_turns_floorless",
    "speak_turns", "append", "extend", "insert", "_origin_path", "_floor_shell",
    "run", "_run", "_run_once", "run_forever", "<module>", "wrapper", "inner"})

# Rows that are LABELS the booth writes for a road (a desk marker, a sponsor
# spot's listing): linked to a stamped line of the road they announce - the
# first one after (a call, a bulletin) or the spot the listing sits on.
MARKER_LINKS = {"call": ("caller", "call"), "news": ("news",), "sponsor": ("ad",)}
SPONSOR_LISTING = "\U0001f4e3 sponsor spot"


def label_kind(c: dict[str, Any]) -> str:
    """"" for an item that is not a label; else what it announces."""
    text = str(c.get("text") or "")
    low = text.lower()
    if c.get("road") == "desk marker":
        if c.get("kind") in ("call", "news"):
            return str(c.get("kind"))
        return "call" if low.startswith("on line") else "news" if low.startswith("news") else "desk"
    if str(c.get("kind") or "") == "ad" and text.startswith(SPONSOR_LISTING):
        return "sponsor"
    return ""


# --- small pure helpers --------------------------------------------------------

def _pack(value: Any) -> bytes:
    return zlib.compress(json.dumps(value, separators=(",", ":"), default=str).encode("utf-8"), 6)


def _unpack(blob: Any) -> Any:
    if blob is None:
        return None
    try:
        return json.loads(zlib.decompress(blob).decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _words(text: Any, cap: int = 160) -> str:
    return " ".join(str(text or "").split())[:cap]


def _f(x: Any) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def day_of(at: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(float(at or 0)))


def eligible(entry: Any) -> bool:
    """Is this ring / air-log row an ITEM that reached the air (or a label the
    booth showed for one)? Not yet aired rows are not items yet."""
    if not isinstance(entry, dict) or not entry.get("id"):
        return False
    kind = str(entry.get("kind") or "")
    if kind in SKIP_KINDS:
        return False
    who = str(entry.get("who") or "")
    if who == "host" and kind != "chat":
        return True                                   # a desk marker ("On line 3: X")
    if who == "board" and str(entry.get("sfx_dir") or "") == "the desk":
        return True                                   # the phone ringing
    if entry.get(HEARD_KEY):
        return True
    return str(entry.get("aired") or "") in PUB_STATES


def road_of(entry: dict[str, Any], stamp: dict[str, Any] | None = None) -> str:
    """The road an item came down, in the operator's words."""
    kind = str(entry.get("kind") or "")
    who = str(entry.get("who") or "")
    rnd = str(entry.get("round") or "")
    if kind == "record":
        return "record"
    if who == "host" and kind != "chat":
        return "desk marker"
    if kind == "sfx" or who == "board":
        return "board clip"
    if kind in ("sfxguy", "drop") or who == "drop":
        return "sfx guy"
    if kind == "emergency_host" or entry.get("emergency"):
        return "emergency host"
    if (kind == "interject" and rnd == "gold") or (stamp or {}).get("gold"):
        return "gold"
    if kind in ("megaphone", "ack"):
        return "operator"
    if entry.get("replay") and entry.get("replay_of"):
        return "operator replay"
    if who in ("caller", "caller2"):
        return "caller"
    if kind == "ad" and str(entry.get("text") or "").startswith("\U0001f4e3"):
        return "ad spot"
    if kind in ("ad", "manager", "station_id", "news", "gallery", "open", "intro",
                "outro", "track_talk", "upstairs", "interject", "reply", "request"):
        return kind if not rnd or rnd == kind else "%s (%s)" % (kind, rnd)
    return "round: " + (rnd or "banter")


def frame_chain(entry: dict[str, Any]) -> list[str]:
    return [p for p in str(entry.get("origin_path") or "").split("<") if p]


def producer_of(chain: list[str]) -> str:
    """The first frame that is not a door every road shares."""
    for name in chain:
        if name.split(":")[0] not in GENERIC_FRAMES:
            return name
    return chain[0] if chain else ""


def forced_by_path(chain: list[str]) -> dict[str, Any] | None:
    for name in chain:
        fn = name.split(":")[0]
        if fn in FORCED_PATHS:
            road, trigger = FORCED_PATHS[fn]
            return {"road": road, "trigger": trigger, "by": fn, "how": "code path"}
    return None


# --- rolls: the tables and the dice ----------------------------------------------

def _roll(table: str, rec: Any, **extra: Any) -> dict[str, Any] | None:
    """One recorded roll, compact: which table, what it landed on, the die."""
    if not isinstance(rec, dict):
        return None
    out: dict[str, Any] = {"table": str(table)[:60]}
    for k in ("key", "label", "picked", "dice", "u", "index", "of", "odds", "hit", "kind", "recorded_on"):
        v = rec.get(k)
        if v not in (None, "", [], {}):
            out[k] = (_words(v, 120) if isinstance(v, str) else v)
    out.update({k: v for k, v in extra.items() if v not in (None, "", [], {})})
    return out if len(out) > 1 else None


def stamp_rolls(stamp: dict[str, Any] | None, ledger: dict[str, Any] | None,
                entry: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The rolls a row carries on itself (its stamp, its ledger dice)."""
    out: list[dict[str, Any]] = []
    s = stamp if isinstance(stamp, dict) else {}
    sfx = s.get("sfx_roll") if isinstance(s.get("sfx_roll"), dict) else (
        (entry or {}).get("sfx_roll") if isinstance((entry or {}).get("sfx_roll"), dict) else None)
    if sfx:
        out.append(_roll("SFX category (%s)" % (sfx.get("road") or "board"), sfx.get("category")))
        out.append(_roll("SFX clip (%s)" % (sfx.get("road") or "board"), sfx.get("clip")))
    for name, keys in (("gold", ("run", "pick")), ("replay", ("chance", "pick")),
                       ("listening", ("seam", "pick"))):
        got = s.get(name)
        if isinstance(got, dict):
            for k in keys:
                out.append(_roll("%s.%s" % (name, k), got.get(k)))
    spin = (entry or {}).get("s3_spin")
    if isinstance(spin, dict):
        out.append(_roll("records." + str(spin.get("lane") or "spin"), spin.get("roll")))
        deal = spin.get("deal")
        if isinstance(deal, dict):
            out.append(_roll("records.rotation_deal", deal))
    roll = (entry or {}).get("s3_roll")
    if isinstance(roll, dict):
        out.append(_roll(str(roll.get("key") or "dice door"), roll))
    dice = (ledger or {}).get("dice")
    if isinstance(dice, dict):
        inner = dice.get("s3") if isinstance(dice.get("s3"), dict) else {}
        out.append(_roll("line dice (%s)" % (dice.get("axis") or "axis"),
                         {"picked": dice.get("text"), "dice": dice.get("roll")},
                         phase=inner.get("phase"), es=inner.get("es")))
    return [r for r in out if r]


def decision_roll(ev: dict[str, Any]) -> dict[str, Any] | None:
    """A System 3 decision event, compact: id, table (family / stage), what it
    selected, the die and of how many."""
    if not isinstance(ev, dict):
        return None
    sel = ev.get("selected") if isinstance(ev.get("selected"), dict) else {}
    rng = ev.get("rng") if isinstance(ev.get("rng"), dict) else {}
    stages = [st for st in (ev.get("stages") or []) if isinstance(st, dict)]
    last = stages[-1] if stages else {}
    tables = [str(st.get("selected")) for st in stages if st.get("selected") not in (None, "")]
    out = {"id": str(ev.get("event_id") or ""), "table": str(ev.get("family") or ""),
           "path": " > ".join(tables)[:120] if tables else "",
           "picked": _words(sel.get("label") or sel.get("id") or "", 120),
           "dice": rng.get("dice"), "u": rng.get("u"),
           "index": last.get("selected_index"), "of": last.get("of"),
           "authority": sel.get("authority") or ("rolled" if rng else "obligated")}
    return {k: v for k, v in out.items() if v not in (None, "", [])}


# --- store refs: where the thing was drawn from --------------------------------

def store_refs(entry: dict[str, Any], stamp: dict[str, Any] | None, road: str,
               ledger: dict[str, Any] | None = None, observations: Any = None,
               context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    s = stamp if isinstance(stamp, dict) else {}
    led = ledger or {}
    ctx = context or {}
    out: list[dict[str, Any]] = []
    text = str(entry.get("text") or "")
    if road == "board clip":
        sfx = s.get("sfx_roll") if isinstance(s.get("sfx_roll"), dict) else (
            entry.get("sfx_roll") if isinstance(entry.get("sfx_roll"), dict) else {})
        cat = sfx.get("category") if isinstance(sfx.get("category"), dict) else {}
        clip = sfx.get("clip") if isinstance(sfx.get("clip"), dict) else {}
        folder = str(entry.get("sfx_dir") or cat.get("label") or "")
        out.append({"kind": "sfx library", "folder": folder,
                    "file": _words(text.replace("\U0001f50a", ""), 120),
                    "key": str(entry.get("sfx") or entry.get("sfx_sample_id") or entry.get("sfx_video_id") or ""),
                    "pool": str(sfx.get("road") or ("the desk" if folder == "the desk" else "")),
                    "index": clip.get("index"), "of": clip.get("of"),
                    "video": bool(entry.get("video") or entry.get("sfx_video_id"))})
    if road == "board clip":
        m = match_pick(entry, ctx)
        if m:
            out.append({"kind": "sfx matcher", "pool": m.get("road"), "line": m.get("line"),
                        "line_source": m.get("line_source"), "why": m.get("why"), "score": m.get("score"),
                        "cands": m.get("cands"), "tied": m.get("tied"), "eligible": m.get("eligible"),
                        "removed": {k: v for k, v in (m.get("removed") or {}).items() if v},
                        "words": {k: v for k, v in (m.get("words") or {}).items() if v}})
    if road == "sfx guy":
        got = None
        for o in observations or []:
            if (isinstance(o, dict) and o.get("family") == "SFXGUY"
                    and _words(o.get("line"), 400) == _words(text, 400)):
                got = o
                break
        draws = (got or {}).get("draws") or []
        d = draws[-1] if draws and isinstance(draws[-1], dict) else {}
        st = d.get("store") if isinstance(d.get("store"), dict) else {}
        out.append({"kind": st.get("kind") or {"news": "sfx guy news desk", "reaction": "sfx guy warped lines"}.get(
                        str((got or {}).get("kind") or ""), "sfx guy quip shelf"),
                    "db": st.get("db") or "", "pool": d.get("pool") or (got or {}).get("kind") or "",
                    "index": d.get("index"), "of": d.get("of"),
                    "candidates": d.get("candidates") if d.get("candidates") else None})
    gold = s.get("gold") if isinstance(s.get("gold"), dict) else None
    if gold:
        out.append({"kind": "gold bars", "key": str(gold.get("bar") or ""),
                    "minted": gold.get("minted"), "firing": gold.get("firing")})
    rep = s.get("replay") if isinstance(s.get("replay"), dict) else None
    if rep:
        out.append({"kind": "speech bank (re-air)", "pool": str(rep.get("road") or ""),
                    "first_aired": rep.get("first_aired"), "airing": rep.get("airing")})
    lis = s.get("listening") if isinstance(s.get("listening"), dict) else None
    if lis:
        pick = lis.get("pick") if isinstance(lis.get("pick"), dict) else {}
        out.append({"kind": "listening responses", "index": pick.get("index"), "of": pick.get("of")})
    if road == "emergency host":
        out.append({"kind": "emergency reserve (continuity bank)", "key": _words(text, 120)})
    if road.startswith("ad") or str(entry.get("round") or "") == "ad" or entry.get("ad_id"):
        prod = str(entry.get("product") or "")
        now_ad = ctx.get("ad_now") if isinstance(ctx.get("ad_now"), dict) else {}
        at = _f(entry.get("air_at") or entry.get("ts"))
        if not prod and now_ad and abs(at - _f(now_ad.get("at"))) < 600:
            prod = str(now_ad.get("product") or "")
        if prod or entry.get("ad_id") or entry.get("ad_audio"):
            out.append({"kind": "ad book", "product": prod[:160], "key": str(entry.get("ad_id") or ""),
                        "file": str(entry.get("ad_audio") or ""),
                        "picture": ((entry.get("images") or [""])[0] if entry.get("images") else "")})
    if road.startswith("manager") or str(entry.get("kind") or "") == "manager":
        out.append({"kind": "upstairs pages", "file": str(entry.get("media") or "")})
    if road == "record":
        spin = entry.get("s3_spin") if isinstance(entry.get("s3_spin"), dict) else {}
        out.append({"kind": "record library", "key": str(entry.get("track_id") or ""),
                    "pool": str(spin.get("lane") or ""), "file": _words(text, 160)})
    if road == "desk marker":
        low = text.lower()
        if str(entry.get("kind") or "") == "call" or low.startswith("on line"):
            out.append({"kind": "call line", "key": _words(text.split(":", 1)[-1], 80),
                        "pool": _words(text.split(":", 1)[0], 40)})
        elif str(entry.get("kind") or "") == "news" or low.startswith("news"):
            out.append({"kind": "news wire", "key": _words(text.split(":", 1)[-1], 200)})
    src = str(led.get("source") or entry.get("source") or "")
    if src:
        out.append({"kind": "document" if "." in src else "stock list", "file": src[:120]})
    media = str(entry.get("clip_media") or entry.get("media") or "")
    if media and road not in ("board clip", "record"):
        out.append({"kind": "voice take", "file": media[:80],
                    "window": [entry.get("clip_from"), entry.get("clip_until")]
                    if entry.get("clip_from") is not None else None})
    clean = []
    for r in out:
        r = {k: v for k, v in r.items() if v not in (None, "", [], {}, False)}
        if len(r) > 1:
            clean.append(r)
    return clean


def match_pick(entry: dict[str, Any], context: dict[str, Any] | None) -> dict[str, Any] | None:
    """The matcher's working for this clip, if it was a matched pick (by clip id,
    within ten minutes of the air)."""
    picks = (context or {}).get("match_picks")
    if not isinstance(picks, dict):
        return None
    for key in (entry.get("sfx"), entry.get("sfx_sample_id"), entry.get("sfx_video_id")):
        m = picks.get(str(key or ""))
        if isinstance(m, dict) and abs(_f(m.get("at")) - _f(entry.get("air_at") or entry.get("ts"))) <= 600:
            return m
    return None


# --- the record ------------------------------------------------------------------

def build(entry: dict[str, Any], ledger: dict[str, Any] | None = None,
          stamp: dict[str, Any] | None = None, conv: dict[str, Any] | None = None,
          context: dict[str, Any] | None = None, inferred_path: str = "") -> dict[str, Any]:
    """One aired item -> its origin record. Pure.

    entry   the ring row (live) or the air-log row (replay)
    ledger  its script-ledger row (block, ord, dice, system3, source ...)
    stamp   its System 3 stamp (conversation, turn, sub-rolls), if any
    conv    what System 3's store holds for that conversation:
            {"exists", "turn": [decision events of the line's turn],
             "round": [conversation-level decisions], "observations": [...]}
    """
    e = entry or {}
    led = ledger or {}
    s = dict(stamp) if isinstance(stamp, dict) else {}
    c = conv or {}
    lid = str(e.get("id") or e.get("line_id") or "")
    chain = frame_chain(e)
    path = "<".join(chain) or inferred_path
    road = road_of(e, s)
    cid = str(s.get("conversation_id") or "")
    tid = str(s.get("turn_id") or "")
    rolls = stamp_rolls(s, led, e)
    turn_decisions = [d for d in (decision_roll(ev) for ev in (c.get("turn") or [])) if d]
    obs = list(c.get("observations") or [])
    # the forced reason, if this is a forced road - explicit first
    forced = None
    for cand in (e.get("origin_forced"), s.get("forced")):
        if isinstance(cand, dict) and cand.get("road"):
            forced = dict(cand, how=cand.get("how") or "stamped at the door")
            break
    if forced is None:
        for o in obs:
            if (isinstance(o, dict) and o.get("family") == "INJECT"
                    and str(o.get("line_id") or "") == lid and lid):
                forced = {"road": "injected", "trigger": _words(o.get("why"), 300),
                          "by": _words(o.get("by"), 120), "how": "System 3 INJECT node"}
                break
    if forced is None and road == "emergency host":
        forced = {"road": "emergency_host", "by": "continuity_air", "how": "the road",
                  "trigger": "never-quiet: " + (_words(e.get("emergency_reason"), 240)
                                                or "the emergency host's recorded pair covered a silence")}
    if forced is None and road == "gold":
        g = s.get("gold") if isinstance(s.get("gold"), dict) else {}
        run = g.get("run") if isinstance(g.get("run"), dict) else {}
        gap = (context or {}).get("gold_why") if isinstance((context or {}).get("gold_why"), dict) else {}
        if str(run.get("key") or "") == "gold.in_round":
            trigger = "never-quiet: a banked gold bar fires inside the round (gold.in_round)"
        elif gap.get("why") and abs(_f(e.get("air_at") or e.get("ts")) - _f(gap.get("at"))) <= 300:
            trigger = "never-quiet: a gold run filled a gap - " + _words(gap.get("why"), 200)
        else:
            trigger = "never-quiet: a banked gold bar filled a gap"
        forced = {"road": "gold", "by": "gold_fill_gap", "how": "the road", "trigger": trigger,
                  "detail": _words(g.get("label"), 200)}
    if forced is None and road == "operator replay":
        forced = {"road": "operator", "by": "script_line_replay", "how": "the road",
                  "trigger": "the operator replayed line %s" % str(e.get("replay_of") or "")[:48],
                  "of": str(e.get("replay_of") or "")[:48]}
    spin = e.get("s3_spin") if isinstance(e.get("s3_spin"), dict) else None
    if forced is None and spin and spin.get("forced"):
        forced = {"road": "records: " + str(spin.get("lane") or ""), "by": "dj_next_track", "how": "the spin",
                  "trigger": _words(spin.get("why") or "no roll owns this lane", 200)}
    if forced is None and road == "board clip" and str(e.get("sfx_dir") or "") == "the desk":
        forced = {"road": "desk", "by": "_desk_sound", "how": "the road",
                  "trigger": "the desk's own noise on the call road (%s)" % _words(e.get("text"), 60)}
    if forced is None:
        forced = forced_by_path(chain)
    verdict, why = "rogue", ""
    if forced:
        verdict = "forced"
        why = "forced: %s - %s" % (forced.get("road"), forced.get("trigger"))
    elif cid and (rolls or turn_decisions):
        verdict, why = "rolled", "System 3 node with %d roll(s)" % (len(rolls) + len(turn_decisions))
    elif cid and (c.get("round") or c.get("any") or c.get("exists") is None):
        # the conversation's own decisions shaped it (a door node, a line draw)
        verdict = "rolled"
        why = ("System 3 node: its conversation's %d decision(s)" % int(c.get("any") or len(c.get("round") or []))
               if (c.get("round") or c.get("any")) else "System 3 node (conversation not read)")
    elif spin and (spin.get("roll") or spin.get("deal") or spin.get("due")):
        verdict, why = "rolled", "the spin's recorded roll"
    elif isinstance(e.get("s3_roll"), dict):
        verdict, why = "rolled", "a dice-door roll recorded for this row"
    elif rolls:
        verdict, why = "rolled", "its own recorded System 3 dice (%s)" % ", ".join(
            str(r.get("table")) for r in rolls[:3])
    elif cid:
        why = "stamped %s but System 3 holds no roll for it" % cid
    else:
        why = "no System 3 stamp"
    lk = label_kind({"road": road, "kind": e.get("kind"), "text": e.get("text")})
    if verdict == "rogue" and lk and not cid:
        # a label the booth writes for a road; linked to that road's node when
        # its line is found (OriginLedger._link_label), else honestly forced
        verdict = "forced"
        forced = {"road": "desk label", "by": "the booth", "how": "a label, not a line",
                  "trigger": "the booth labels the %s it announces" % {
                      "call": "call", "news": "news bulletin", "sponsor": "sponsor spot"}.get(lk, "road")}
        why = "forced: desk label - " + forced["trigger"]
    rogue = None
    if verdict == "rogue":
        rogue = {"path": path or "unknown (not captured)", "producer": producer_of(chain) or inferred_path,
                 "why": why}
    heard = _f(e.get(HEARD_KEY))
    air_at = _f(e.get("air_at") or e.get("ts"))
    compact = {
        "schema": SCHEMA, "line_id": lid, "air_at": round(air_at, 3), "road": road,
        "verdict": verdict, "why": why, "kind": str(e.get("kind") or ""), "who": str(e.get("who") or ""),
        "round": str(e.get("round") or ""), "text": _words(e.get("text"), 160),
        "receipt": {k: v for k, v in (("aired", str(e.get("aired") or "")), ("heard_at", round(heard, 3) or None),
                                      ("seconds", e.get("seconds")), ("heard_by", e.get("heard_ack_by")))
                    if v not in (None, "")},
        "script": {k: v for k, v in (("block", led.get("block")), ("ord", led.get("ord")),
                                     ("sid", str(led.get("sid") or e.get("sid") or "")),
                                     ("segment", ((led.get("segment") or {}).get("id")
                                                  if isinstance(led.get("segment"), dict) else led.get("segment"))),
                                     ("turn", e.get("turn") if e.get("turn") is not None else led.get("turn")))
                   if v not in (None, "")},
        "system3": {k: v for k, v in (("conversation_id", cid), ("turn_id", tid),
                                      ("road", s.get("road")), ("mode", s.get("mode")),
                                      ("config_hash", s.get("config_hash")),
                                      ("via", s.get("via")),   # [s3-account-p2] how the stamp was known
                                      ("decisions", [d["id"] for d in turn_decisions if d.get("id")]),
                                      ("turn_key", (cid + "|" + tid) if cid and tid and turn_decisions else ""))
                    if v not in (None, "", [])},
        "tables": rolls,
        "store": store_refs(e, s, road, led, obs, context),
        "path": path, "producer": producer_of(chain) or inferred_path,
    }
    if forced:
        compact["forced"] = forced
    if rogue:
        compact["rogue"] = rogue
    if e.get("replay_of"):
        compact["of"] = str(e.get("replay_of"))[:48]
    full = {
        "entry": {k: v for k, v in e.items() if k not in ("system_prompts", "vector", "dossier")
                  and not k.startswith("_")},
        "ledger": {k: v for k, v in led.items() if k != "system_prompts"},
        "stamp": s,
        "match": match_pick(e, context),
        "observations": [o for o in obs if isinstance(o, dict) and lid   # [s3-account-p2] "lines" may be a count
                         and lid in (o.get("lines") if isinstance(o.get("lines"), (list, tuple)) else ())][:8],
    }
    out = {"compact": compact, "full": full}
    # the turn's decisions and the conversation's, kept ONCE (every line of a turn
    # - its chunks, its welded clip, the SFX Guy after it - shares them)
    if cid and tid and turn_decisions:
        out["turn"] = {"key": cid + "|" + tid, "cid": cid, "compact": turn_decisions,
                       "full": {"decisions": list(c.get("turn") or []),
                                "observations": [o for o in obs if isinstance(o, dict)
                                                 and o.get("turn_id") == tid][:24]}}
    if cid and (c.get("round") or obs):
        out["conv"] = {"cid": cid, "compact": {"decisions": [d for d in (c.get("round") or []) if d]},
                       "full": {"observations": [o for o in obs if isinstance(o, dict)
                                                 and not o.get("turn_id")][:24]}}
    return out


def order_key(e: dict[str, Any]) -> int:
    if label_kind({"road": road_of(e), "kind": e.get("kind"), "text": e.get("text")}):
        return 2
    return 1 if PUNCT.match(str(e.get("id") or "")) else 0


def settled(record: dict[str, Any], now: float, seen_at: float, ledger_known: bool) -> bool:
    """A verdict is final once it cannot improve: rolled/forced with the
    script row known (or the settle window gone); rogue only after the window,
    since the ledger may still stamp it."""
    c = record.get("compact") or {}
    at = max(_f(c.get("air_at")), _f(seen_at))
    if c.get("verdict") in ("rolled", "forced"):
        return ledger_known or now - at > SETTLE_S
    if label_kind(c) and not c.get("announces"):
        return now - at > MARKER_LINK_S
    return now - at > SETTLE_S


# --- the durable store ------------------------------------------------------------

class OriginLedger:
    """data/system3_origin.sqlite3 - one connection, one lock, every method sync
    (the station calls them in threads)."""

    def __init__(self, path: Any, reports_dir: Any = None, system3_db: Any = None):
        self.path = Path(path)
        self.reports_dir = Path(reports_dir) if reports_dir else self.path.parent / "system3_origin_reports"
        self.system3_db = Path(system3_db) if system3_db else None
        self.lock = threading.RLock()
        self._db = None                      # opened on first use, never at import
        self._init_state()

    @property
    def db(self) -> sqlite3.Connection:
        if self._db is None:
            with self.lock:
                if self._db is None:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    db = sqlite3.connect(str(self.path), check_same_thread=False, timeout=15)
                    db.execute("PRAGMA journal_mode=WAL")
                    db.execute("PRAGMA synchronous=NORMAL")
                    with db:
                        db.executescript("""
                        CREATE TABLE IF NOT EXISTS origin(
                            line_id TEXT PRIMARY KEY, air_at REAL NOT NULL, day TEXT NOT NULL, road TEXT,
                            verdict TEXT, kind TEXT, who TEXT, conversation_id TEXT, turn_id TEXT,
                            block INTEGER, ord INTEGER, producer TEXT, why TEXT,
                            settled INTEGER NOT NULL DEFAULT 0,
                            compact BLOB NOT NULL, full BLOB, updated REAL NOT NULL);
                        CREATE INDEX IF NOT EXISTS origin_air ON origin(air_at);
                        CREATE INDEX IF NOT EXISTS origin_verdict ON origin(verdict, air_at);
                        CREATE INDEX IF NOT EXISTS origin_day ON origin(day, road);
                        CREATE INDEX IF NOT EXISTS origin_conv ON origin(conversation_id);
                        CREATE TABLE IF NOT EXISTS convs(
                            conversation_id TEXT PRIMARY KEY, at REAL NOT NULL, compact BLOB NOT NULL, full BLOB);
                        CREATE TABLE IF NOT EXISTS turns(
                            turn_key TEXT PRIMARY KEY, conversation_id TEXT, at REAL NOT NULL,
                            compact BLOB NOT NULL, full BLOB);
                        CREATE TABLE IF NOT EXISTS reports(day TEXT PRIMARY KEY, made REAL NOT NULL,
                                                           body TEXT NOT NULL);
                        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                        """)
                    self._db = db
        return self._db

    def _init_state(self) -> None:
        self._s3 = None
        self._conv_cache: "collections.OrderedDict[str, tuple[float, dict]]" = collections.OrderedDict()
        self._state: "collections.OrderedDict[str, tuple[str, float, int]]" = collections.OrderedDict()
        self._ledger: "collections.OrderedDict[str, dict]" = collections.OrderedDict()
        self._side: "collections.deque[dict]" = collections.deque(maxlen=400)
        self._markers: list[dict[str, Any]] = []
        self.ledger_cap = 8000               # script rows held for the tick (a replay raises it)
        self.marker_cap = 60                 # desk markers waiting to link (ditto)
        self._recent: "collections.deque[dict]" = collections.deque(maxlen=400)
        self._memo: "collections.OrderedDict[str, dict]" = collections.OrderedDict()   # built this run
        self._shared: dict[str, int] = {}    # turns / conversations written, by what was known
        self._recovered: "collections.OrderedDict[str, tuple]" = collections.OrderedDict()   # [s3-account-p2]
        self.metrics = {"ticks": 0, "written": 0, "rogue": 0, "forced": 0, "rolled": 0,
                        "errors": 0, "last_error": "", "compacted": 0, "reports": 0}

    # -- System 3's store, read-only -------------------------------------------------
    def _s3db(self):
        if self._s3 is None and self.system3_db and self.system3_db.exists():
            self._s3 = sqlite3.connect("file:%s?mode=ro" % self.system3_db, uri=True,
                                       check_same_thread=False, timeout=5)
        return self._s3

    def conversation(self, cid: str, turn_id: str = "", fresh: bool = False) -> dict[str, Any]:
        """{"exists", "turn", "round", "observations"} for a conversation - one
        indexed read of System 3's events, memoised a minute."""
        if not cid:
            return {}
        now = time.time()
        got = self._conv_cache.get(cid)
        if got is None or fresh or now - got[0] > 60:
            body = {"exists": None, "events": []}
            db = self._s3db()
            if db is not None:
                try:
                    rows = db.execute("SELECT kind, family, turn_id, body FROM events WHERE conversation_id=? "
                                      "ORDER BY id", (cid,)).fetchall()
                    body = {"exists": bool(rows), "events": [
                        (k, f, t or "", _unpack(b)) for k, f, t, b in rows]}
                except Exception as exc:  # noqa: BLE001
                    self._err("system3 read", exc)
            got = (now, body)
            self._conv_cache[cid] = got
            self._conv_cache.move_to_end(cid)
            while len(self._conv_cache) > 400:
                self._conv_cache.popitem(last=False)
        body = got[1]
        evs = body.get("events") or []
        return {"exists": body.get("exists"),
                "any": sum(1 for k, f, t, b in evs if k == "decision"),
                "turn": [b for k, f, t, b in evs if k == "decision" and turn_id and t == turn_id and b],
                "round": [decision_roll(b) for k, f, t, b in evs if k == "decision" and not t and b],
                "observations": [dict(b, turn_id=b.get("turn_id") or t) for k, f, t, b in evs
                                 if k == "observation" and isinstance(b, dict)
                                 and f in ("SFXGUY", "INJECT", "SFX", "LINE")]}

    def _err(self, where: str, exc: Exception) -> None:
        self.metrics["errors"] += 1
        self.metrics["last_error"] = "%s: %s: %s" % (where, type(exc).__name__, str(exc)[:200])

    # -- feeds -------------------------------------------------------------------------
    def ledger_note(self, block: int, at: float, sid: str, round_kind: str, segment: Any,
                    rows: list[dict[str, Any]]) -> None:
        """The script ledger committed these rows: remember their place and
        stamps for the tick (dict work only - this may run on the loop)."""
        seg = segment.get("id") if isinstance(segment, dict) else segment
        for i, r in enumerate(rows or []):
            lid = str((r or {}).get("line_id") or "")
            if not lid:
                continue
            self._ledger[lid] = {
                "block": int(block or 0), "ord": int(r.get("_ord", i)), "at": at, "sid": str(sid or ""),
                "round": str(round_kind or ""), "segment": seg, "turn": r.get("turn"),
                "system3": dict(r["system3"]) if isinstance(r.get("system3"), dict) else None,
                "dice": dict(r["dice"]) if isinstance(r.get("dice"), dict) else None,
                "source": str(r.get("source") or "")[:120], "cue": str(r.get("cue") or ""),
                "scripted": bool(r.get("scripted", True)),
                "model_call": r.get("model_call") if isinstance(r.get("model_call"), dict) else None,
                "scenario": r.get("scenario") if isinstance(r.get("scenario"), dict) else None}
            self._ledger.move_to_end(lid)
        while len(self._ledger) > self.ledger_cap:
            self._ledger.popitem(last=False)

    def side_note(self, item: dict[str, Any]) -> None:
        """An aired item that never passes the ring (a record on the deck, the
        megaphone, a Pine Chat answer): queued for the next tick."""
        if isinstance(item, dict) and item.get("id"):
            item.setdefault("air_at", time.time())
            self._side.append(dict(item))

    # -- the tick ------------------------------------------------------------------------
    def tick(self, entries: list[dict[str, Any]], peek_stamp: Any = None,
             context: dict[str, Any] | None = None, now: float = 0.0) -> dict[str, int]:
        """Sync, in the keeper's thread. Every eligible ring row not yet final is
        (re)built and upserted when its record changed; markers link forward."""
        now = float(now or time.time())
        self.metrics["ticks"] += 1
        out = {"seen": 0, "written": 0}
        rows = [e for e in (entries or []) if isinstance(e, dict)]
        while self._side:
            rows.append(self._side.popleft())
        # a welded clip ("<id>-punct-N") after the line it belongs to; a label
        # (a desk marker, a sponsor listing) after the lines it may announce
        rows.sort(key=order_key)
        batch = []
        for e in rows:
            try:
                if not eligible(e):
                    continue
                lid = str(e["id"])
                st = self._state.get(lid)
                if st and st[2]:
                    continue                                   # final
                out["seen"] += 1
                seen_at = st[1] if st else now
                rec, led_known = self.build_live(e, peek_stamp, context)
                digest = self._digest(rec)
                final = settled(rec, now, seen_at, led_known)
                if st and st[0] == digest and not final:
                    continue
                batch.append((rec, final))
                self._state[lid] = (digest, seen_at, 1 if final else 0)
                self._state.move_to_end(lid)
            except Exception as exc:  # noqa: BLE001
                self._err("tick", exc)
        while len(self._state) > 30000:
            self._state.popitem(last=False)
        if batch:
            out["written"] = self.upsert(batch)
        return out

    def build_live(self, e: dict[str, Any], peek_stamp: Any = None,
                   context: dict[str, Any] | None = None) -> tuple[dict[str, Any], bool]:
        lid = str(e.get("id") or "")
        led = self._ledger.get(lid)
        m = PUNCT.match(lid)
        stamp = None
        if isinstance(e.get("system3"), dict) and e["system3"].get("conversation_id"):
            stamp = e["system3"]
        elif led and isinstance(led.get("system3"), dict) and led["system3"].get("conversation_id"):
            stamp = led["system3"]
        elif callable(peek_stamp):
            try:
                got = peek_stamp(lid)
                stamp = got if isinstance(got, dict) and got.get("conversation_id") else None
            except Exception:  # noqa: BLE001
                stamp = None
        if stamp is None and not m and not e.get("origin_forced"):   # [s3-account-p2] a row that lost its stamp
            stamp, e = self._durable_origin(e, lid)
        if stamp is None and m:
            stamp, pforced = self._parent_stamp(e, m.group(1))
            if pforced and not e.get("origin_forced"):
                e = dict(e, origin_forced=pforced)
        conv = self.conversation(str((stamp or {}).get("conversation_id") or ""),
                                 str((stamp or {}).get("turn_id") or "")) if stamp else {}
        rec = build(e, led, stamp, conv, context)
        if e.get("recovery"):                    # [s3-account-p2] boot recovery put it back on the air
            rec["compact"]["republished"] = "after a restart, by boot recovery (page_recovery_start)"
            if e.get("recovered_from"):
                rec["compact"]["recovered_from"] = str(e["recovered_from"])[:48]
        self._link_label(rec)
        self._memo[lid] = rec["compact"]
        self._memo.move_to_end(lid)
        while len(self._memo) > 3000:
            self._memo.popitem(last=False)
        return rec, led is not None

    def _durable_origin(self, e: dict[str, Any], lid: str) -> tuple[Any, dict[str, Any]]:
        """[s3-account-p2] A row that reaches the ring WITHOUT its stamp (a
        preserved delivery republished after a restart, page_recovery_chat_rows;
        a ring row restored at boot) is still the line System 3 made. Its
        origin is read back from the two durable records that outlive the
        process - never guessed: (1) System 3's own line register (the lines
        table: line -> conversation, turn); (2) this ledger's record of the
        same line id from before, when that one was traced (rolled: its stamp;
        forced: its named reason). Neither: the row stands as it is. Returns
        (stamp or None, the row - with origin_forced when a forced reason came
        back). Memoised per id; a miss is looked up again after 60 s."""
        now = time.time()
        got = self._recovered.get(lid)
        if got is None or (not got[1] and not got[2] and now - got[0] > 60.0):
            stamp: dict[str, Any] = {}
            forced: dict[str, Any] | None = None
            # the line itself, then the heard line a recovered replay stands in for
            ids = [lid] + [str(x) for x in (e.get("recovered_from"),) if x and str(x) != lid]
            s3 = self._s3db()
            for key in ids:
                if stamp or s3 is None:
                    break
                try:
                    r = s3.execute("SELECT conversation_id, turn_id FROM lines WHERE line_id=?", (key,)).fetchone()
                except Exception:  # noqa: BLE001  (an older store with no line register)
                    r = None
                if r and r[0]:
                    stamp = {"conversation_id": str(r[0]), "turn_id": str(r[1] or ""),
                             "via": "System 3's line register" + ("" if key == lid else " (the line it replays, %s)" % key)}
            for key in ids:
                if stamp or forced:
                    break
                try:
                    prior = self.get(key)
                except Exception:  # noqa: BLE001
                    prior = None
                via = ("its origin record from before the restart" if key == lid
                       else "the origin record of the line it replays (%s)" % key)
                if isinstance(prior, dict) and not prior.get("announces"):
                    ps = prior.get("system3") or {}
                    pf = prior.get("forced") if isinstance(prior.get("forced"), dict) else None
                    if prior.get("verdict") == "rolled" and ps.get("conversation_id"):
                        stamp = {"conversation_id": str(ps["conversation_id"]), "turn_id": str(ps.get("turn_id") or ""),
                                 "via": via}
                    elif prior.get("verdict") == "forced" and pf and pf.get("road") != "desk label":
                        forced = dict(pf, how=via)
            got = (now, stamp, forced)
            self._recovered[lid] = got
            self._recovered.move_to_end(lid)
            while len(self._recovered) > 5000:
                self._recovered.popitem(last=False)
        stamp, forced = got[1], got[2]
        if forced and not e.get("origin_forced"):
            e = dict(e, origin_forced=dict(forced))
        return (dict(stamp) if stamp else None), e

    def _parent_stamp(self, e: dict[str, Any], parent_id: str) -> tuple[Any, Any]:
        """A clip welded to a line ("<id>-punct-N") is part of that line: its
        stamp, or the forced reason the line was aired under."""
        parent = self._ledger.get(parent_id)
        if parent and isinstance(parent.get("system3"), dict) and parent["system3"].get("conversation_id"):
            return dict(parent["system3"], via="the line it punctuates"), None
        got = self._memo.get(parent_id)
        if got is None:
            try:
                got = self.get(parent_id)
            except Exception:  # noqa: BLE001
                got = None
        if not got:
            return None, None
        if got.get("verdict") == "forced" and isinstance(got.get("forced"), dict):
            return None, dict(got["forced"], how="the line it punctuates (%s)" % parent_id[:12])
        s3 = got.get("system3") or {}
        if s3.get("conversation_id"):
            return {"conversation_id": s3["conversation_id"], "turn_id": s3.get("turn_id") or "",
                    "via": "the line it punctuates"}, None
        return None, None

    def _link_label(self, rec: dict[str, Any]) -> None:
        """A label (a desk marker, a sponsor listing) takes the node of a stamped
        line of the road it announces: the first one after it, or - for a
        listing written after its spot - the spot's own lines just before."""
        c = rec["compact"]
        lk = label_kind(c)
        if lk:
            wants = MARKER_LINKS.get(lk, ())
            for m in self._markers:
                if m.get("line_id") == c["line_id"]:
                    if m.get("link"):
                        self._apply_link(rec, m["link"])
                    return
            m = {"line_id": c["line_id"], "at": c["air_at"], "wants": wants}
            if lk == "sponsor":
                for r in reversed(self._recent):
                    if r["round"] in wants and 0 <= _f(c.get("air_at")) - r["at"] <= 600:
                        m["link"] = r
                        break
            self._markers.append(m)
            del self._markers[:-self.marker_cap]
            if m.get("link"):
                self._apply_link(rec, m["link"])
            return
        s3 = c.get("system3") or {}
        if c.get("verdict") != "rolled" or not s3.get("conversation_id"):
            return
        rnd = str(c.get("round") or "")
        link = {"line_id": c["line_id"], "conversation_id": s3.get("conversation_id"),
                "turn_id": s3.get("turn_id"), "road": c.get("road"), "round": rnd, "at": _f(c.get("air_at"))}
        self._recent.append(link)
        for m in self._markers:
            if (not m.get("link") and rnd in m.get("wants", ())
                    and -600 <= _f(c.get("air_at")) - _f(m.get("at")) <= MARKER_LINK_S):
                m["link"] = link

    @staticmethod
    def _apply_link(rec: dict[str, Any], link: dict[str, Any]) -> None:
        c = rec["compact"]
        c["verdict"] = "rolled"
        c["why"] = "a desk label for the %s it announces (line %s)" % (link.get("road"), link.get("line_id"))
        c.pop("rogue", None)
        c["system3"] = {"conversation_id": link.get("conversation_id"), "turn_id": link.get("turn_id"),
                        "via": "the line it announces: " + str(link.get("line_id"))}
        c["announces"] = str(link.get("line_id") or "")
        c.pop("forced", None)

    @staticmethod
    def _digest(rec: dict[str, Any]) -> str:
        c = rec.get("compact") or {}
        return "%s|%s|%s|%s|%s" % (c.get("verdict"), (c.get("script") or {}).get("block"),
                                   (c.get("receipt") or {}).get("aired"),
                                   len(c.get("tables") or []) + len((c.get("system3") or {}).get("decisions") or []),
                                   len(c.get("store") or []))

    def upsert(self, batch: list[tuple[dict[str, Any], bool]]) -> int:
        now = time.time()
        rows = []
        for rec, final in batch:
            c = rec["compact"]
            s3 = c.get("system3") or {}
            sc = c.get("script") or {}
            rows.append((c["line_id"], float(c.get("air_at") or now), day_of(c.get("air_at") or now),
                         c.get("road"), c.get("verdict"), c.get("kind"), c.get("who"),
                         s3.get("conversation_id") or "", s3.get("turn_id") or "",
                         sc.get("block"), sc.get("ord"), c.get("producer") or "", c.get("why") or "",
                         1 if final else 0, _pack(c), _pack(rec.get("full") or {}), now))
            if final and c.get("verdict") in self.metrics:
                self.metrics[c["verdict"]] += 1
        try:
            with self.lock, self.db:
                self._upsert_rows(rows, now)
                self._upsert_shared([rec for rec, _final in batch], now)
            self.metrics["written"] += len(rows)
            return len(rows)
        except Exception as exc:  # noqa: BLE001
            self._err("upsert", exc)
            return 0

    def _upsert_rows(self, rows: list[tuple], now: float) -> None:
        cut = now - FULL_DAYS * 86400
        self.db.executemany(
            "INSERT INTO origin(line_id,air_at,day,road,verdict,kind,who,conversation_id,turn_id,block,ord,"
            "producer,why,settled,compact,full,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(line_id) DO UPDATE SET air_at=excluded.air_at, day=excluded.day, road=excluded.road, "
            "verdict=excluded.verdict, kind=excluded.kind, who=excluded.who, "
            "conversation_id=excluded.conversation_id, turn_id=excluded.turn_id, block=excluded.block, "
            "ord=excluded.ord, producer=excluded.producer, why=excluded.why, settled=excluded.settled, "
            "compact=excluded.compact, full=CASE WHEN excluded.air_at < %r THEN NULL ELSE excluded.full END, "
            "updated=excluded.updated" % cut, rows)

    def _upsert_shared(self, recs: list[dict[str, Any]], now: float) -> None:
        """The turn's decisions and the conversation's, once each (compact forever,
        full for 7 days) - rewritten only when what is known of them grew."""
        cut = now - FULL_DAYS * 86400
        for rec in recs:
            at = float((rec.get("compact") or {}).get("air_at") or now)
            t = rec.get("turn")
            if isinstance(t, dict) and t.get("key"):
                size = len(t.get("compact") or []) * 100 + len((t.get("full") or {}).get("observations") or [])
                if self._shared.get(t["key"]) != size:
                    self.db.execute(
                        "INSERT INTO turns VALUES(?,?,?,?,?) ON CONFLICT(turn_key) DO UPDATE SET "
                        "compact=excluded.compact, full=excluded.full",
                        (t["key"], t.get("cid") or "", at, _pack(t.get("compact") or []),
                         None if at < cut else _pack(t.get("full") or {})))
                    self._shared[t["key"]] = size
            cv = rec.get("conv")
            if isinstance(cv, dict) and cv.get("cid"):
                size = len((cv.get("compact") or {}).get("decisions") or []) * 100 + len(
                    (cv.get("full") or {}).get("observations") or [])
                if self._shared.get("c|" + cv["cid"]) != size:
                    self.db.execute(
                        "INSERT INTO convs VALUES(?,?,?,?) ON CONFLICT(conversation_id) DO UPDATE SET "
                        "compact=excluded.compact, full=excluded.full",
                        (cv["cid"], at, _pack(cv.get("compact") or {}),
                         None if at < cut else _pack(cv.get("full") or {})))
                    self._shared["c|" + cv["cid"]] = size
        while len(self._shared) > 20000:
            self._shared.pop(next(iter(self._shared)))

    # -- readers ------------------------------------------------------------------------
    def get(self, line_id: str, full: bool = False) -> dict[str, Any] | None:
        with self.lock:
            row = self.db.execute("SELECT compact, full, settled FROM origin WHERE line_id=?",
                                  (str(line_id),)).fetchone()
            if not row:
                return None
            rec = _unpack(row[0]) or {}
            rec["settled"] = bool(row[2])
            s3 = rec.get("system3") or {}
            cid, tkey = s3.get("conversation_id"), s3.get("turn_key")
            conv_row = turn_row = None
            if cid:
                conv_row = self.db.execute("SELECT compact, full FROM convs WHERE conversation_id=?",
                                           (cid,)).fetchone()
                if conv_row:
                    rec["conversation_decisions"] = (_unpack(conv_row[0]) or {}).get("decisions") or []
            if tkey:
                turn_row = self.db.execute("SELECT compact, full FROM turns WHERE turn_key=?", (tkey,)).fetchone()
                if turn_row:
                    rec["turn_decisions"] = _unpack(turn_row[0]) or []
        if full:
            rec["full"] = _unpack(row[1])
            if isinstance(rec["full"], dict):
                rec["full"]["turn"] = _unpack(turn_row[1]) if turn_row else None
                rec["full"]["conversation"] = _unpack(conv_row[1]) if conv_row else None
            rec["retention"] = ("full (kept %d days)" % FULL_DAYS if row[1] is not None
                                else "compacted: ids, tables, rolls and store refs (kept forever)")
        else:
            rec["retention"] = "full" if row[1] is not None else "compacted"
        return rec

    def chain(self, line_id: str) -> dict[str, Any] | None:
        """The origin chain as nodes, top (the air) to bottom (the table / store /
        forced reason / rogue code path) - what every item opens to."""
        rec = self.get(line_id)
        if rec is None:
            return None
        nodes = [{"node": "air", "label": "on air", "line_id": rec.get("line_id"),
                  "at": rec.get("air_at"), **(rec.get("receipt") or {})}]
        sc = rec.get("script") or {}
        if sc:
            nodes.append({"node": "script", "label": "script ledger", **sc})
        nodes.append({"node": "road", "label": rec.get("road"), "kind": rec.get("kind"), "who": rec.get("who")})
        s3 = rec.get("system3") or {}
        if s3.get("conversation_id"):
            nodes.append({"node": "conversation", "label": "System 3 conversation", **s3})
        for t in rec.get("conversation_decisions") or []:
            nodes.append({"node": "roll", "scope": "round", **t})
        for t in rec.get("turn_decisions") or []:
            nodes.append({"node": "roll", "scope": "turn", **t})
        for t in rec.get("tables") or []:
            nodes.append({"node": "roll", "scope": "line", **t})
        for st in rec.get("store") or []:
            nodes.append({"node": "store", **st})
        if rec.get("forced"):
            nodes.append({"node": "forced", **rec["forced"]})
        if rec.get("rogue"):
            nodes.append({"node": "rogue", **rec["rogue"]})
        return {"line_id": rec.get("line_id"), "verdict": rec.get("verdict"), "why": rec.get("why"),
                "road": rec.get("road"), "text": rec.get("text"), "retention": rec.get("retention"),
                "settled": rec.get("settled"), "nodes": nodes, "record": rec}

    def find_record(self, track: str = "", at: float = 0.0, event: str = "") -> dict[str, Any] | None:
        """A record's (or a live set's) origin by its key: the spin of `track`
        nearest `at` (the latest without one), or the live set of `event`."""
        if event:
            like, args = "live:%s:%%" % event, ()
        elif track:
            like, args = "%%:%s:%%" % track, ()
        else:
            return None
        with self.lock:
            row = self.db.execute(
                "SELECT line_id FROM origin WHERE kind='record' AND line_id LIKE ? "
                "ORDER BY %s LIMIT 1" % ("ABS(air_at - ?)" if at else "air_at DESC"),
                (like,) + ((float(at),) if at else ()) + args).fetchone()
        return self.chain(row[0]) if row else None

    def untraced(self, since: float = 0.0, limit: int = 100) -> dict[str, Any]:
        since = float(since or (time.time() - 86400))
        with self.lock:
            rows = self.db.execute(
                "SELECT line_id, air_at, road, kind, who, producer, why, compact FROM origin "
                "WHERE verdict='rogue' AND settled=1 AND air_at>=? ORDER BY air_at DESC LIMIT ?",
                (since, max(1, min(1000, int(limit))))).fetchall()
            total = self.db.execute("SELECT COUNT(*) FROM origin WHERE verdict='rogue' AND settled=1 AND air_at>=?",
                                    (since,)).fetchone()[0]
            by = self.db.execute("SELECT producer, road, COUNT(*), MAX(air_at) FROM origin WHERE verdict='rogue' "
                                 "AND settled=1 AND air_at>=? GROUP BY producer, road ORDER BY 3 DESC LIMIT 30",
                                 (since,)).fetchall()
            all_n = self.db.execute("SELECT COUNT(*) FROM origin WHERE settled=1 AND air_at>=?",
                                    (since,)).fetchone()[0]
        items = []
        for lid, at, road, kind, who, prod, why, blob in rows:
            c = _unpack(blob) or {}
            items.append({"line_id": lid, "air_at": at, "road": road, "kind": kind, "who": who,
                          "producer": prod, "why": why, "text": c.get("text"),
                          "path": (c.get("rogue") or {}).get("path") or c.get("path")})
        return {"since": since, "count": int(total), "items_total": int(all_n), "items": items,
                "by_path": [{"producer": p or "unknown", "road": r, "count": n, "last": a} for p, r, n, a in by]}

    def coverage(self, since: float, until: float) -> dict[str, Any]:
        with self.lock:
            rows = self.db.execute(
                "SELECT road, verdict, COUNT(*) FROM origin WHERE air_at>=? AND air_at<? AND settled=1 "
                "GROUP BY road, verdict", (since, until)).fetchall()
            rogue = self.db.execute(
                "SELECT producer, road, why, COUNT(*) FROM origin WHERE air_at>=? AND air_at<? AND settled=1 "
                "AND verdict='rogue' GROUP BY producer, road, why ORDER BY 4 DESC LIMIT 20", (since, until)).fetchall()
            forced = self.db.execute(
                "SELECT road, why, COUNT(*) FROM origin WHERE air_at>=? AND air_at<? AND settled=1 "
                "AND verdict='forced' GROUP BY road, why ORDER BY 3 DESC LIMIT 20", (since, until)).fetchall()
        return coverage_report(rows, rogue, forced, since, until)

    def report_day(self, day: str, now: float = 0.0) -> dict[str, Any]:
        start = float(calendar.timegm(time.strptime(day, "%Y-%m-%d")))
        rep = self.coverage(start, start + 86400)
        rep["day"] = day
        rep["made"] = float(now or time.time())
        return rep

    def reports(self) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.db.execute("SELECT day, made, body FROM reports ORDER BY day DESC LIMIT 400").fetchall()
        out = []
        for d, m, b in rows:
            try:
                t = json.loads(b).get("totals") or {}
            except Exception:  # noqa: BLE001
                t = {}
            out.append({"day": d, "made": m, "totals": t})
        return out

    def report(self, day: str) -> dict[str, Any] | None:
        with self.lock:
            row = self.db.execute("SELECT body FROM reports WHERE day=?", (day,)).fetchone()
        return json.loads(row[0]) if row else None

    # -- housekeeping (hourly, in a thread) --------------------------------------------
    def housekeeping(self, now: float = 0.0) -> dict[str, int]:
        """Compact what is older than 7 days (the full blob goes; ids, tables, rolls
        and store refs stay forever) and write every finished day's report."""
        now = float(now or time.time())
        cut = now - FULL_DAYS * 86400
        out = {"compacted": 0, "reports": 0}
        try:
            with self.lock, self.db:
                cur = self.db.execute("UPDATE origin SET full=NULL WHERE air_at<? AND full IS NOT NULL", (cut,))
                out["compacted"] = cur.rowcount or 0
                self.db.execute("UPDATE convs SET full=NULL WHERE at<? AND full IS NOT NULL", (cut,))
                self.db.execute("UPDATE turns SET full=NULL WHERE at<? AND full IS NOT NULL", (cut,))
                # an unsettled row older than a day will never settle: settle it as it stands
                self.db.execute("UPDATE origin SET settled=1 WHERE settled=0 AND air_at<?", (now - 86400,))
            self.metrics["compacted"] += out["compacted"]
            with self.lock:
                first = self.db.execute("SELECT MIN(day) FROM origin").fetchone()[0]
                have = {r[0] for r in self.db.execute("SELECT day FROM reports")}
            today = day_of(now)
            if first:
                d = first
                for _ in range(400):
                    if d >= today:
                        break
                    if d not in have:
                        rep = self.report_day(d, now)
                        self.save_report(d, rep)
                        out["reports"] += 1
                    d = day_of(calendar.timegm(time.strptime(d, "%Y-%m-%d")) + 86400 + 3600)
            self.metrics["reports"] += out["reports"]
        except Exception as exc:  # noqa: BLE001
            self._err("housekeeping", exc)
        return out

    def save_report(self, day: str, rep: dict[str, Any]) -> None:
        body = json.dumps(rep, default=str)
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO reports VALUES(?,?,?)", (day, time.time(), body))
        try:
            self.reports_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.reports_dir / (day + ".json.tmp")
            tmp.write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
            tmp.replace(self.reports_dir / (day + ".json"))
        except OSError:
            pass

    def close(self) -> None:
        with self.lock:
            for c in (self._db, self._s3):
                try:
                    if c is not None:
                        c.close()
                except Exception:  # noqa: BLE001
                    pass
            self._db = self._s3 = None

    def counts(self) -> dict[str, Any]:
        with self.lock:
            n = self.db.execute("SELECT COUNT(*), SUM(full IS NOT NULL), MIN(air_at) FROM origin").fetchone()
        size = self.path.stat().st_size if self.path.exists() else 0
        return {"records": n[0], "full": n[1] or 0, "since": n[2], "bytes": size, **self.metrics}


def coverage_report(rows: Any, rogue: Any, forced: Any, since: float, until: float) -> dict[str, Any]:
    """% of air traced by road, forced vs rolled vs rogue, worst untraced sources."""
    roads: dict[str, dict[str, int]] = {}
    tot = {"items": 0, "rolled": 0, "forced": 0, "rogue": 0}
    for road, verdict, n in rows or []:
        r = roads.setdefault(str(road or "?"), {"items": 0, "rolled": 0, "forced": 0, "rogue": 0})
        v = verdict if verdict in ("rolled", "forced", "rogue") else "rogue"
        r[v] += int(n)
        r["items"] += int(n)
        tot[v] += int(n)
        tot["items"] += int(n)

    def pct(r: dict[str, int]) -> float:
        return round(100.0 * (r["rolled"] + r["forced"]) / r["items"], 2) if r["items"] else 100.0

    by_road = sorted(({"road": k, **v, "traced_pct": pct(v)} for k, v in roads.items()),
                     key=lambda x: (x["traced_pct"], -x["items"]))
    return {"schema": SCHEMA + "/coverage", "since": since, "until": until,
            "totals": dict(tot, traced_pct=pct(tot)), "roads": by_road,
            "worst_untraced": [{"producer": p or "unknown", "road": r, "why": w, "count": n}
                               for p, r, w, n in rogue or []],
            "forced": [{"road": r, "why": w, "count": n} for r, w, n in forced or []]}


# --- the station's install -----------------------------------------------------------

def install(app: Any, namespace: dict[str, Any]) -> OriginLedger | None:
    """Wire the ledger into the station: hooks in `namespace`, routes on `app`.
    Every hook is a no-op that never raises into an air path."""
    from fastapi import Header, HTTPException
    from fastapi.responses import HTMLResponse
    import asyncio

    data_path = namespace["data_path"]
    led = OriginLedger(data_path("system3_origin.sqlite3"), data_path("system3_origin_reports"),
                       data_path("system3.sqlite3"))
    radio = namespace.get("_RADIO")
    held = namespace.get("_S3_LINE_BY_ID")

    def peek(lid: str) -> Any:
        got = held.get(lid) if isinstance(held, dict) else None
        return dict(got) if isinstance(got, dict) else None

    def origin_keeper_tick(entries: list[dict[str, Any]]) -> dict[str, int]:
        try:
            ad_now = dict((radio or {}).get("ad_now") or {}) if isinstance(radio, dict) else {}
            gold_why = dict(namespace.get("_ORIGIN_GOLD_WHY") or {})
            picks = dict(namespace.get("_SFX_MATCH_PICKS") or {})
            return led.tick(entries, peek, {"ad_now": ad_now, "gold_why": gold_why, "match_picks": picks})
        except Exception as exc:  # noqa: BLE001
            led._err("keeper", exc)
            return {}

    def origin_housekeeping() -> dict[str, int]:
        return led.housekeeping()

    def origin_ledger_note(block, at, sid, round_kind, segment, rows) -> None:
        try:
            led.ledger_note(block, at, sid, round_kind, segment, rows)
        except Exception as exc:  # noqa: BLE001
            led._err("ledger note", exc)

    def origin_side_note(item: dict[str, Any]) -> None:
        try:
            led.side_note(item)
        except Exception as exc:  # noqa: BLE001
            led._err("side note", exc)

    namespace["origin_keeper_tick"] = origin_keeper_tick
    namespace["origin_housekeeping"] = origin_housekeeping
    namespace["origin_ledger_note"] = origin_ledger_note
    namespace["origin_side_note"] = origin_side_note
    namespace["origin_lookup"] = led.chain
    namespace["_ORIGIN_LEDGER"] = led
    auth = namespace["require_read_auth"]

    @app.get("/api/system3/origin/{line_id}")
    async def origin_api(line_id: str, full: int = 0, authorization: str | None = Header(default=None)):
        """[s3-account] One aired item's origin chain, any age: the air receipt,
        the script place, the System 3 conversation, turn and decisions, every
        table roll, the store it came from - or the named forced reason, or the
        rogue code path."""
        auth(authorization)
        got = await asyncio.to_thread(led.chain, str(line_id))
        if got is None:
            raise HTTPException(404, "the origin ledger holds no record of %s" % line_id)
        if full:
            rec = await asyncio.to_thread(led.get, str(line_id), True)
            got["full"] = (rec or {}).get("full")
            got["retention"] = (rec or {}).get("retention")
        return got

    @app.get("/api/system3/origin-of")
    async def origin_of_api(track: str = "", at: float = 0.0, event: str = "",
                            authorization: str | None = Header(default=None)):
        """[s3-account] A record or a live set has no line id: its origin by key -
        ?track=<track id>[&at=<when it spun>] or ?event=<MX Live event id>."""
        auth(authorization)
        got = await asyncio.to_thread(led.find_record, str(track)[:80], float(at or 0), str(event)[:40])
        if got is None:
            raise HTTPException(404, "the origin ledger holds no spin of that record")
        return got

    @app.get("/api/system3/untraced")
    async def untraced_api(since: float = 0.0, hours: float = 24.0, limit: int = 100,
                           authorization: str | None = Header(default=None)):
        """[s3-account] The Untraced alarm list: every item that aired with no
        System 3 origin, newest first, grouped by the code path that aired it."""
        auth(authorization)
        since = float(since or 0) or time.time() - max(0.1, min(24 * 30, float(hours or 24))) * 3600
        return await asyncio.to_thread(led.untraced, since, limit)

    @app.get("/api/system3/coverage")
    async def coverage_api(day: str = "", hours: float = 24.0, authorization: str | None = Header(default=None)):
        """[s3-account] The coverage report: % of air traced by road, forced vs
        rolled vs rogue, the worst untraced sources. `day` (YYYY-MM-DD) reads the
        kept daily report; otherwise the last `hours`, computed now."""
        auth(authorization)
        if day:
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
                raise HTTPException(400, "day is YYYY-MM-DD")
            got = await asyncio.to_thread(led.report, day)
            if got is None:
                got = await asyncio.to_thread(led.report_day, day)
                got["kept"] = False
            return got
        now = time.time()
        rep = await asyncio.to_thread(led.coverage, now - max(0.1, min(24 * 30, float(hours or 24))) * 3600, now)
        rep["days"] = await asyncio.to_thread(led.reports)
        rep["ledger"] = await asyncio.to_thread(led.counts)
        return rep

    @app.get("/system3-coverage", response_class=HTMLResponse)
    async def coverage_page():
        """[s3-account] The daily coverage page: the station's key rides in the
        page the way /journal's does (AUTOFILL_KEY), else ?key= or asked once."""
        key = str(namespace.get("SPARK_AGENT_API_KEY") or "") if namespace.get("AUTOFILL_KEY") else ""
        return HTMLResponse(COVERAGE_PAGE.replace("__SERVER_KEY__", json.dumps(key)),
                            headers={"Cache-Control": "no-store"})

    return led


COVERAGE_PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>System 3 coverage</title>
<style>
:root{--bg:#f6f5f2;--fg:#1d1d1b;--mute:#6b6a66;--line:#d9d6cf;--card:#fff;--ok:#2e7d4f;--forced:#8a6d1a;--rogue:#b3261e;}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--fg:#ecebe7;--mute:#9b9a95;--line:#34332f;--card:#1f1f1d;--ok:#6fc28f;--forced:#d9b24c;--rogue:#ef7b72;}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:980px;margin:0 auto;padding:16px}h1{font-size:20px;margin:4px 0 2px}.sub{color:var(--mute);margin:0 0 14px}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:0 0 12px}select,button{font:inherit;padding:6px 10px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--fg)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:0 0 16px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px}.tile b{display:block;font-size:22px}.tile span{color:var(--mute);font-size:12px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:8px;overflow:hidden;margin:0 0 16px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:12px;color:var(--mute);font-weight:600}
td.n{text-align:right;font-variant-numeric:tabular-nums}.bar{display:flex;height:8px;border-radius:4px;overflow:hidden;min-width:90px;background:var(--line)}
.bar i{display:block}.r{background:var(--ok)}.f{background:var(--forced)}.x{background:var(--rogue)}
.rogue{color:var(--rogue)}.forced{color:var(--forced)}.ok{color:var(--ok)}code{font-size:12px;word-break:break-all}
.wrap{overflow-x:auto}h2{font-size:15px;margin:18px 0 8px}
</style></head><body><main>
<h1>System 3 coverage</h1><p class="sub">Every aired item traced to a table roll, a named forced node, or flagged rogue.</p>
<div class="row"><select id="pick"><option value="">last 24 hours</option></select><button id="reload">Reload</button><span id="state" class="sub"></span></div>
<div class="tiles" id="tiles"></div>
<h2>By road</h2><div class="wrap"><table id="roads"><thead><tr><th>Road</th><th class="n">Items</th><th class="n">Rolled</th><th class="n">Forced</th><th class="n">Rogue</th><th class="n">Traced</th><th></th></tr></thead><tbody></tbody></table></div>
<h2>Worst untraced sources</h2><div class="wrap"><table id="worst"><thead><tr><th>Code path</th><th>Road</th><th>Why</th><th class="n">Count</th></tr></thead><tbody></tbody></table></div>
<h2>Forced nodes</h2><div class="wrap"><table id="forced"><thead><tr><th>Road</th><th>Reason</th><th class="n">Count</th></tr></thead><tbody></tbody></table></div>
</main><script>
(function(){
var SERVER_KEY=__SERVER_KEY__;
var q=new URLSearchParams(location.search),key=q.get("key")||SERVER_KEY||"";
try{if(key)sessionStorage.setItem("s3cov.k",key);else key=sessionStorage.getItem("s3cov.k")||"";}catch(e){}
function get(u){return fetch(u,{headers:key?{Authorization:"Bearer "+key}:{}}).then(function(r){
  if(r.status===401||r.status===403){var k=prompt("Station key");if(k){key=k;try{sessionStorage.setItem("s3cov.k",k)}catch(e){}return get(u)}}
  if(!r.ok)throw new Error(r.status+" "+r.statusText);return r.json();});}
function td(t,c){var e=document.createElement("td");if(c)e.className=c;e.textContent=t==null?"":String(t);return e;}
function tile(v,l,c){var d=document.createElement("div");d.className="tile";var b=document.createElement("b");if(c)b.className=c;b.textContent=v;var s=document.createElement("span");s.textContent=l;d.append(b,s);return d;}
function paint(rep){
  var t=rep.totals||{},tiles=document.getElementById("tiles");tiles.textContent="";
  tiles.append(tile((t.traced_pct==null?"-":t.traced_pct+"%"),"traced","ok"),tile(t.items||0,"aired items"),tile(t.rolled||0,"rolled","ok"),tile(t.forced||0,"forced","forced"),tile(t.rogue||0,"rogue","rogue"));
  var tb=document.querySelector("#roads tbody");tb.textContent="";
  (rep.roads||[]).forEach(function(r){var tr=document.createElement("tr");tr.append(td(r.road),td(r.items,"n"),td(r.rolled,"n ok"),td(r.forced,"n forced"),td(r.rogue,"n rogue"),td(r.traced_pct+"%","n"));
    var c=document.createElement("td"),bar=document.createElement("div");bar.className="bar";[["r",r.rolled],["f",r.forced],["x",r.rogue]].forEach(function(p){var i=document.createElement("i");i.className=p[0];i.style.width=(r.items?100*p[1]/r.items:0)+"%";bar.append(i)});c.append(bar);tr.append(c);tb.append(tr);});
  var wb=document.querySelector("#worst tbody");wb.textContent="";
  (rep.worst_untraced||[]).forEach(function(w){var tr=document.createElement("tr");var c=document.createElement("td");var k=document.createElement("code");k.textContent=w.producer;c.append(k);tr.append(c,td(w.road),td(w.why),td(w.count,"n rogue"));wb.append(tr);});
  if(!(rep.worst_untraced||[]).length){var tr=document.createElement("tr");var c=td("Nothing untraced in this window.");c.colSpan=4;tr.append(c);wb.append(tr);}
  var fb=document.querySelector("#forced tbody");fb.textContent="";
  (rep.forced||[]).forEach(function(f){var tr=document.createElement("tr");tr.append(td(f.road),td(f.why),td(f.count,"n forced"));fb.append(tr);});
}
function load(){var d=document.getElementById("pick").value;document.getElementById("state").textContent="loading";
  get("/api/system3/coverage"+(d?"?day="+encodeURIComponent(d):"")).then(function(rep){
    if(!d&&rep.days){var p=document.getElementById("pick");if(p.options.length<2)rep.days.forEach(function(x){var o=document.createElement("option");o.value=x.day;o.textContent=x.day+" ("+((x.totals||{}).traced_pct==null?"-":x.totals.traced_pct+"%")+")";p.append(o);});}
    paint(rep);document.getElementById("state").textContent=d?("report kept for "+d):"computed now";
  }).catch(function(e){document.getElementById("state").textContent="could not load: "+e.message;});}
document.getElementById("reload").onclick=load;document.getElementById("pick").onchange=load;load();
})();
</script></body></html>"""
