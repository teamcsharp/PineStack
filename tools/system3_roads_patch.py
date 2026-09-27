"""Every road on the station is System 3's: no wedges, no exceptions.

Operator, 2026-09-27: "Nothing is outside of system 3. It takes over
everything." "I don't want any wedges outside of dictating dialogue. It
needs to all be part of the RNG system with full accountability to its
origin. There aren't intended to be any exceptions to that."

What this patch does to app.py, all of it behind globals().get() guards so
a station with System 3 off, or failed, is the legacy station exactly:

  THE ROAD NAMES ITSELF     dj_banter(road=...) - recap, ad, news, manager,
                            memo, gallery, mixtape, open_show, fan_mail,
                            guest. System 3 plans each from its own legs
                            (system3_tables.DEFAULT_ROAD_STRUCTURES) and
                            records it as that road; the entry carries it.
  MEMOS ARE DIRECTED        the `whole` guard on the hook is gone: a memo
                            (whole=True) is planned from the memo legs.
  THE SFX GUY'S MOUTH       his node on every host turn (turn_dice.s3.sfxguy)
                            answers the two random() gates - the cadence's
                            take and speak_turns' quip - and sfxguy_line's
                            three random() calls take System 3's numbers
                            through a chooser that records the candidates.
  SINGLE-VOICE ROADS        record links (track_talk_write), station IDs
                            (prep_station_id, the live ID), the manager's
                            own page (dj_upstairs_write), stock interjections
                            (MANAGER_BREAK_LINES, COMPLAINT_LINES) and the
                            produced advert (ad_pick) go through
                            system3_direct_line: one-seat legs, ES rolled,
                            the running-order clause in the writer's prompt,
                            a LINE draw over the list where the station
                            called random.choice()/unrepeated(), and the
                            words bound to the node.
  THE ORIGIN ON THE LEDGER  dj_speak(system3=stamp) remembers the stamp by
                            line id; script_ledger_catch_up - the one hook
                            every unledgered line passes through - writes it
                            on the row, so /api/system3/line answers for a
                            station ID or a stock line exactly as for a turn.

Idempotent: --check exits 0 when every edit can apply, 2 when already
applied, 1 when an anchor is missing (naming it); --apply writes app.py
atomically, LF only. Run ON THE HOST (the share is slow).
"""
import os
import sys
import tempfile
from pathlib import Path

MARK = "[s3-roads]"

