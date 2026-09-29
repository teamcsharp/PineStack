"""[s3-account] app.py half of total System 3 accountability: the origin ledger
(system3_origin.py) wired into the station, and the rogue roads found on the
live air closed at their source.

  THE LEDGER
  1. ring-class      _OriginRing: the booth ring stamps the appender's frames on
                     every row ("origin_path") - one hook for ~30 append sites -
                     and _origin_force(stamp, road, trigger, by) names a forced node
  2. ring-boot       the ring is an _OriginRing from the first row ...
  3. ring-stop       ... after clean_station_backlog ...
  4. ring-start      ... after dj_start ...
  5. ring-delete     ... and after a line is deleted from it
  6. keeper-tick     airlog_keeper hands the ring to origin_keeper_tick, in its thread
  7. housekeeping    the hourly compaction (7 days full -> compacted forever) and the
                     daily coverage report ride airlog_compact_all, in its thread
  8. ledger-note     script_ledger_commit tells the ledger each row's place and stamps
  9. install        system3_origin.install(app, globals()) after System 3's install
 10. screenplay-fallback  /api/screenplay/<hour>/line/<id>?origin=1 answers any aged
                     line from the origin ledger (default unchanged: 404 = not this hour)

  FORCED NODES AND SIDE ITEMS
 11. gold-why       the gap a gold run fills (its why) is kept for the bar's forced node
 12. (the in-round gold bar is named by its own run key, gold.in_round - no edit)
 13. record-on-air   a record on the deck is an item: its spin's roll or forced note
 14. police-note     the megaphone (never on the ring) is an operator forced item
 15. ack-note        the Pine Chat answer (never on the ring) is an operator forced item

  ROGUE ROADS CLOSED AT SOURCE (measured on the live air, 2026-09-28/29)
 16. continuity-rows the emergency pair's welded cadence clip kept its dice and folder,
                     and every row of the pair names the forced node + trigger
 17. continuity-s3   the clip and the SFX Guy inside the pair wear the pair's node
 18. cadence-folder  a cadence clip names its folder (sfx_dir) - 26 of 95 did not
 19. turns-folder    ... and keeps it on the coalesced road
 20. cycle-roll      the endless set's ring row carries the dice that chose its clip
                     and gets its own door node, like dj_sting's (GAP 10)
 21. sponsor-roll    the sponsor-spot listing carries the dice-door roll that chose it
 22. quip-store      the SFX Guy's quip draw names its shelf (db) and pool
 23. match-sting-filters / match-sting-note  the matcher's working per pick (the line it
                     matched and where from, candidates with scores and their words -
                     line / context / WordNet senses / folder - the floor, what each rule
                     removed) is kept by clip id for the clip's origin record
 25. match-video-roll the endless set's matched clip is System 3's draw among the tied
                     peers (it was the first in score order - no roll); its working kept
 26. wall-note       the endless set's own clip (never a ring row) is an aired item

--check exits 0 ready / 2 applied / 1 anchors missing; --apply is idempotent,
asserts every anchor, writes LF atomically.
TARGET: app.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

RING = '''# --- [s3-account] THE RING NAMES WHO APPENDED ----------------------------------
#
# Every aired item enters the booth ring (_RADIO["chat"]) at one of ~30 append
# sites. The origin ledger (system3_origin.py) must name the code path of an
# item that airs with no System 3 origin, so the ring itself stamps the
# appender's frames on the row ("origin_path", innermost first) - one hook
# instead of thirty edits, the census habit of _admission_producer.
def _origin_path(depth: int = 2, most: int = 5) -> str:
    try:
        import sys as _sys
        frame = _sys._getframe(depth)                 # noqa: SLF001
        names: list[str] = []
        while frame is not None and len(names) < most:
            names.append(frame.f_code.co_name)
            frame = frame.f_back
        return "<".join(names)
    except Exception:  # noqa: BLE001
        return ""


class _OriginRing(list):
    """The booth ring: a list that stamps who appended each row."""
    __slots__ = ()

    def append(self, row: Any) -> None:
        if isinstance(row, dict) and "origin_path" not in row:
            row["origin_path"] = _origin_path(2)
        super().append(row)

    def extend(self, rows: Any) -> None:
        rows = list(rows)
        path = _origin_path(2)
        for row in rows:
            if isinstance(row, dict) and "origin_path" not in row:
                row["origin_path"] = path
        super().extend(rows)

    def insert(self, index: Any, row: Any) -> None:
        if isinstance(row, dict) and "origin_path" not in row:
            row["origin_path"] = _origin_path(2)
        super().insert(index, row)


def _origin_force(stamp: Any, road: str, trigger: str, by: str = "") -> Any:
    """[s3-account] Name the forced node on a stamp (a gold bar, the reserve):
    the road and what triggered it - never dice."""
    if isinstance(stamp, dict):
        stamp.setdefault("forced", {"road": str(road), "trigger": str(trigger)[:300],
                                    "by": str(by or "")})
    return stamp


# [s3-account] the gap the current gold run fills (gold_fill_gap's why)
_ORIGIN_GOLD_WHY: dict[str, Any] = {"why": "", "at": 0.0}


def _origin_note(item: dict[str, Any]) -> None:
    """[s3-account] An aired item that never passes the ring, to the origin ledger."""
    note = globals().get("origin_side_note")
    if note:
        try:
            note(item)
        except Exception:  # noqa: BLE001
            pass


# [s3-account] THE MATCHER'S WORKING, KEPT PER PICK. The matcher kept only its
# last pick's counts in memory (_SFX_MATCH_LAST) and the line it matched in a
# ring of a dozen; a clip older than that could not say what it answered.
# Each pick is noted here by the clip's id - the line and where it came from,
# how many candidates, how many cleared the floor, how many each station rule
# removed, the scored candidates with the words that scored them (the spoken
# line, the round's context, WordNet's senses, the folder theme) - and the
# origin ledger puts it on the clip's record (compact forever: the line, the
# counts, the words; full for 7 days: the candidates with their scores).
_SFX_MATCH_PICKS: dict[str, dict[str, Any]] = {}


def _origin_match_note(path: Any, said: Any, cands: Any, tied: Any, eligible: Any,
                       road: str, why: str = "", score: Any = 0.0,
                       removed: Any = None) -> None:
    try:
        said = said if isinstance(said, dict) else {}
        ctx = str(said.get("context") or "")
        ctx_words = set(re.findall(r"[a-z']{3,}", ctx.lower()))
        top: list[dict[str, Any]] = []
        words: dict[str, list[str]] = {"line": [], "context": [], "senses": [], "folder": []}
        for cand in list(cands or [])[:10]:
            got = cand.as_dict()
            got["senses"] = [w for w in got.get("context") or [] if w.lower() not in ctx_words]
            got["context"] = [w for w in got.get("context") or [] if w.lower() in ctx_words]
            top.append(got)
        chosen = next((c for c in list(tied or []) + list(cands or [])
                       if _sfx_match is not None and _sfx_match.explain(c) == why), None)
        if chosen is not None:
            d = chosen.as_dict()
            words = {"line": list(d.get("line") or []),
                     "context": [w for w in d.get("context") or [] if w.lower() in ctx_words],
                     "senses": [w for w in d.get("context") or [] if w.lower() not in ctx_words],
                     "folder": list(d.get("folder_words") or [])}
        _SFX_MATCH_PICKS[sfx_id(Path(str(path)))] = {
            "at": time.time(), "road": str(road), "clip": Path(str(path)).stem[:120],
            "line": " ".join(str(said.get("line") or "").split())[:300],
            "line_source": str(said.get("source") or "the line it follows")[:80],
            "context": " ".join(ctx.split())[:300],
            "why": str(why or "")[:200], "score": round(float(score or 0), 2),
            "cands": len(list(cands or [])), "tied": len(list(tied or [])),
            "eligible": eligible, "removed": dict(removed or {}),
            "words": words, "candidates": top}
        while len(_SFX_MATCH_PICKS) > 64:
            _SFX_MATCH_PICKS.pop(next(iter(_SFX_MATCH_PICKS)))
    except Exception:  # noqa: BLE001
        pass


def _origin_wall_note(pick: Any, key: str, seconds: float, start: float, why: str = "") -> None:
    """[s3-account] The endless set's own clip (never a ring row) is an aired
    item too: its folder, its dice or its matched line, to the origin ledger."""
    try:
        item: dict[str, Any] = {
            "id": "wall:%s:%d" % (key, int(start)), "kind": "sfx", "who": "board",
            "text": Path(str(pick)).stem, "sfx": key, "sfx_dir": Path(str(pick)).parent.name or "sfx",
            "video": True, "endless": True, "aired": "published", "air_at": float(start),
            "seconds": round(float(seconds or 0), 2), "origin_path": "sfx_video_cycle",
            **({"match_why": str(why)[:240]} if why else {})}
        _sfx_roll_carry(item, Path(str(pick)))
        _origin_note(item)
    except Exception:  # noqa: BLE001
        pass


# --- Pine Box FM: the DJ ---------------------------------------------------
'''

EDITS = [
    ("ring-class",
     '# --- Pine Box FM: the DJ ---------------------------------------------------\n',
     RING,
     1),
    ("ring-boot",
     '    "history": [], "requests": [], "chat": [], "since_id": 0, "on": False,\n',
     '    "history": [], "requests": [], "chat": _OriginRing(), "since_id": 0, "on": False,   # [s3-account]\n',
     1),
    ("ring-stop",
     '    _RADIO["chat"] = []\n    _RADIO["last_said"] = {}\n',
     '    _RADIO["chat"] = _OriginRing()                                   # [s3-account]\n'
     '    _RADIO["last_said"] = {}\n',
     1),
    ("ring-start",
     '        "requests": [], "history": [], "chat": [],\n',
     '        "requests": [], "history": [], "chat": _OriginRing(),   # [s3-account]\n',
     1),
    ("ring-delete",
     '    _RADIO["chat"] = [e for e in _RADIO["chat"] if e.get("id") != mid]\n',
     '    _RADIO["chat"] = _OriginRing(e for e in _RADIO["chat"] if e.get("id") != mid)   # [s3-account]\n',
     1),
    ("keeper-tick",
     '            except Exception:  # noqa: BLE001\n'
     '                pass          # an unplaced line still airs\n',
     '            except Exception:  # noqa: BLE001\n'
     '                pass          # an unplaced line still airs\n'
     '            # [s3-account] ...and its ORIGIN, off the same ring, in a thread: the\n'
     '            # table roll, the named forced node, or the rogue code path\n'
     '            _otick = globals().get("origin_keeper_tick")\n'
     '            if _otick:\n'
     '                try:\n'
     '                    await asyncio.to_thread(_otick, list(_RADIO.get("chat") or []))\n'
     '                except Exception:  # noqa: BLE001\n'
     '                    pass      # an untraced line still airs\n',
     1),
    ("housekeeping",
     '    out["pause_log"] = airlog_jsonl_trim(PAUSE_LOG_PATH, 30 * 86400.0)\n    return out\n',
     '    out["pause_log"] = airlog_jsonl_trim(PAUSE_LOG_PATH, 30 * 86400.0)\n'
     '    # [s3-account] the origin ledger: 7 days full, then compacted forever; and\n'
     '    # every finished day\'s coverage report written and kept\n'
     '    _ohk = globals().get("origin_housekeeping")\n'
     '    if _ohk:\n'
     '        try:\n'
     '            out["origin"] = _ohk()\n'
     '        except Exception:  # noqa: BLE001\n'
     '            pass\n'
     '    return out\n',
     1),
    ("ledger-note",
     '    if globals().get("system3_observe_ledger"):\n'
     '        globals()["system3_observe_ledger"](block, sid, rows, round_kind)\n',
     '    # [s3-account] the origin ledger learns each row\'s place and stamps (dict work)\n'
     '    if globals().get("origin_ledger_note"):\n'
     '        globals()["origin_ledger_note"](block, at, sid, round_kind, _segment, rows)\n'
     '    if globals().get("system3_observe_ledger"):\n'
     '        globals()["system3_observe_ledger"](block, sid, rows, round_kind)\n',
     1),
    ("install",
     '    print("sfx vectors did not install: %s: %s" % (type(_sfxv_exc).__name__, _sfxv_exc))\n',
     '    print("sfx vectors did not install: %s: %s" % (type(_sfxv_exc).__name__, _sfxv_exc))\n'
     '# [s3-account] THE ORIGIN LEDGER (system3_origin.py): every aired item traced\n'
     '# to a table roll, a named forced node, or flagged rogue with its code path;\n'
     '# 7 days full, compacted forever; the Untraced list and the daily coverage.\n'
     'try:\n'
     '    import system3_origin as _system3_origin\n'
     '    _ORIGIN_RUNTIME = _system3_origin.install(app, globals())\n'
     'except Exception as _origin_exc:  # noqa: BLE001\n'
     '    _ORIGIN_RUNTIME = None\n'
     '    print("the origin ledger did not install: %s: %s" % (type(_origin_exc).__name__, _origin_exc))\n',
     1),
    ("screenplay-fallback",
     '    line_id: str,\n'
     '    authorization: str | None = Header(default=None),\n'
     ') -> dict[str, Any]:\n'
     '    """#1050: one line\'s provenance tree, off the cached hour."""\n'
     '    require_read_auth(authorization)\n'
     '    key, since, until = _screenplay_span(hour_key)\n'
     '    script = await screenplay_hour(since, until, key)\n'
     '    prov = (script.get("provenance") or {}).get(str(line_id))\n'
     '    if prov is None:\n'
     '        raise HTTPException(status_code=404,\n'
     '                            detail="No such line in that hour")\n'
     '    return {"line": str(line_id), "hour_key": key, "provenance": prov}\n',
     '    line_id: str,\n'
     '    authorization: str | None = Header(default=None),\n'
     '    origin: int = 0,\n'
     ') -> dict[str, Any]:\n'
     '    """#1050: one line\'s provenance tree, off the cached hour.\n'
     '    [s3-account] ?origin=1: a line the hour\'s tree does not hold (it keeps the\n'
     '    current and previous hour) answers from the origin ledger, any age -\n'
     '    asked for, never by default: a 404 still means "not in this hour"."""\n'
     '    require_read_auth(authorization)\n'
     '    key, since, until = _screenplay_span(hour_key)\n'
     '    script = await screenplay_hour(since, until, key)\n'
     '    prov = (script.get("provenance") or {}).get(str(line_id))\n'
     '    if prov is None:\n'
     '        _olook = globals().get("origin_lookup") if origin else None\n'
     '        _orig = (await asyncio.to_thread(_olook, str(line_id))) if _olook else None\n'
     '        if _orig:\n'
     '            return {"line": str(line_id), "hour_key": key,\n'
     '                    "provenance": {"origin": _orig, "from": "the origin ledger"}}\n'
     '        raise HTTPException(status_code=404,\n'
     '                            detail="No such line in that hour")\n'
     '    return {"line": str(line_id), "hour_key": key, "provenance": prov}\n',
     1),
    ("gold-why",
     '    want = float(ahead) if ahead else GOLD_RUN_AHEAD\n',
     '    want = float(ahead) if ahead else GOLD_RUN_AHEAD\n'
     '    # [s3-account] the gap this run fills: the gold bar\'s forced node names it\n'
     '    _ORIGIN_GOLD_WHY.update(why=str(why or "dead air")[:200], at=time.time())\n',
     1),
    ("record-on-air",
     '    """The audio is starting: this is the moment the track is on air, and the\n'
     '    moment `elapsed` starts counting from."""\n'
     '    previous = _RADIO.get("now")\n',
     '    """The audio is starting: this is the moment the track is on air, and the\n'
     '    moment `elapsed` starts counting from."""\n'
     '    # [s3-account] the record on the deck is an aired item: the spin\'s roll, or\n'
     '    # its honest forced note (MX Live, a FIFO request), to the origin ledger\n'
     '    # (the origin key: rec:<track id>:<spin at>, or live:<event id>:<track id>:<at>)\n'
     '    try:\n'
     '        _spin = track.get("s3_spin") if isinstance(track.get("s3_spin"), dict) else {}\n'
     '        _t_at = int(float(_spin.get("at") or time.time()))\n'
     '        _ev = ""\n'
     '        if track.get("pinelive"):\n'
     '            try:\n'
     '                _ev = str(pinelive.PL.event_id() or "")[:40]\n'
     '            except Exception:  # noqa: BLE001\n'
     '                _ev = ""\n'
     '        _origin_note({"id": (("live:%s:" % _ev) if track.get("pinelive") else "rec:")\n'
     '                      + "%s:%d" % (str(track.get("id") or "")[:40], _t_at),\n'
     '                      "kind": "record", "who": "deck", "aired": "published",\n'
     '                      "air_at": time.time(), "track_id": str(track.get("id") or "")[:80],\n'
     '                      **({"event_id": _ev} if _ev else {}),\n'
     '                      "text": " - ".join(str(track.get(k) or "") for k in ("title", "artist")\n'
     '                                         if track.get(k))[:200],\n'
     '                      "s3_spin": (dict(track["s3_spin"]) if isinstance(track.get("s3_spin"), dict)\n'
     '                                  else None),\n'
     '                      "origin_path": "dj_on_air"})\n'
     '    except Exception:  # noqa: BLE001\n'
     '        pass\n'
     '    previous = _RADIO.get("now")\n',
     1),
    ("police-note",
     '    await _episode_stage(f"{play[\'path\']}?t={play[\'sig\']}", label)\n'
     '    pipeline_log("air", f"megaphone outside',
     '    await _episode_stage(f"{play[\'path\']}?t={play[\'sig\']}", label)\n'
     '    _origin_note({"id": "pol:" + uuid.uuid4().hex[:16], "kind": "megaphone",   # [s3-account]\n'
     '                  "who": "outside", "aired": "published", "air_at": time.time(),\n'
     '                  "text": label + ": " + str(text)[:300], "media": str(play.get("path") or ""),\n'
     '                  "s3_roll": _s3_spin_roll("police.character", 300.0) or None,\n'
     '                  "origin_path": "dj_police_outside",\n'
     '                  "origin_forced": {"road": "operator", "by": "dj_police_outside",\n'
     '                                    "trigger": "the operator sent the officer outside (the megaphone)"}})\n'
     '    pipeline_log("air", f"megaphone outside',
     1),
    ("ack-note",
     '            played = await _play_on_box(clip["path"], clip["sig"], reply=True)\n'
     '            if not played:\n'
     '                box_hold(clip, line, "host")\n'
     '        return\n',
     '            played = await _play_on_box(clip["path"], clip["sig"], reply=True)\n'
     '            if not played:\n'
     '                box_hold(clip, line, "host")\n'
     '        _origin_note({"id": "ack:" + uuid.uuid4().hex[:16], "kind": "ack",   # [s3-account]\n'
     '                      "who": "box", "aired": "published", "air_at": time.time(),\n'
     '                      "text": str(line)[:300], "media": str(clip.get("path") or ""),\n'
     '                      "origin_path": "pine_speak_ack",\n'
     '                      "origin_forced": {"road": "operator", "by": "pine_speak_ack",\n'
     '                                        "trigger": "the station answering the operator\'s Pine Chat request"}})\n'
     '        return\n',
     1),
    ("continuity-rows",
     '                **{key: pick[key] for key in ("sfx_sample_id", "sfxguy_reservation") if key in pick},\n'
     '                "emergency_reason": str(reason)[:300], "from": offset, "until": offset + seconds,\n',
     '                **{key: pick[key] for key in ("sfx_sample_id", "sfxguy_reservation",\n'
     '                                              # [s3-account] the welded clip keeps its dice and folder\n'
     '                                              "sfx_roll", "poster", "sfx_dir", "sfx_video_id")\n'
     '                   if key in pick},\n'
     '                # [s3-account] a never-quiet filler: every row names its forced node\n'
     '                "origin_forced": {"road": "emergency_host", "by": "continuity_air",\n'
     '                                  "trigger": "never-quiet: " + (str(reason or "")[:240]\n'
     '                                                                or "the reserve covered a silence")},\n'
     '                "emergency_reason": str(reason)[:300], "from": offset, "until": offset + seconds,\n',
     1),
    ("continuity-s3",
     '        _CONTINUITY_STATE.update(last_air=time.time(), why=reason or "Emergency host continuity")\n'
     '        to_box = (_RADIO.get("voice_to") or "box") in ("box", "both") and box_talk_ok()\n',
     '        _CONTINUITY_STATE.update(last_air=time.time(), why=reason or "Emergency host continuity")\n'
     '        # [s3-account] the clip / the SFX Guy welded inside the pair wear the pair\'s\n'
     '        # node (not its replay stamp), with the clip\'s own dice (the rows are the\n'
     '        # ring\'s own dicts; nothing has awaited since they went on)\n'
     '        if _cont_s3 and _cont_s3.get("conversation_id"):\n'
     '            for _cont_row in rows:\n'
     '                if _cont_row.get("who") not in ("dj", "cohost") and not _cont_row.get("system3"):\n'
     '                    _cont_row["system3"] = {\n'
     '                        "conversation_id": _cont_s3["conversation_id"],\n'
     '                        "turn_id": str(_cont_s3.get("turn_id") or ""),\n'
     '                        "mode": _cont_s3.get("mode") or "active",\n'
     '                        **({"sfx_roll": dict(_cont_row["sfx_roll"])}\n'
     '                           if isinstance(_cont_row.get("sfx_roll"), dict) else {})}\n'
     '        to_box = (_RADIO.get("voice_to") or "box") in ("box", "both") and box_talk_ok()\n',
     1),
    ("cadence-folder",
     '            additions.append({"path": str(sample), "who": "board", "text": "\U0001f50a " + sample.stem,\n'
     '                              "seconds": duration, "sfx_sample_id": sfx_id(sample)})\n',
     '            additions.append({"path": str(sample), "who": "board", "text": "\U0001f50a " + sample.stem,\n'
     '                              "seconds": duration, "sfx_sample_id": sfx_id(sample),\n'
     '                              "sfx_dir": sample.parent.name or "sfx"})   # [s3-account] its folder\n',
     1),
    ("turns-folder",
     '                                     if k in ("voice", "sfx_sample_id", "sfxguy_reservation",\n'
     '                                              "sfx_video_id", "sfx_video_seconds",\n'
     '                                              "sfx_match_why", "sfx_reaction_for")}\n',
     '                                     if k in ("voice", "sfx_sample_id", "sfxguy_reservation",\n'
     '                                              "sfx_video_id", "sfx_video_seconds",\n'
     '                                              "sfx_match_why", "sfx_reaction_for",\n'
     '                                              "sfx_dir")}          # [s3-account] its folder\n',
     1),
    ("cycle-roll",
     '        "url": "/sfx/%s?t=%s" % (key, media_sign(key)), "aired": "airing",\n'
     '        **({"match_why": str(why)[:240]} if why else {}),   # [#1251]\n'
     '        "endless": True})                          # #1417: rung by the cycle, after the tube\'s clip\n'
     '    del _RADIO["chat"][:-RADIO_CHAT_KEEP]\n',
     '        "url": "/sfx/%s?t=%s" % (key, media_sign(key)), "aired": "airing",\n'
     '        **({"match_why": str(why)[:240]} if why else {}),   # [#1251]\n'
     '        "endless": True})                          # #1417: rung by the cycle, after the tube\'s clip\n'
     '    # [s3-account] the set\'s row carries the dice that chose its clip (dj_sting\n'
     '    # rolled it before handing it to the cycle) and gets its own door node\n'
     '    try:\n'
     '        _cyc_row = _RADIO["chat"][-1]\n'
     '        _sfx_roll_carry(_cyc_row, sample)\n'
     '        asyncio.get_running_loop()       # a door node only where the loop is\n'
     '        fire_and_forget(_s3_loose_board_stamp(_cyc_row, sample))\n'
     '    except Exception:  # noqa: BLE001\n'
     '        pass\n'
     '    del _RADIO["chat"][:-RADIO_CHAT_KEEP]\n',
     1),
    ("sponsor-roll",
     '    if _spot:\n'
     '        ad_booth_row("\\U0001f4e3 sponsor spot \\u2014 " + name.upper(),\n'
     '                     product=name, air_at=_spot_at)\n',
     '    if _spot:\n'
     '        _sp_row = ad_booth_row("\\U0001f4e3 sponsor spot \\u2014 " + name.upper(),\n'
     '                               product=name, air_at=_spot_at)\n'
     '        # [s3-account] the listing carries the dice-door roll that chose the sponsor\n'
     '        if isinstance(_sp_row, dict) and _sponsor_roll:\n'
     '            _sp_row["s3_roll"] = _sponsor_roll\n',
     1),
    ("sponsor-pick",
     '    name = s3_unrepeated("ad.sponsor_service", list(SPONSOR_SERVICES), "sponsor-service", '
     '"which of the box\'s own services is tonight\'s sponsor spot")   # [s3-dice-door]\n',
     '    name = s3_unrepeated("ad.sponsor_service", list(SPONSOR_SERVICES), "sponsor-service", '
     '"which of the box\'s own services is tonight\'s sponsor spot")   # [s3-dice-door]\n'
     '    _sponsor_roll = _s3_spin_roll("ad.sponsor_service")            # [s3-account]\n',
     1),
    ("quip-store",
     '    _sfxguy_stamp(line)\n'
     '    if len(_SFXGUY_WARPED) < 8:\n',
     '    _sfxguy_stamp(line)\n'
     '    if _kind == "quip":\n'
     '        # [s3-account] the quip draw names the store it came from: the shelf file\n'
     '        try:\n'
     '            _qd = getattr(director, "draws", None)\n'
     '            if isinstance(_qd, list) and _qd and isinstance(_qd[-1], dict):\n'
     '                _qd[-1].setdefault("store", {\n'
     '                    "kind": "sfx guy quip shelf",\n'
     '                    "db": "%s/%s.json" % (SFXGUY_QUIPS_DIR.name, _sfxguy_voice(voice)),\n'
     '                    "pool": "quips not said inside the hour", "shelf": len(rows)})\n'
     '        except Exception:  # noqa: BLE001\n'
     '            pass\n'
     '    if len(_SFXGUY_WARPED) < 8:\n',
     1),
    ("match-sting-filters",
     '    for path, _seconds, cand in sfx_match_rows(tied):\n'
     '        if allowed_paths is not None and str(path) not in allowed_paths:\n'
     '            continue\n'
     '        key = sfx_id(path)\n'
     '        if key in banned:\n'
     '            continue\n'
     '        if float(weights.get(key, 1.0) or 0) <= 0.05:\n'
     '            continue                          # marked all the way down (#645)\n'
     '        # A lone exact lexical hit must not defeat the station\'s rotation.\n'
     '        # If it was just heard, let the ordinary draw reach the deep book.\n'
     '        if sting_recent(str(path)):\n'
     '            continue\n'
     '        if sfx_is_video(path) and sfx_video_on_cooldown(key):\n'
     '            continue\n'
     '        survivors.append(str(path))\n',
     '    # [s3-account] how many each of the station\'s rules removed, for the clip\'s origin\n'
     '    _removed = {"the picture share": 0, "banned": 0, "weighted out (#645)": 0,\n'
     '                "just heard": 0, "video cooldown": 0}\n'
     '    for path, _seconds, cand in sfx_match_rows(tied):\n'
     '        if allowed_paths is not None and str(path) not in allowed_paths:\n'
     '            _removed["the picture share"] += 1\n'
     '            continue\n'
     '        key = sfx_id(path)\n'
     '        if key in banned:\n'
     '            _removed["banned"] += 1\n'
     '            continue\n'
     '        if float(weights.get(key, 1.0) or 0) <= 0.05:\n'
     '            _removed["weighted out (#645)"] += 1\n'
     '            continue                          # marked all the way down (#645)\n'
     '        # A lone exact lexical hit must not defeat the station\'s rotation.\n'
     '        # If it was just heard, let the ordinary draw reach the deep book.\n'
     '        if sting_recent(str(path)):\n'
     '            _removed["just heard"] += 1\n'
     '            continue\n'
     '        if sfx_is_video(path) and sfx_video_on_cooldown(key):\n'
     '            _removed["video cooldown"] += 1\n'
     '            continue\n'
     '        survivors.append(str(path))\n',
     1),
    ("match-sting-note",
     '    _SFX_MATCH_LAST.update({"path": got, "why": why, "score": score,\n'
     '                            "at": time.time(), "cands": len(cands),\n'
     '                            "tied": len(tied), "eligible": len(survivors)})\n',
     '    _SFX_MATCH_LAST.update({"path": got, "why": why, "score": score,\n'
     '                            "at": time.time(), "cands": len(cands),\n'
     '                            "tied": len(tied), "eligible": len(survivors)})\n'
     '    _origin_match_note(got, said, cands, tied, len(survivors), "sting", why, score,   # [s3-account]\n'
     '                       _removed)\n',
     1),
    ("match-video-roll",
     '    pin = sfx_pin_prefix()\n'
     '    banned = sfx_bans()\n'
     '    for path, seconds, cand in sfx_match_rows(tied):\n'
     '        if pin and not str(path).startswith(pin):\n'
     '            continue\n'
     '        key = sfx_id(path)\n'
     '        if key in banned:\n'
     '            continue\n'
     '        if sfx_video_folder_recent(path.parent.name):\n'
     '            continue                           # #1450: vary the source shelf\n'
     '        if sfx_video_on_cooldown(key):          # #1450: this deck still holds\n'
     '            continue\n'
     '        why = _sfx_match.explain(cand)\n'
     '        _SFX_MATCH["picks"] = int(_SFX_MATCH.get("picks") or 0) + 1\n'
     '        _SFX_MATCH["matched"] = int(_SFX_MATCH.get("matched") or 0) + 1\n'
     '        sfx_match_note("endless", path.stem, why, cand.score, said["line"])\n'
     '        return (path, float(seconds or 0), why, round(float(cand.score), 2))\n',
     '    pin = sfx_pin_prefix()\n'
     '    banned = sfx_bans()\n'
     '    # [s3-account] every eligible peer, then System 3 draws which one the set rings:\n'
     '    # the score chose the peers, never the clip (it was the first in score order,\n'
     '    # a pick no roll made - the same rule the sting road already follows)\n'
     '    _removed = {"pinned folder": 0, "banned": 0, "folder just shown (#1450)": 0,\n'
     '                "on cooldown (#1450)": 0}\n'
     '    _eligible: list[tuple] = []\n'
     '    for path, seconds, cand in sfx_match_rows(tied):\n'
     '        if pin and not str(path).startswith(pin):\n'
     '            _removed["pinned folder"] += 1\n'
     '            continue\n'
     '        key = sfx_id(path)\n'
     '        if key in banned:\n'
     '            _removed["banned"] += 1\n'
     '            continue\n'
     '        if sfx_video_folder_recent(path.parent.name):\n'
     '            _removed["folder just shown (#1450)"] += 1\n'
     '            continue                           # #1450: vary the source shelf\n'
     '        if sfx_video_on_cooldown(key):          # #1450: this deck still holds\n'
     '            _removed["on cooldown (#1450)"] += 1\n'
     '            continue\n'
     '        _eligible.append((path, seconds, cand))\n'
     '    if _eligible:\n'
     '        _at = _S3ClipDice("sfx.match_video", "which of the clips matched to the line the endless "\n'
     '                          "set rings (the tied peers over the floor)").pick(\n'
     '            "sfx.match_video", [str(e[0]) for e in _eligible])\n'
     '        path, seconds, cand = _eligible[_at if 0 <= _at < len(_eligible) else 0]\n'
     '        why = _sfx_match.explain(cand)\n'
     '        _sfx_roll_note(path, "match", {"label": path.parent.name, "dice": None, "of": None,\n'
     '                                       "by": "the matcher\'s score (#1251)"},\n'
     '                       _s3_sfx_rolled("sfx.match_video", path.stem), 1)\n'
     '        _origin_match_note(path, said, cands, tied, len(_eligible), "endless", why,\n'
     '                           cand.score, _removed)\n'
     '        _SFX_MATCH["picks"] = int(_SFX_MATCH.get("picks") or 0) + 1\n'
     '        _SFX_MATCH["matched"] = int(_SFX_MATCH.get("matched") or 0) + 1\n'
     '        sfx_match_note("endless", path.stem, why, cand.score, said["line"])\n'
     '        return (path, float(seconds or 0), why, round(float(cand.score), 2))\n',
     1),
    ("wall-note",
     '            sfx_video_note_played(key, pick.parent.name)\n'
     '            if asked_who:\n'
     '                _sfx_cycle_note(pick, seconds, start, asked_who,\n',
     '            sfx_video_note_played(key, pick.parent.name)\n'
     '            if not asked_who:          # [s3-account] the set\'s own clip is an aired item\n'
     '                _origin_wall_note(pick, key, seconds, start, _match_why)\n'
     '            if asked_who:\n'
     '                _sfx_cycle_note(pick, seconds, start, asked_who,\n',
     1),
]


def plan(text):
    return list(EDITS)


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


def apply(path):
    path = Path(path)
    text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
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
    assert "\r" not in text
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    with os.fdopen(fd, "wb") as fh:
        fh.write(text.encode("utf-8"))
    try:
        shutil.copymode(str(path), tmp)
    except OSError:
        pass
    os.replace(tmp, path)
    return 0


def main(argv):
    do_apply = "--apply" in argv
    target = next((a for a in argv if not a.startswith("--")), "app.py")
    if do_apply:
        code = apply(target)
        print({0: "APPLIED", 1: "ANCHORS MISSING - nothing written", 2: "already applied"}[code])
        return code
    text = Path(target).read_bytes().decode("utf-8").replace("\r\n", "\n")
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