# (name, old, new, count) - `count` is how many times `old` must appear.
EDITS = [
    # ---- the road names itself -------------------------------------------------
    ("banter-sig",
     '                    exchange: dict[str, Any] | None = None,\n'
     '                    ) -> list[str]:\n',
     '                    exchange: dict[str, Any] | None = None,\n'
     '                    # [s3-roads] which road this round is: System 3 plans it\n'
     '                    # from that road\'s own structure and records it as such\n'
     '                    road: str = "",\n'
     '                    ) -> list[str]:\n', 1),
    ("memo-guard",
     '            if whole or not globals().get("system3_direct_banter"):\n'
     '                return None\n',
     '            if not globals().get("system3_direct_banter"):   # [s3-roads] memos too\n'
     '                return None\n', 1),
    ("direct-kwargs",
     '                    call_meta=(call_meta if isinstance(call_meta, dict) else {}))   # [s3-calls]\n',
     '                    call_meta=(call_meta if isinstance(call_meta, dict) else {}),   # [s3-calls]\n'
     # tools/system3_glass_patch.py: the length roll rides the same call
     '                    road=str(road or ""), whole=bool(whole),   # [s3-roads]\n'
     '                    lines_rolled=bool(_lines_rolled), lines_base=int(_lines_base),   # [s3-glass]\n'
     '                    lines_min=int(dj.get("banter_min_lines") or 4),\n'
     '                    lines_max=int(dj.get("banter_max_lines") or 22))\n', 1),
    ("entry-road",
     '        "whole": bool(whole),                  # #859\n',
     '        "whole": bool(whole),                  # #859\n'
     '        "road": str(road or ""),               # [s3-roads]\n', 1),
    ("site-recap",
     '            return await dj_banter(track, angle=angle, lines=6,\n'
     '                                   render_stream=bool(\n',
     '            return await dj_banter(track, road="recap", angle=angle, lines=6,\n'
     '                                   render_stream=bool(\n', 1),
    ("site-service-ad",
     '    _spot = await dj_banter(None, lines=4, angle=(\n'
     '        f"A SPONSOR SPOT for tonight\'s sponsor: {name.upper()}, one of "\n',
     '    _spot = await dj_banter(None, road="ad", lines=4, angle=(\n'
     '        f"A SPONSOR SPOT for tonight\'s sponsor: {name.upper()}, one of "\n', 1),
    ("site-engineering-ad",
     '    _spot = await dj_banter(None, lines=4, angle=(\n'
     '        "The STATION ENGINEERING REPORT as a sponsor spot ',
     '    _spot = await dj_banter(None, road="ad", lines=4, angle=(\n'
     '        "The STATION ENGINEERING REPORT as a sponsor spot ', 1),
    ("site-upstairs-page",
     '        await dj_banter(_RADIO.get("now"), lines=4, angle=(\n'
     '            "You have both just been made to listen to a page from the "\n',
     '        await dj_banter(_RADIO.get("now"), road="manager", lines=4, angle=(\n'
     '            "You have both just been made to listen to a page from the "\n', 1),
    ("site-gallery",
     '    lines = await dj_banter(None, angle=angle, lines=12,\n'
     '                            source=(seed or {}).get("file", ""),\n'
     '                            bank=bank_to is not None, bank_to=bank_to,\n',
     '    lines = await dj_banter(None, road="gallery", angle=angle, lines=12,\n'
     '                            source=(seed or {}).get("file", ""),\n'
     '                            bank=bank_to is not None, bank_to=bank_to,\n', 1),
    ("site-reanalysis",
     '    lines = await dj_banter(None, angle=angle, lines=8,\n'
     '                            source=(seed or {}).get("file", ""),\n'
     '                            own_material=True)\n',
     '    lines = await dj_banter(None, road="gallery", angle=angle, lines=8,\n'
     '                            source=(seed or {}).get("file", ""),\n'
     '                            own_material=True)\n', 1),
    ("site-hawk",
     '    lines = await dj_banter(None, angle=angle, lines=12,\n'
     '                            source=(seed or {}).get("file", ""),\n'
     '                            caller_name=_buyer,\n',
     '    lines = await dj_banter(None, road="gallery", angle=angle, lines=12,\n'
     '                            source=(seed or {}).get("file", ""),\n'
     '                            caller_name=_buyer,\n', 1),
    ("site-news",
     '        _said = await dj_banter(_RADIO.get("now"), angle=angle,\n'
     '                                lines=7 if hourly else 6,\n',
     '        _said = await dj_banter(_RADIO.get("now"), road="news", angle=angle,\n'
     '                                lines=7 if hourly else 6,\n', 1),
    ("site-mixtape-intro",
     '    lines = await dj_banter(None, lines=4, also_name=tape["title"], angle=(\n',
     '    lines = await dj_banter(None, road="mixtape", lines=4, also_name=tape["title"], angle=(\n', 1),
    ("site-mixtape-outro",
     '    lines = await dj_banter(None, lines=4, angle=(\n'
     '        "the MX tape has just finished. Come back on air glowing and talk "\n',
     '    lines = await dj_banter(None, road="mixtape", lines=4, angle=(\n'
     '        "the MX tape has just finished. Come back on air glowing and talk "\n', 1),
    ("site-open-show",
     '    return await dj_banter(None, lines=4, angle=(\n'
     '        f"you are opening the session. {show_open_when()} Welcome people to "\n',
     '    return await dj_banter(None, road="open_show", lines=4, angle=(\n'
     '        f"you are opening the session. {show_open_when()} Welcome people to "\n', 1),
    ("site-manager-rings",
     '        said = await dj_banter(\n'
     '            track, lines=turns, own_material=True,\n'
     '            caller_name=boss, caller_voice=voice,\n',
     '        said = await dj_banter(\n'
     '            track, road="manager", lines=turns, own_material=True,\n'
     '            caller_name=boss, caller_voice=voice,\n', 1),
    ("site-memo-hot",
     '        _hot_said = await dj_banter(track, lines=3, whole=True,   # #859\n',
     '        _hot_said = await dj_banter(track, road="memo", lines=3, whole=True,   # #859\n', 1),
    ("site-memo",
     '    _said = await dj_banter(track, lines=10, whole=True,          # #859\n',
     '    _said = await dj_banter(track, road="memo", lines=10, whole=True,   # #859\n', 1),
    ("site-manager-call",
     '    return await dj_banter(\n'
     '        _RADIO.get("now"), lines=4, source=doc, own_material=True,\n'
     '        caller_name=boss, caller_voice=voice,\n',
     '    return await dj_banter(\n'
     '        _RADIO.get("now"), road="manager", lines=4, source=doc, own_material=True,\n'
     '        caller_name=boss, caller_voice=voice,\n', 1),
    ("site-fan-mail",
     '    return await dj_banter(\n'
     '        _RADIO.get("now"), lines=5, source=doc, own_material=True,\n'
     '        angle=("A letter has arrived at the station addressed to the two of "\n',
     '    return await dj_banter(\n'
     '        _RADIO.get("now"), road="fan_mail", lines=5, source=doc, own_material=True,\n'
     '        angle=("A letter has arrived at the station addressed to the two of "\n', 1),
    ("site-guest",
     '            await dj_banter(_RADIO.get("now"), angle=angle,\n'
     '                            lines=random.randint(8, 13))\n',
     '            await dj_banter(_RADIO.get("now"), road="guest", angle=angle,\n'
     '                            lines=random.randint(8, 13))\n', 1),

    # ---- the SFX Guy's mouth ---------------------------------------------------
    ("guy-mouth",
     '                    _gq_rate = int(dj_settings().get("sfxguy_rate") or 0)\n'
     '                    if (not _keep_mic and _gq_rate\n'
     '                            and dj_settings().get("drop_voice")\n'
     '                            and item["who"] in ("dj", "cohost", "third")\n'
     '                            and random.random() < _gq_rate / 100.0):\n'
     '                        _gv = str(dj_settings()["drop_voice"])\n'
     '                        _qraw = sfxguy_line(\n'
     '                            _gv, spoken_text(item["chunk"])[:200])\n',
     '                    _gq_rate = int(dj_settings().get("sfxguy_rate") or 0)\n'
     '                    # [s3-roads] HIS NODE ON THIS TURN. Under System 3 the\n'
     "                    # round's plan says whether he pipes up here and what\n"
     "                    # kind of line; the number is System 3's, recorded on\n"
     '                    # the turn. None (not a System 3 round, or one planned\n'
     "                    # before he had a node) is the dial's own random.\n"
     '                    _gq_s3 = None\n'
     '                    if (not _keep_mic and _gq_rate and dj_settings().get("drop_voice")\n'
     '                            and item["who"] in ("dj", "cohost", "third")\n'
     '                            and globals().get("system3_sfxguy_direction")):\n'
     '                        _gq_s3 = globals()["system3_sfxguy_direction"](\n'
     '                            ready_meta, item["who"], spoken_text(item["chunk"]))\n'
     '                    if (not _keep_mic and _gq_rate\n'
     '                            and dj_settings().get("drop_voice")\n'
     '                            and item["who"] in ("dj", "cohost", "third")\n'
     '                            and (bool(_gq_s3.get("speak")) if _gq_s3 is not None\n'
     '                                 else not _s3_active() and random.random() < _gq_rate / 100.0)):\n'
     '                        _gv = str(dj_settings()["drop_voice"])\n'
     '                        _qraw = sfxguy_line(\n'
     '                            _gv, spoken_text(item["chunk"])[:200],\n'
     '                            director=(globals()["system3_sfxguy_chooser"](_gq_s3)\n'
     '                                      if _gq_s3 is not None\n'
     '                                      and globals().get("system3_sfxguy_chooser") else None))\n', 1),
    ("guy-cadence",
     '    if (sfx_due_after(completed, guy_interval) and settings.get("drop_voice")\n'
     '            and (ready_takes is not None\n'
     '                 or random.random() < float(settings.get("sfxguy_rate") or 0) / 100.0)):\n'
     '        _SFX_CADENCE_STATUS["guy_due"] += 1\n'
     '        take = sfxguy_ready_pick(text, str(settings["drop_voice"]))\n'
     '        if take:\n'
     '            additions.append({"path": str(VOICE_MEDIA_DIR / str(take["clip"]["path"]).rsplit("/", 1)[-1]),\n'
     '                              "who": "drop", "text": take["text"], "voice": take["voice"],\n'
     '                              "seconds": float(take["seconds"]), "sfxguy_reservation": take["id"]})\n',
     "    # [s3-roads] his node on this turn (see speak_turns): System 3's number\n"
     "    # in place of the dial's random; a banked round's takes keep their floor.\n"
     '    _s3_guy = (globals()["system3_sfxguy_direction"](meta, who, text)\n'
     '               if globals().get("system3_sfxguy_direction") and settings.get("drop_voice") else None)\n'
     '    _guy_wanted = (bool(_s3_guy and _s3_guy.get("speak")) if _s3_active()\n'
     '                   else ready_takes is not None or random.random() <\n'
     '                   float(settings.get("sfxguy_rate") or 0) / 100.0)\n'
     '    if (sfx_due_after(completed, guy_interval) and settings.get("drop_voice")\n'
     '            and _guy_wanted):\n'
     '        _SFX_CADENCE_STATUS["guy_due"] += 1\n'
     '        take = sfxguy_ready_pick(text, str(settings["drop_voice"]))\n'
     '        if take:\n'
     '            additions.append({"path": str(VOICE_MEDIA_DIR / str(take["clip"]["path"]).rsplit("/", 1)[-1]),\n'
     '                              "who": "drop", "text": take["text"], "voice": take["voice"],\n'
     '                              "seconds": float(take["seconds"]), "sfxguy_reservation": take["id"]})\n'
     '            if _s3_guy is not None and globals().get("system3_sfxguy_spoke"):\n'
     '                globals()["system3_sfxguy_spoke"](\n'
     '                    _s3_guy, take["text"], "bank",\n'
     '                    how="the speech bank\'s own context matcher chose the take; "\n'
     '                        "System 3 rolled whether he speaks")\n', 1),
    ("guy-take-sig",
     'def _sfxguy_take(context: str = "") -> str:\n',
     'def _sfxguy_take(context: str = "", director: Any = None) -> str:\n', 1),
    ("guy-take-pick",
     '    at = random.randrange(len(_SFXGUY_WARPED))\n'
     '    return str(_sfxguy_row(_SFXGUY_WARPED.pop(at)).get("text") or "")\n',
     '    # [s3-roads] System 3\'s number when the round is its own\n'
     '    at = (director.pick("reaction", [str(_sfxguy_row(r).get("text") or "") for r in _SFXGUY_WARPED])\n'
     '          if director is not None else random.randrange(len(_SFXGUY_WARPED)))\n'
     '    at = at if 0 <= at < len(_SFXGUY_WARPED) else 0\n'
     '    return str(_sfxguy_row(_SFXGUY_WARPED.pop(at)).get("text") or "")\n', 1),
    ("guy-line-sig",
     'def sfxguy_line(voice: str, context: str = "") -> str:\n',
     'def sfxguy_line(voice: str, context: str = "", director: Any = None) -> str:\n', 1),
    ("guy-line-news",
     '    line = ""\n'
     '    if (_SFXGUY_NEWS and random.random() < 0.15\n'
     '            and time.time() - _SFXGUY_NEWS_AT[0] > 600):\n'
     '        story = _SFXGUY_NEWS.pop(0)\n',
     '    line = ""\n'
     '    # [s3-roads] `director` is System 3\'s chooser for this line: the plan\'s\n'
     '    # kind order and its own recorded numbers stand in for the three\n'
     '    # random() calls here; None is the dial\'s own random, as ever.\n'
     '    _kind = "quip"\n'
     '    _news_ok = bool(_SFXGUY_NEWS) and time.time() - _SFXGUY_NEWS_AT[0] > 600\n'
     '    if (director.takes("news", _news_ok) if director is not None\n'
     '            else (_news_ok and random.random() < 0.15)):\n'
     '        story = _SFXGUY_NEWS.pop(0)\n', 1),
    ("guy-line-news-done",
     '        fire_and_forget(_sfxguy_news_fill())\n'
     '        return story["line"]\n'
     '    if _SFXGUY_WARPED and random.random() < warp / 100.0:\n'
     '        # [#1386] his reaction finally lands on the line it was written\n'
     '        # for, when there is one for this line.\n'
     '        line = _sfxguy_take(context)\n'
     '    else:\n',
     '        fire_and_forget(_sfxguy_news_fill())\n'
     '        if director is not None:\n'
     '            director.done(story["line"], "news")\n'
     '        return story["line"]\n'
     '    if (director.takes("reaction", bool(_SFXGUY_WARPED)) if director is not None\n'
     '            else (_SFXGUY_WARPED and random.random() < warp / 100.0)):\n'
     '        # [#1386] his reaction finally lands on the line it was written\n'
     '        # for, when there is one for this line.\n'
     '        line = _sfxguy_take(context, director)\n'
     '        _kind = "reaction"\n'
     '    else:\n', 1),
    ("guy-line-quip",
     '        line = (random.choice(pool) if pool else\n'
     '                min(rows, key=lambda r:\n'
     '                    float(said.get(_sfxguy_key(r)) or 0)))\n'
     '    _sfxguy_stamp(line)\n',
     '        if pool and director is not None:\n'
     '            _qi = director.pick("quip", pool)\n'
     '            line = pool[_qi if 0 <= _qi < len(pool) else 0]\n'
     '        else:\n'
     '            line = (random.choice(pool) if pool else\n'
     '                    min(rows, key=lambda r:\n'
     '                        float(said.get(_sfxguy_key(r)) or 0)))\n'
     '    _sfxguy_stamp(line)\n', 1),
    ("guy-line-done",
     '    if not _SFXGUY_NEWS:\n'
     '        fire_and_forget(_sfxguy_news_fill())\n'
     '    return line\n'
     '\n'
     '\n'
     '@app.get("/api/sfxguy/quips")\n',
     '    if not _SFXGUY_NEWS:\n'
     '        fire_and_forget(_sfxguy_news_fill())\n'
     '    if director is not None:\n'
     '        director.done(line, _kind)\n'
     '    return line\n'
     '\n'
     '\n'
     '@app.get("/api/sfxguy/quips")\n', 1),

    # ---- the origin of every single line ------------------------------------------
    ("speak-sig",
     '                   bound: dict[str, Any] | None = None,   # [#1237]\n'
     '                   bound_part: str = "") -> str:\n',
     '                   bound: dict[str, Any] | None = None,   # [#1237]\n'
     '                   system3: dict[str, Any] | None = None,  # [s3-roads] the line\'s node\n'
     '                   bound_part: str = "") -> str:\n', 2),
    ("speak-pass",
     '            sid=sid, bound=bound, bound_part=bound_part)   # [#1237]\n',
     '            sid=sid, bound=bound, bound_part=bound_part,   # [#1237]\n'
     '            system3=system3)   # [s3-roads]\n', 2),
    ("speak-mint",
     '    line_id = uuid.uuid4().hex  # durable cadence receipts must not recycle 24-bit IDs\n',
     '    line_id = uuid.uuid4().hex  # durable cadence receipts must not recycle 24-bit IDs\n'
     '    _s3_line_remember(line_id, system3)                      # [s3-roads]\n', 1),
    ("speak-helpers",
     'async def dj_speak(kind: str, track: dict[str, Any] | None = None,\n',
     '# --- [s3-roads] THE ORIGIN OF EVERY SINGLE LINE ------------------------------\n'
     '#\n'
     '# A line that never passes through a round - a station ID, a record link,\n'
     "# a stock interjection, a produced spot - is still System 3's: its road\n"
     '# asked system3_direct_line for its node and got a stamp back. dj_speak\n'
     '# remembers the stamp by the line id it mints, and script_ledger_catch_up -\n'
     '# "the one hook that catches all twenty-five ring append sites" - writes it\n'
     '# on the ledger row, so /api/system3/line answers for it like any turn.\n'
     '_S3_LINE_BY_ID: dict[str, dict[str, Any]] = {}\n'
     '\n'
     '\n'
     'def _s3_active() -> bool:\n'
     '    """Whether System 3 currently owns the station\'s dialogue decisions."""\n'
     '    runtime = globals().get("_system3")\n'
     '    try:\n'
     '        return bool(runtime and runtime().ready\n'
     '                    and runtime().settings.get("mode") == "active")\n'
     '    except Exception:  # noqa: BLE001\n'
     '        return False\n'
     '\n'
     '\n'
     'def _s3_line_remember(line_id: Any, stamp: Any) -> None:\n'
     '    if isinstance(stamp, dict) and stamp.get("conversation_id") and line_id:\n'
     '        _S3_LINE_BY_ID[str(line_id)] = dict(stamp)\n'
     '        while len(_S3_LINE_BY_ID) > 600:\n'
     '            _S3_LINE_BY_ID.pop(next(iter(_S3_LINE_BY_ID)))\n'
     '\n'
     '\n'
     'def _s3_line_stamp_of(row: Any) -> dict[str, Any] | None:\n'
     '    """The System 3 stamp for an aired ring row: the one it carries, else\n'
     '    the one dj_speak remembered for its id."""\n'
     '    got = row.get("system3") if isinstance(row, dict) else None\n'
     '    if isinstance(got, dict) and got.get("conversation_id"):\n'
     '        return dict(got)\n'
     '    return _S3_LINE_BY_ID.pop(str((row or {}).get("id") or ""), None)\n'
     '\n'
     '\n'
     'async def _s3_stock_line(road: str, options: Any, who: str = "dj", context: str = "",\n'
     '                         source: str = "") -> tuple[str, dict[str, Any] | None]:\n'
     '    """[s3-roads] A line off a fixed list is a LINE draw: System 3 rolls\n'
     '    over the list with every candidate recorded, and the words are bound\n'
     '    to the node. A failed draw withholds the line; it cannot choose off-ledger."""\n'
     '    rows = [str(x) for x in (options or []) if str(x or "").strip()]\n'
     '    if not rows:\n'
     '        return "", None\n'
     '    if globals().get("system3_direct_line"):\n'
     '        try:\n'
     '            _h = await globals()["system3_direct_line"](\n'
     '                road=road, who=who, dj=dj_settings(), context=context,\n'
     '                candidates=rows, candidates_from=source or road)\n'
     '            if _h is not None and _h.active and _h.line:\n'
     '                if globals().get("system3_bind_line"):\n'
     '                    globals()["system3_bind_line"](_h, _h.line)\n'
     '                return _h.line, dict(_h.stamp)\n'
     '        except Exception as _exc:  # noqa: BLE001\n'
     '            pipeline_log("system3", "a stock line was withheld after its draw failed",\n'
     '                         extra=("%s: %s" % (type(_exc).__name__, _exc))[:200])\n'
     '    return "", None\n'
     '\n'
     '\n'
     'async def _s3_ad_pick() -> dict[str, Any] | None:\n'
     '    """[s3-roads] ad_pick\'s rule - the reads that have run least - with the\n'
     "    draw among them System 3's, recorded with the book's candidates; the\n"
     '    row carries the stamp so the booth row and the ledger name the node."""\n'
     '    rows = [r for r in ad_list() if r.get("auto_air") is not False]\n'
     '    if not rows:\n'
     '        return None\n'
     '    fewest = min(r.get("uses", 0) for r in rows)\n'
     '    pool = [r for r in rows if r.get("uses", 0) == fewest]\n'
     '    if globals().get("system3_direct_line") and pool:\n'
     '        try:\n'
     '            _h = await globals()["system3_direct_line"](\n'
     '                road="ad_spot", who="dj", dj=dj_settings(), context="a produced spot",\n'
     '                candidates=[{"id": str(r.get("id") or i),\n'
     '                             "text": str(r.get("product") or r.get("text") or "a spot")[:200],\n'
     '                             "weight": 1.0} for i, r in enumerate(pool)],\n'
     '                candidates_from="the ad book, the reads that have run least")\n'
     '            if _h is not None and _h.active and _h.choice is not None and 0 <= _h.choice < len(pool):\n'
     '                _pick = dict(pool[_h.choice])\n'
     '                if globals().get("system3_bind_line"):\n'
     '                    globals()["system3_bind_line"](\n'
     '                        _h, str(_pick.get("text") or _pick.get("product") or ""))\n'
     '                _pick["system3"] = dict(_h.stamp)\n'
     '                return _pick\n'
     '        except Exception as _exc:  # noqa: BLE001\n'
     '            pipeline_log("system3", "a produced spot was withheld after its draw failed",\n'
     '                         extra=("%s: %s" % (type(_exc).__name__, _exc))[:200])\n'
     '    return None\n'
     '\n'
     '\n'
     'async def dj_speak(kind: str, track: dict[str, Any] | None = None,\n', 1),
    ("catchup-row",
     '              # [#1237] a single line published bound to a record keeps it\n'
     '              **({"bound": dict(one["bound"])}\n'
     '                 if isinstance(one.get("bound"), dict) else {})}\n'
     '             for one in group],\n',
     '              # [#1237] a single line published bound to a record keeps it\n'
     '              **({"bound": dict(one["bound"])}\n'
     '                 if isinstance(one.get("bound"), dict) else {}),\n'
     '              # [s3-roads] and its System 3 node, when it has one\n'
     '              **({"system3": _s3_line_stamp_of(one)}\n'
     '                 if _s3_line_stamp_of(one) else {})}\n'
     '             for one in group],\n', 1),
    ("round-row-extras",
     '                def _s3_row_of(_row_at: int) -> dict[str, Any]:\n'
     '                    # System 3 (docs/SYSTEM3_EVENT_SCHEMA.md): the\n'
     '                    # conversation this line belongs to and, for a spoken\n'
     '                    # turn, which of its turns - active or shadow.\n'
     '                    _s3m = (ready_meta.get("system3")\n',
     '                def _s3_row_of(_row_at: int) -> dict[str, Any]:\n'
     '                    # System 3 (docs/SYSTEM3_EVENT_SCHEMA.md): the\n'
     '                    # conversation this line belongs to and, for a spoken\n'
     '                    # turn, which of its turns - active or shadow.\n'
     '                    # [s3-roads] an addition with a node of its own (a\n'
     '                    # complaint line drawn by System 3) names that node.\n'
     '                    _own = ((_sfx_meta.get(_row_at) or {}).get("system3")\n'
     '                            if isinstance(_sfx_meta.get(_row_at), dict) else None)\n'
     '                    if isinstance(_own, dict) and _own.get("conversation_id"):\n'
     '                        return {"conversation_id": str(_own.get("conversation_id") or ""),\n'
     '                                "mode": str(_own.get("mode") or ""),\n'
     '                                "turn_id": str(_own.get("turn_id") or "")}\n'
     '                    _s3m = (ready_meta.get("system3")\n', 1),

    # ---- stock interjections -------------------------------------------------------
    ("manager-break-lines-a",
     '                "interject", _RADIO.get("now"),\n'
     '                line=random.choice(MANAGER_BREAK_LINES),\n',
     '                "interject", _RADIO.get("now"),\n'
     '                line=(_mb := await _s3_stock_line(\n'
     '                    "interject", MANAGER_BREAK_LINES, "dj",\n'
     '                    source="MANAGER_BREAK_LINES"))[0],   # [s3-roads]\n'
     '                system3=_mb[1],\n', 1),
    ("manager-break-lines-b",
     '                await dj_speak("interject", track,\n'
     '                               line=random.choice(MANAGER_BREAK_LINES),\n',
     '                await dj_speak("interject", track,\n'
     '                               line=(_mb := await _s3_stock_line(\n'
     '                                   "interject", MANAGER_BREAK_LINES, "dj",\n'
     '                                   source="MANAGER_BREAK_LINES"))[0],   # [s3-roads]\n'
     '                               system3=_mb[1],\n', 1),
    ("manager-break-lines-c",
     '        said = await dj_speak("interject", _RADIO.get("now"),\n'
     '                              line=random.choice(MANAGER_BREAK_LINES),\n',
     '        said = await dj_speak("interject", _RADIO.get("now"),\n'
     '                              line=(_mb := await _s3_stock_line(\n'
     '                                  "interject", MANAGER_BREAK_LINES, "dj",\n'
     '                                  source="MANAGER_BREAK_LINES"))[0],   # [s3-roads]\n'
     '                              system3=_mb[1],\n', 1),
    ("complaint-line",
     '                    phrase = random.choice(COMPLAINT_LINES)\n',
     '                    phrase, _s3_c = await _s3_stock_line(      # [s3-roads]\n'
     '                        "interject", COMPLAINT_LINES, other,\n'
     '                        context=sample.stem, source="COMPLAINT_LINES")\n', 1),
    ("complaint-row",
     '                                "who": other, "text": phrase, "voice": voice,\n'
     '                                "seconds": length, "sfx_reaction_for": sfx_id(sample)})\n',
     '                                "who": other, "text": phrase, "voice": voice,\n'
     '                                "seconds": length, "sfx_reaction_for": sfx_id(sample),\n'
     '                                **({"system3": _s3_c} if _s3_c else {})})   # [s3-roads]\n', 1),

    # ---- the produced advert ---------------------------------------------------------
    ("ad-pick",
     '    stored = ad_pick()\n',
     '    stored = await _s3_ad_pick()                              # [s3-roads]\n', 1),
    ("ad-booth-stamp",
     '    page_delivery = ""\n'
     '    box_played = False\n'
     '    box_dispatched = False\n'
     '    # --- broadcast admission (#1339) ---\n',
     '    if isinstance(entry.get("system3"), dict):               # [s3-roads]\n'
     '        booth_row["system3"] = dict(entry["system3"])\n'
     '    page_delivery = ""\n'
     '    box_played = False\n'
     '    box_dispatched = False\n'
     '    # --- broadcast admission (#1339) ---\n', 1),

    # ---- record links ----------------------------------------------------------------------
    ("track-talk-ask",
     '    answer = ""\n'
     '    try:\n'
     '        answer = prep_air_text(await ask_model(prompt, limit=620, spice=0.15),\n',
     '    # [s3-roads] the link is System 3\'s: one leg, the feeling rolled, the\n'
     '    # running-order clause in the prompt, the words bound to the node.\n'
     '    _s3l = None\n'
     '    if globals().get("system3_direct_line"):\n'
     '        try:\n'
     '            _s3l = await globals()["system3_direct_line"](\n'
     '                road="track_talk", who="dj" if part == "intro" else "cohost",\n'
     '                dj=dj_settings(), context=identity + " (" + str(part) + ")", bank=True)\n'
     '        except Exception:  # noqa: BLE001\n'
     '            _s3l = None\n'
     '    if _s3l is not None and _s3l.active and _s3l.sheet:\n'
     '        prompt += _s3l.sheet\n'
     '    answer = ""\n'
     '    try:\n'
     '        answer = prep_air_text(await ask_model(prompt, limit=620, spice=0.15),\n', 1),
    ("track-talk-bind",
     '    except Exception:  # noqa: BLE001\n'
     '        answer = ""\n'
     '    if track_talk_text_report(answer, track, part).get("ok"):\n'
     '        return answer\n',
     # tools/system3_glass_patch.py: the words the road RETURNS are bound
     '    except Exception:  # noqa: BLE001\n'
     '        answer = ""\n'
     '\n'
     '    def _s3_bound(_text: str) -> str:\n'
     '        # [s3-glass] the words the road RETURNS are the ones bound to the\n'
     '        # node - the fallback link included - never the raw answer alone\n'
     '        if _s3l is not None:\n'
     '            if globals().get("system3_bind_line"):\n'
     '                globals()["system3_bind_line"](_s3l, _text)\n'
     '            if isinstance(track, dict):\n'
     '                track["_s3_line_" + str(part)] = dict(_s3l.stamp)\n'
     '        return _text\n'
     '    if track_talk_text_report(answer, track, part).get("ok"):\n'
     '        return _s3_bound(answer)\n', 1),
    ("track-talk-side",
     '            text = await track_talk_write(track, part)\n',
     '            text = await track_talk_write(track, part)\n'
     '            if isinstance(track.get("_s3_line_" + str(part)), dict):   # [s3-roads]\n'
     '                side["system3"] = track.pop("_s3_line_" + str(part))\n', 1),
    ("track-talk-intro-air",
     '                           sid=record_talk_ride(track, "intro",\n'
     '                                                _ahead_intro),\n'
     '                           bound=record_bound_snapshot(track),   # [#1237]\n',
     '                           sid=record_talk_ride(track, "intro",\n'
     '                                                _ahead_intro),\n'
     '                           system3=_ahead_intro.get("system3"),   # [s3-roads]\n'
     '                           bound=record_bound_snapshot(track),   # [#1237]\n', 1),
    ("track-talk-outro-air",
     '                               sid=record_talk_ride(_gone, "outro",\n'
     '                                                    _back),\n',
     '                               sid=record_talk_ride(_gone, "outro",\n'
     '                                                    _back),\n'
     '                               system3=_back.get("system3"),   # [s3-roads]\n', 1),

    # ---- station IDs --------------------------------------------------------------------------
    ("unrepeated-sig",
     'def unrepeated(pool: list[str], key: str, keep: int = 8) -> str:\n',
     'def unrepeated(pool: list[str], key: str, keep: int = 8, director: Any = None) -> str:\n', 1),
    ("unrepeated-pick",
     '    pick = random.choice([p for p in pool if p not in recent] or pool)\n',
     '    # [s3-roads] a road that hands its System 3 line handle in gets the\n'
     '    # draw made with its recorded number; the ring is kept the same way.\n'
     '    _cands = [p for p in pool if p not in recent] or pool\n'
     '    if director is not None and hasattr(director, "pick"):\n'
     '        _at = director.pick(key, _cands)\n'
     '        pick = _cands[_at if 0 <= _at < len(_cands) else 0]\n'
     '    else:\n'
     '        pick = random.choice(_cands)\n', 1),
    ("liner-sig",
     'async def drop_liner(station: str) -> str:\n',
     'async def drop_liner(station: str, director: Any = None) -> str:\n', 1),
    ("liner-pick",
     '        line = unrepeated(pool, "drop_liner", keep=10)\n',
     '        line = unrepeated(pool, "drop_liner", keep=10, director=director)   # [s3-roads]\n', 1),
    ("liner-fallback",
     '    _plain = unrepeated([ln.format(station=station) for ln in naming],\n'
     '                        "drop_fallback", keep=3)\n',
     '    _plain = unrepeated([ln.format(station=station) for ln in naming],\n'
     '                        "drop_fallback", keep=3, director=director)   # [s3-roads]\n', 1),
    ("id-prep",
     '    station = str(dj.get("station_name") or "")\n'
     '    line = await drop_liner(station)\n'
     '    if not line:\n'
     '        return False\n',
     '    station = str(dj.get("station_name") or "")\n'
     '    # [s3-roads] the ID is System 3\'s: its node rolls how it is said and\n'
     '    # draws the liner off the stack with its own number; the shelf row\n'
     '    # carries the stamp to the air.\n'
     '    _s3l = None\n'
     '    if globals().get("system3_direct_line"):\n'
     '        try:\n'
     '            _s3l = await globals()["system3_direct_line"](\n'
     '                road="station_id", who="drop", dj=dj, context=station, bank=True)\n'
     '        except Exception:  # noqa: BLE001\n'
     '            _s3l = None\n'
     '    line = await drop_liner(station, director=_s3l if (_s3l is not None and _s3l.active) else None)\n'
     '    if not line:\n'
     '        return False\n', 1),
    ("id-prep-row",
     '    _row = {"text": text, "voice": drop_voice, "seconds": 0.0}\n',
     '    if _s3l is not None and globals().get("system3_bind_line"):   # [s3-roads]\n'
     '        globals()["system3_bind_line"](_s3l, text)\n'
     '    _row = {"text": text, "voice": drop_voice, "seconds": 0.0,\n'
     '            **({"system3": dict(_s3l.stamp)} if _s3l is not None else {})}\n', 1),
    ("id-air-shelf",
     '                    out = await dj_speak("station_id", None, line=str(_prep["text"]),\n'
     '                                         who="drop", voice=drop_voice, name="The SFX Guy")\n',
     '                    out = await dj_speak("station_id", None, line=str(_prep["text"]),\n'
     '                                         who="drop", voice=drop_voice, name="The SFX Guy",\n'
     '                                         system3=_prep.get("system3"))   # [s3-roads]\n', 1),
    ("id-air-live",
     '        if _prep_id and str(_prep_id.get("text") or ""):\n'
     '            line = str(_prep_id["text"])\n'
     '        else:\n'
     '            line = await drop_liner(station)\n'
     '            if station and station.lower() not in line.lower():\n'
     '                line = f"{line} {station}."\n'
     '        try:\n'
     '            await dj_speak("station_id", None, line=line, who="drop",\n',
     '        _s3_id = None\n'
     '        if _prep_id and str(_prep_id.get("text") or ""):\n'
     '            line = str(_prep_id["text"])\n'
     '            _s3_id = _prep_id.get("system3")\n'
     '        else:\n'
     '            # [s3-roads] a live ID is System 3\'s node too\n'
     '            _s3l = None\n'
     '            if globals().get("system3_direct_line"):\n'
     '                try:\n'
     '                    _s3l = await globals()["system3_direct_line"](\n'
     '                        road="station_id", who="drop", dj=dj_settings(), context=station)\n'
     '                except Exception:  # noqa: BLE001\n'
     '                    _s3l = None\n'
     '            line = await drop_liner(station, director=_s3l if (_s3l is not None and _s3l.active) else None)\n'
     '            if station and station.lower() not in line.lower():\n'
     '                line = f"{line} {station}."\n'
     '            if _s3l is not None:\n'
     '                if globals().get("system3_bind_line"):\n'
     '                    globals()["system3_bind_line"](_s3l, line)\n'
     '                _s3_id = dict(_s3l.stamp)\n'
     '        try:\n'
     '            await dj_speak("station_id", None, line=line, who="drop", system3=_s3_id,\n', 1),

    # ---- the manager's own page --------------------------------------------------------------
    ("upstairs-ask",
     '    try:\n'
     '        text = spoken_text(await ask_model(prompt, limit=700))\n'
     '    except Exception:\n'
     '        text = ""\n'
     '    if not text:\n'
     '        return {}\n',
     '    # [s3-roads] the page is System 3\'s: one leg in his voice, the feeling\n'
     '    # rolled and written into the prompt; the words bound to the node.\n'
     '    _s3l = None\n'
     '    if globals().get("system3_direct_line"):\n'
     '        try:\n'
     '            _s3l = await globals()["system3_direct_line"](\n'
     '                road="upstairs", who="manager", seat="C", dj=dj_settings(),\n'
     '                name=manager_call_name(), context=gripe)\n'
     '        except Exception:  # noqa: BLE001\n'
     '            _s3l = None\n'
     '    if _s3l is not None and _s3l.active and _s3l.sheet:\n'
     '        prompt += _s3l.sheet\n'
     '    try:\n'
     '        text = spoken_text(await ask_model(prompt, limit=700))\n'
     '    except Exception:\n'
     '        text = ""\n'
     '    if not text:\n'
     '        return {}\n', 1),
    ("upstairs-bind",
     '    text = await crystal_line(text, "the manager\'s own voice", 5)\n'
     '    row = upstairs_save(text, gripe, context)\n',
     '    text = await crystal_line(text, "the manager\'s own voice", 5)\n'
     '    row = upstairs_save(text, gripe, context)\n'
     '    if _s3l is not None and isinstance(row, dict) and row.get("id"):   # [s3-roads]\n'
     '        if globals().get("system3_bind_line"):\n'
     '            globals()["system3_bind_line"](_s3l, text)\n'
     '        try:\n'
     '            upstairs_update(str(row.get("id") or ""), system3=dict(_s3l.stamp))\n'
     '            row["system3"] = dict(_s3l.stamp)\n'
     '        except Exception:  # noqa: BLE001\n'
     '            pass\n', 1),
    ("upstairs-air",
     '        "page_id": str(made.get("id") or ""),\n'
     '        "aired": "box" if box_accepted else "published",\n'
     '    }\n',
     '        "page_id": str(made.get("id") or ""),\n'
     '        **({"system3": dict(made["system3"])}                 # [s3-roads]\n'
     '           if isinstance(made.get("system3"), dict) else {}),\n'
     '        "aired": "box" if box_accepted else "published",\n'
     '    }\n', 1),
]


def plan(text):
    """Every edit, in order. Kept as a function for the wiring test."""
    return list(EDITS)


def state_of(text, old, new, count):
    """'applied' when the replacement is in and the anchor survives only
    inside it (nine of these edits insert around their anchor - an anchor
    that outlives its edit must never be offered a second time); 'ready'
    when the anchor is there exactly `count` times and the replacement is
    not; otherwise the counts, for the operator."""
    n_new = text.count(new)
    n_old = text.count(old)
    if n_new >= 1 and n_old == new.count(old) * n_new:
        return "applied"
    if n_new == 0 and n_old == count:
        return "ready"
    return "anchor found %d times, wanted %d; replacement found %d times" % (n_old, count, n_new)


def check(text):
    """(applied, missing): how many edits are already in, and which anchors
    are absent or ambiguous (with the counts)."""
    applied = 0
    missing = []
    for name, old, new, count in plan(text):
        state = state_of(text, old, new, count)
        if state == "applied":
            applied += 1
        elif state != "ready":
            missing.append("%s (%s)" % (name, state))
    return applied, missing


def apply(path):
    path = Path(path)
    raw = path.read_bytes()
    text = raw.decode("utf-8").replace("\r\n", "\n")
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
