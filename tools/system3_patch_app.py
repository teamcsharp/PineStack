"""Wire System 3 into app.py. --check exits 0 ready / 2 applied / 1 anchors
missing; --apply is idempotent, asserts every anchor, writes LF atomically.

TARGET: app.py

Run from the repository root: python tools/system3_patch_app.py --check app.py
"""
import os
import sys

MARK = "system3_direct_banter"

EDITS = [
    # 1. Install beside System 2.
    ("install",
     "_SYSTEM2_RUNTIME = install_system2(app, globals())\n",
     "_SYSTEM2_RUNTIME = install_system2(app, globals())\n"
     "# System 3 (docs/system3_blueprint.md): the conversation director. Every\n"
     "# hook it exports is reached through globals().get(), so an install that\n"
     "# fails leaves the legacy station exactly as it was.\n"
     "try:\n"
     "    from system3_runtime import install as install_system3\n"
     "    _SYSTEM3_RUNTIME = install_system3(app, globals())\n"
     "except Exception as _system3_exc:  # noqa: BLE001\n"
     "    _SYSTEM3_RUNTIME = None\n"
     "    print(\"system3 did not install: %s: %s\" % (type(_system3_exc).__name__, _system3_exc))\n"),
    # 2. The handle exists on every path through dj_banter.
    ("handle",
     "    _system2_sources: list[dict[str, Any]] = []\n\n    def _source_for_scene(row):\n",
     "    _system2_sources: list[dict[str, Any]] = []\n"
     "    _s3 = None      # System 3's handle for this round (see _s3_direct)\n\n"
     "    def _source_for_scene(row):\n"),
    # 3. Plan the round before the legacy topic draw; the draw stands down
    #    while System 3 owns the running order.
    ("direct",
     "        _topic_at, _topic_new = 0, {}\n        try:\n            if (banter_dice_on() > 0 and int(lines or 0) >= 8\n",
     '        async def _s3_direct(call_sheet: str = ""):\n'
     '            # System 3 (docs/system3_blueprint.md) plans the round. ACTIVE:\n'
     "            # its running order replaces #1386's and its door rolls replace\n"
     '            # random(). SHADOW: it records what it would have done. None\n'
     '            # (off, or it failed) is this road exactly as it was.\n'
     '            if not globals().get("system3_direct_banter"):   # [s3-roads] memos too\n'
     '                return None\n'
     '            try:\n'
     '                return await globals()["system3_direct_banter"](\n'
     '                    lines=int(lines or 0), bank=bool(bank), dj=dj,\n'
     '                    seats=banter_floor_seats(dj, bool(third), caller_name),\n'
     '                    caller_name=caller_name, caller2_name=caller2_name,\n'
     '                    caller_seat=caller_seat,\n'
     '                    seed_text=str((seed or {}).get("text") or ""),\n'
     '                    seed_file=str((seed or {}).get("file") or ""),\n'
     '                    angle=str(angle or ""), own_material=bool(own_material),\n'
     '                    news_titles=str(news_titles or ""), weather=_weather,\n'
     '                    approach=_approach,\n'
     '                    gazette=bool((_paper_context or {}).get("prompt")),\n'
     '                    system2_job=_system2_job, system2_budget=_system2_budget,\n'
     '                    call_sheet=call_sheet, exchange=exchange,   # [topic-exchange]\n'
     '                    call_meta=(call_meta if isinstance(call_meta, dict) else {}),   # [s3-calls]\n'
     '                    road=str(road or ""), whole=bool(whole),   # [s3-roads]\n'
     '                    lines_rolled=bool(_lines_rolled), lines_base=int(_lines_base),   # [s3-glass]\n'
     '                    lines_min=int(dj.get("banter_min_lines") or 4),\n'
     '                    lines_max=int(dj.get("banter_max_lines") or 22),\n'
     '                    record=({k: str((_RADIO.get("now") or {}).get(k) or "")[:180]\n'
     '                             for k in ("id", "title", "artist")}\n'
     '                            if not bank and str(road or "banter") == "banter"\n'
     '                            and dj.get("track_talk", True) else {}))\n'
     '            except Exception as _s3_exc:  # noqa: BLE001\n'
     '                pipeline_log("system3", "the director was skipped - the legacy running order stands",\n'
     '                             extra=("%s: %s" % (type(_s3_exc).__name__, _s3_exc))[:200])\n'
     '                return None\n'
     '        if not caller_name:\n'
     '            _s3 = await _s3_direct()\n'
     '        _s3_owns = bool(_s3 is not None and _s3.active and _s3.sheet)\n'
     '        if _s3_active() and not caller_name and not _s3_owns:\n'
     '            pipeline_log("system3", "round withheld because its running order was not directed",\n'
     '                         extra=str(road or "banter"))\n'
     '            return []\n'
     '        if _s3_owns and int(getattr(_s3, "turns", 0) or 0) > 0:\n'
     "            # [s3-glass] a free round's length is System 3's roll\n"
     '            lines = int(_s3.turns)\n'
     '            _judge_lines = min(int(_judge_lines), lines)\n'
     '        _topic_at, _topic_new = 0, {}\n'
     '        try:\n'
     '            if (not _s3_owns and banter_dice_on() > 0 and int(lines or 0) >= 8\n'),
    # 4. The call keeps its protocol; System 3 adds the delivery per turn.
    ("call",
     "                _dice_rolls = []\n                raise _CallSheetDone\n",
     '                _s3 = await _s3_direct(call_sheet=_beat_sheet)\n'
     '                if _s3 is not None and _s3.active and _s3.sheet:\n'
     '                    _beat_sheet = _s3.sheet\n'
     '                    _s3_owns = True\n'
     '                elif _s3_active():\n'
     '                    pipeline_log("system3", "call withheld because its running order was not directed")\n'
     '                    return []\n'
     '                _dice_rolls = []\n'
     '                raise _CallSheetDone\n'),
    # 5. System 3's running order, when it owns the round.
    ("sheet",
     "            _beat_sheet, _dice_rolls = banter_beat_sheet(\n                int(lines or 0),\n",
     "            if _s3_owns:\n"
     "                _beat_sheet, _dice_rolls = _s3.sheet, list(_s3.rolls)\n"
     "                _topic_at, _topic_new = _s3.topic_at, dict(_s3.topic_new or {})\n"
     "            else:\n"
     "              _beat_sheet, _dice_rolls = banter_beat_sheet(\n                int(lines or 0),\n"),
    # 6. Mode B: the banked beat chain asks the director before each beat.
    ("beats-call",
     "                seed_text=str((seed or {}).get(\"text\") or \"\"),\n                trace=_beat_trace)\n",
     "                seed_text=str((seed or {}).get(\"text\") or \"\"),\n                trace=_beat_trace,\n"
     "                director=(globals()[\"system3_director\"](_s3)\n"
     "                          if globals().get(\"system3_director\") else None))\n"),
    ("beats-sig",
     "                        trace: list[dict[str, Any]] | None = None) -> str:\n"
     "    \"\"\"Write a banked exchange as responsive 3-4-turn calls.\n",
     "                        trace: list[dict[str, Any]] | None = None,\n"
     "                        director: Any = None) -> str:\n"
     "    \"\"\"Write a banked exchange as responsive 3-4-turn calls.\n"),
    ("beats-loop",
     "        rows = plan[cursor:cursor + 4]\n        started = time.monotonic()\n",
     "        if director is not None and made:\n"
     "            # System 3 Mode B: what was written is observed and the rest\n"
     "            # of the running order is decided again from there.\n"
     "            try:\n"
     "                _fresh = await director(made, cursor, plan[cursor:])\n"
     "                if _fresh:\n"
     "                    plan[cursor:] = _fresh\n"
     "            except Exception:  # noqa: BLE001\n"
     "                pass\n"
     "        rows = plan[cursor:cursor + 4]\n        started = time.monotonic()\n"),
    # 7. Door rolls.
    ("door",
     "        if rec[\"applies\"] and rate > 0:\n            roll = random.random()\n",
     "        if rec[\"applies\"] and rate > 0:\n"
     "            roll = (globals()[\"system3_door_roll\"](_s3, door)\n"
     "                    if globals().get(\"system3_door_roll\") else None)\n"
     "            if roll is None:\n"
     "                roll = random.random()\n"
     "            else:\n"
     "                rec[\"rolled_by\"] = \"system3\"\n"),
    # 8. Bounded repair for a banked round that ignored the running order.
    ("repair",
     "    _draft_entry = {\"script\": script, \"prep_kind\": \"caller\" if caller_name else \"banter\",\n",
     '    if (not _needs_rewrite and not caller_name\n            and globals().get("system3_repair_wanted")\n            and globals()["system3_repair_wanted"](_s3, script)):\n        _needs_rewrite = True\n    # [s3-rewrite] ON A SYSTEM 3 ROUND THE REPAIR ROLL DECIDES. True: a round\n    # that missed goes back, and the review gate below does not cancel it\n    # (with the content gates off it cancelled every repair). False: it\n    # stands as written, whatever the checks found. None: the old rules.\n    _s3_repair = (globals()["system3_repair_roll"](_s3) if globals().get("system3_repair_roll") else None)\n    if _needs_rewrite and _s3_repair is False:\n        pipeline_log("system3", "the round missed its target, and its REPAIR roll said it stands "\n                                "as written - no rewrite")\n        _needs_rewrite = False\n    _draft_entry = {"script": script, "prep_kind": "caller" if caller_name else "banter",\n'),
    ("repair-clause",
     "                    if caller_name else \"\") + \"\\n\\n\"\n                + script,\n",
     "                    if caller_name else \"\")\n"
     "                + (globals()[\"system3_repair_clause\"](_s3)\n"
     "                   if globals().get(\"system3_repair_clause\") else \"\")\n"
     "                + \"\\n\\n\"\n                + script,\n"),
    # 9. Bind the final (tinted, graded) script to the plan.
    ("bind",
     "    if bank:\n        # #842: a round written for a PARTICULAR segment",
     "    if _s3 is not None and globals().get(\"system3_bind_entry\"):\n"
     "        globals()[\"system3_bind_entry\"](entry, _s3)\n"
     "    if bank:\n        # #842: a round written for a PARTICULAR segment"),
    # 10. ES -> the voice, on the prepared render.
    ("perf-prep",
     "                    state=weather_state_for(entry.get(\"weather\"), who)):\n",
     "                    state=((globals()[\"system3_perf_state\"](entry, None, text, who)\n"
     "                            if globals().get(\"system3_perf_state\") else None)\n"
     "                           or weather_state_for(entry.get(\"weather\"), who))):\n"),
    # 11. The SFX Guy: System 3's intent and extra dues, then what played.
    ("sfx-due",
     "    if sfx_due_after(completed, int(settings.get(\"sfx_every_units\") or 0)):\n"
     "        _SFX_CADENCE_STATUS[\"sample_due\"] += 1\n",
     "    _s3_sfx = (globals()[\"system3_sfx_direction\"](meta, who, text)\n"
     "               if globals().get(\"system3_sfx_direction\") else None)\n"
     "    _s3_query = \" \".join(x for x in (text, (_s3_sfx or {}).get(\"query\") or \"\") if x)\n"
     "    _cadence_due = sfx_due_after(completed, int(settings.get(\"sfx_every_units\") or 0))\n"
     "    if _cadence_due or (_s3_sfx or {}).get(\"extra\"):\n"
     "        _SFX_CADENCE_STATUS[\"sample_due\"] += 1\n"),
    ("sfx-video",
     "                    got = await asyncio.to_thread(_sfx_cadence_video_pick, text)\n",
     "                    got = await asyncio.to_thread(_sfx_cadence_video_pick, _s3_query)\n"),
    ("sfx-match",
     "                    matched = await asyncio.to_thread(sfx_match_sting_pick, text, False)\n",
     "                    matched = await asyncio.to_thread(sfx_match_sting_pick, _s3_query, False)\n"),
    ("sfx-observe",
     "            _SFX_CADENCE_STATUS[\"guy_omitted\"] += 1\n    return additions\n",
     "            _SFX_CADENCE_STATUS[\"guy_omitted\"] += 1\n"
     "    if _s3_sfx and globals().get(\"system3_sfx_observe\"):\n"
     "        globals()[\"system3_sfx_observe\"](meta, _s3_sfx, _cadence_due, additions,\n"
     "                            dict(_SFX_MATCH_LAST))\n"
     "    return additions\n"),
    # The matcher's own counts, for "candidates 17 / eligible 13".
    ("match-counts",
     "    _SFX_MATCH_LAST.update({\"path\": got, \"why\": why, \"score\": score,\n"
     "                            \"at\": time.time()})\n",
     "    _SFX_MATCH_LAST.update({\"path\": got, \"why\": why, \"score\": score,\n"
     "                            \"at\": time.time(), \"cands\": len(cands),\n"
     "                            \"tied\": len(tied), \"eligible\": len(survivors)})\n"),
    # 12. The script is frozen and ordered: link each line to its turn.
    ("ledger",
     "    except Exception:  # noqa: BLE001\n        return 0\n",
     None),   # replaced below by a targeted edit (the anchor is not unique)
]

PANEL = [
    ("panel-button",
     '        <button onclick="system2Open()" title="System2 hourly plans, scripts and line diagnostics">System2</button>\n',
     '        <button onclick="system2Open()" title="System2 hourly plans, scripts and line diagnostics">System2</button>\n'
     '        <button onclick="system3Open()" title="System 3, the conversation director: the conversation, the RNG Rolodex and the final script, in sync">System 3</button>\n'),
    ("panel-open",
     '  } catch (error) { setStatus("System2 could not open: " + error.message, true); }\n}\n',
     '  } catch (error) { setStatus("System2 could not open: " + error.message, true); }\n}\n'
     '\n'
     '/* System 3 (docs/system3_blueprint.md): the conversation director\'s\n'
     '   instrument - conversation, RNG Rolodex and final script views. */\n'
     'let system3View = null;\n'
     'async function system3Open(tab) {                       /* [s3-window] tab: tables, segments, prompts, audit, sys3 */\n'
     '  if (system3View) return;\n'
     '  if (!document.getElementById("system3Style")) {\n'
     '    const style = document.createElement("link"); style.id = "system3Style"; style.rel = "stylesheet";\n'
     '    style.href = "/system3/system3.css?v=4"; document.head.append(style);\n'
     '  }\n'
     '  try {\n'
     '    const module = await import("/system3/system3.js?v=5");\n'
     '    system3View = await module.openSystem3({request: (path, options) => api(path, options),\n'
     '      tab: typeof tab === "string" ? tab : "",\n'
     '      onClose: () => { system3View = null; }});\n'
     '  } catch (error) { setStatus("System 3 could not open: " + error.message, true); }\n'
     '}\n'),
    ("panel-palette",
     '      ["\U0001F4CB", "System2", "hourly plans, scripts and line diagnostics", () => system2Open()],\n',
     '      ["\U0001F4CB", "System2", "hourly plans, scripts and line diagnostics", () => system2Open()],\n'
     '      ["\U0001F3B2", "System 3", "the conversation director: every roll behind every line, and the script it made", () => system3Open()],\n'),
]

ROWS = [
    # Every script-ledger line names its System 3 conversation and turn,
    # active or shadow, so any line on the Script page resolves to the
    # decisions behind it with no guessing.
    ("ledger-row-helper",
     "                _script_rows = [\n",
     '                def _s3_row_of(_row_at: int) -> dict[str, Any]:\n'
     "                    # [s3-sfx-roll] the board's clip: the rolls that chose it\n"
     '                    # and its picture ride its stamp, to the ledger and the node\n'
     '                    _st = _s3_row_bare(_row_at)\n'
     '                    _mx = _sfx_meta.get(_row_at)\n'
     '                    if _st and isinstance(_mx, dict) and (_mx.get("sfx_roll") or _mx.get("poster")):\n'
     '                        _st = dict(_st, **{k: _mx[k] for k in ("sfx_roll", "poster") if _mx.get(k)})\n'
     '                    return _st\n'
     '                _script_rows = [\n'),
    ("ledger-row-stamp",
     "                            **({\"dice\": _td_of(_r)} if _td_of(_r) else {}),\n",
     "                            **({\"dice\": _td_of(_r)} if _td_of(_r) else {}),\n"
     "                            **({\"system3\": _s3_row_of(_r)} if _s3_row_of(_r) else {}),\n"),
    ("ledger-row-copy",
     "            **({\"dice\": dict(row[\"dice\"])}\n"
     "               if isinstance(row.get(\"dice\"), dict) else {}),\n",
     "            **({\"dice\": dict(row[\"dice\"])}\n"
     "               if isinstance(row.get(\"dice\"), dict) else {}),\n"
     "            **({\"system3\": dict(row[\"system3\"])}\n"
     "               if isinstance(row.get(\"system3\"), dict) else {}),\n"),
]

TUNE = [
    ('tune-allow',
     '_PUBLIC_GET = {"/healthz", "/api/dj", "/api/dj/voice", "/api/dj/reacts",\n',
     '_PUBLIC_GET = {"/healthz", "/api/dj", "/api/dj/voice", "/api/dj/reacts",\n               # System 3: how each line in the listener feed was composed.\n               # A compact projection behind the tune-in token; nothing about\n               # the station\'s configuration (docs/SYSTEM3_UI_CONTRACT.md).\n               "/api/system3/public/lines",\n'),
    ('tune-css',
     '  .said.me b { color: #ffd479; }\n',
     '  .said.me b { color: #ffd479; }\n  /* System 3: the rolls behind each line, and its card when tapped. */\n  .said.s3-has { cursor: pointer; }\n  .s3-strip { display: grid; gap: 3px; margin: 3px 0 1px; }\n  .s3-d { font: 11px ui-monospace, monospace; color: #9fb0c3; border: 1px solid #1b2735;\n          border-radius: 999px; padding: 0 7px; white-space: nowrap; max-width: 100%;\n          overflow: hidden; text-overflow: ellipsis; justify-self: start; }\n  .s3-d::before { content: ""; display: inline-block; width: 6px; height: 6px; margin-right: 5px;\n                  transform: rotate(45deg); background: var(--f, #7f8ea3); vertical-align: 1px; }\n  /* #1472: the rolodex and the die. The drum scrolls only through the\n     recorded reel and stops on the recorded pick; the die shows nothing\n     while it tumbles and pops to the recorded d100; the words wait behind\n     them and arrive when the last one has landed. */\n  .s3-roll { display: flex; align-items: center; gap: 6px; font: 11px ui-monospace, monospace; }\n  .s3-roll .fam { flex: none; min-width: 72px; color: var(--f, #7f8ea3); font-weight: 700; letter-spacing: .04em; }\n  .s3-drum { position: relative; flex: 1 1 auto; min-width: 0; height: 20px; overflow: hidden; border-radius: 5px;\n             background: #0b121c; border: 1px solid #1b2735;\n             -webkit-mask-image: linear-gradient(transparent, #000 28%, #000 72%, transparent);\n             mask-image: linear-gradient(transparent, #000 28%, #000 72%, transparent); }\n  .s3-drum ul { list-style: none; margin: 0; padding: 0; position: absolute; left: 0; right: 0; top: 0; }\n  .s3-drum li { height: 20px; line-height: 20px; padding: 0 8px; white-space: nowrap; overflow: hidden;\n                text-overflow: ellipsis; color: #7f8ea3; }\n  .s3-drum li.hit { color: #e6eef8; font-weight: 600; }\n  .s3-die { flex: none; width: 30px; height: 22px; border-radius: 5px; display: grid; place-items: center;\n            font: 600 11px ui-monospace, monospace; background: #f4f1e8; color: #1c2624;\n            box-shadow: inset 0 -2px 0 #0003; }\n  .s3-die.none { background: #33474d; color: #9fb0c3; font-weight: 400; }\n  .s3-die.rolling { animation: s3tumble .18s linear infinite; color: transparent; }\n  .s3-die.pop { animation: s3pop .35s ease-out; }\n  @keyframes s3tumble { from { transform: rotate(0) scale(.9); } to { transform: rotate(360deg) scale(.9); } }\n  @keyframes s3pop { 0% { transform: scale(1.4); } 60% { transform: scale(.92); } 100% { transform: scale(1); } }\n  .said .words.typing { color: #7f8ea3; }\n  .said .words.typing::after { content: ""; display: inline-block; width: .5em; height: 1em; margin-left: 2px;\n        vertical-align: -2px; background: currentColor; opacity: .7; animation: s3caret .8s steps(2) infinite; }\n  @keyframes s3caret { 50% { opacity: 0; } }\n  /* #1472c: the dialogue comes together at the end, and each result\'s\n     line arrives as its die lands. */\n  .said .words .w { display: inline-block; opacity: 0; animation: s3in .3s ease-out forwards; }\n  .s3-card .r.arrive, .s3-card .m.arrive { animation: s3in .3s ease-out; }\n  @keyframes s3in { from { opacity: 0; transform: translateY(3px); } to { opacity: 1; transform: none; } }\n  .s3-card { margin: 6px 0 2px; padding: 8px 10px; background: #0b121c; border: 1px solid #1b2735;\n             border-radius: 8px; font-size: 12px; color: #c9d6e3; cursor: auto; }\n  .s3-card .r { font: 11px/1.5 ui-monospace, monospace; margin: 2px 0; }\n  .s3-card .fam { border-left: 3px solid var(--f, #7f8ea3); padding-left: 6px; }\n  .s3-card .m { color: #7f8ea3; margin: 2px 0; }\n  .s3-card .reel { font-size: 11px; padding-left: 9px; }\n  @media (prefers-reduced-motion: reduce) {\n    .s3-die.rolling, .s3-die.pop, .said .words.typing::after, .said .words .w, .s3-card .arrive { animation: none; }\n    .said .words .w { opacity: 1; }\n  }\n'),
    ('tune-feed',
     'function patter(state) {\n  const host = document.getElementById("patter");\n  host.textContent = "";\n  (state.chat || []).slice(-14).forEach((line) => {\n    const row = document.createElement("div");\n    row.className = "said" + (line.who === "host" ? " me" : "");\n    const who = document.createElement("b");\n    who.textContent = line.who === "dj" ? "DJ " : "Request ";\n    row.appendChild(who);\n    row.appendChild(document.createTextNode(line.text));\n    host.appendChild(row);\n  });\n  host.scrollTop = host.scrollHeight;\n}\n',
     '/* System 3 (docs/system3_blueprint.md): THE FEED SHOWS HOW EACH REPLY WAS MADE.\n *\n * "Have the feed ... showing the roulette system and rolodexing of replies\n *  being generated in the conversational feed. Allow users to tap on\n *  messages to expand them and see how they are composed of elements."\n *\n * A line System 3 directed carries its recorded rolls - the emotion, the\n * response, the pushback, the flow, the speakerbox and SFX dice. #1472:\n * "make sure the conversation rolodexes through the results of the node\n * before arriving at the phrase being said ... show the dice rolling and\n * landing on the results, resulting in the rolodex stopping and landing on\n * that result." So each roll is a drum that scrolls ONCE through the\n * candidates that were really in the draw while its die tumbles; the die\n * lands on the d100 it rolled, the drum stops on what was drawn, and only\n * then do the words appear. Nothing is invented for the effect: a line\n * with no recorded roll shows its words at once. Tap a line to open it\n * into its elements.\n *\n * Rows are keyed by the line\'s own id and KEPT between polls, so an open\n * card survives the next refresh; the list only moves to the bottom when\n * the listener was already there. One small request, only when new lines\n * appear, for their compositions (/api/system3/public/lines). */\nconst patterNodes = new Map();   /* line key -> its row */\nconst s3Comp = new Map();        /* line id -> composition, or null */\nlet s3Asking = false;\nlet s3RetryAt = 0;\nconst S3_FAMILY = {CTS: "#8ac6ac", ES: "#f0a6ca", RS: "#87bfff", IRS: "#ffb86b",\n                   FL: "#c4a1ee", SPEAKERBOX: "#e7bf78", SFX: "#7fe0d6"};\nconst s3Still = () => { try { return matchMedia("(prefers-reduced-motion: reduce)").matches; }\n                        catch (e) { return false; } };\n\nfunction patterKey(line, i) {\n  return String(line.id || ((line.ts || "") + ":" + String(line.text || "").slice(0, 48) + ":" + i));\n}\n\nfunction patter(state) {\n  const host = document.getElementById("patter");\n  const rows = (state.chat || []).slice(-14);\n  const near = host.scrollHeight - host.scrollTop - host.clientHeight < 48;\n  const keep = new Set();\n  rows.forEach((line, i) => {\n    const key = patterKey(line, i);\n    keep.add(key);\n    const held = patterNodes.get(key);\n    if (held && held.isConnected) return;\n    const row = patterRow(line, key);\n    patterNodes.set(key, row);\n    host.appendChild(row);\n  });\n  Array.from(host.children).forEach((n) => {\n    if (!keep.has(n.dataset.key)) { patterNodes.delete(n.dataset.key); n.remove(); }\n  });\n  if (near) host.scrollTop = host.scrollHeight;\n  s3Ask(rows);\n}\n\nfunction patterRow(line, key) {\n  const row = document.createElement("div");\n  row.className = "said" + (line.who === "host" ? " me" : "");\n  row.dataset.key = key;\n  const who = document.createElement("b");\n  who.textContent = line.who === "dj" ? "DJ " : "Request ";\n  row.appendChild(who);\n  const words = document.createElement("span");\n  words.className = "words";\n  words.textContent = line.text || "";\n  row.appendChild(words);\n  const strip = document.createElement("div");\n  strip.className = "s3-strip";\n  row.appendChild(strip);\n  const card = document.createElement("div");\n  card.className = "s3-card";\n  card.hidden = true;\n  row.appendChild(card);\n  row.tabIndex = 0;\n  row.setAttribute("role", "button");\n  row.setAttribute("aria-expanded", "false");\n  row.addEventListener("click", () => s3Toggle(row));\n  row.addEventListener("keydown", (e) => {\n    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); s3Toggle(row); }\n  });\n  /* #1472: the words wait behind the rolls. A line whose composition\n   * is already known rolls at once; one still being asked for holds its\n   * words (a caret) until the answer lands, or for a few seconds at most\n   * - a slow station must never hide the conversation. A line no node\n   * made shows its words immediately. */\n  const comp = line.id ? s3Comp.get(String(line.id)) : null;\n  if (comp !== undefined) s3Dress(row, comp, true);\n  else s3Hold(row);\n  return row;\n}\n\nfunction s3Hold(row, deadline) {\n  const words = row.querySelector(".words");\n  if (!words) return;\n  if (!words.classList.contains("typing")) {\n    words.dataset.text = words.textContent;\n    words.textContent = "";\n    words.classList.add("typing");\n  }\n  if (row.__s3Hold) { clearTimeout(row.__s3Hold); row.__s3Hold = 0; }\n  const ms = deadline === undefined ? 4500 : deadline;\n  if (ms > 0) row.__s3Hold = setTimeout(() => s3Release(row), ms);\n}\n\nfunction s3Release(row) {\n  if (row.__s3Hold) { clearTimeout(row.__s3Hold); row.__s3Hold = 0; }\n  const words = row.querySelector(".words");\n  if (!words || !words.classList.contains("typing")) return;\n  words.classList.remove("typing");\n  words.textContent = words.dataset.text || "";\n}\n\n/* #1472c: THE DIALOGUE COMES TOGETHER. The held words arrive one by one,\n   a beat apart, once the last roll has landed. */\nfunction s3Words(row) {\n  const words = row.querySelector(".words");\n  if (!words) return;\n  if (row.__s3Hold) { clearTimeout(row.__s3Hold); row.__s3Hold = 0; }\n  const text = words.classList.contains("typing") ? (words.dataset.text || "") : (words.dataset.text || words.textContent || "");\n  words.classList.remove("typing");\n  if (s3Still()) { words.textContent = text; return; }\n  words.textContent = "";\n  let n = 0;\n  text.split(/(\\s+)/).forEach((p) => {\n    if (!p) return;\n    if (/^\\s+$/.test(p)) { words.appendChild(document.createTextNode(p)); return; }\n    const w = document.createElement("span");\n    w.className = "w";\n    w.textContent = p;\n    w.style.animationDelay = Math.min(1400, n * 45) + "ms";\n    n += 1;\n    words.appendChild(w);\n  });\n}\n\nfunction s3Ask(rows) {\n  if (s3Asking || Date.now() < s3RetryAt) return;\n  const ids = rows.map((r) => String(r.id || ""))\n    .filter((id) => /^[0-9A-Za-z_-]{6,64}$/.test(id) && !s3Comp.has(id)).slice(-16);\n  if (!ids.length) return;\n  s3Asking = true;\n  api("/api/system3/public/lines?ids=" + ids.join(","))\n    .then((got) => {\n      (got.lines || []).forEach((item) => {\n        const comp = item.system3 ? item : null;\n        s3Comp.set(String(item.line_id), comp);\n        const row = patterNodes.get(String(item.line_id));\n        if (row) s3Dress(row, comp, true);\n      });\n      ids.forEach((id) => {\n        if (s3Comp.has(id)) return;\n        s3Comp.set(id, null);\n        const row = patterNodes.get(id);\n        if (row) s3Dress(row, null, false);        /* #1472: nothing to roll */\n      });\n      if (s3Comp.size > 300) {\n        Array.from(s3Comp.keys()).slice(0, s3Comp.size - 300).forEach((k) => s3Comp.delete(k));\n      }\n    })\n    .catch(() => {\n      s3RetryAt = Date.now() + 30000;                  /* the feed still reads */\n      ids.forEach((id) => { const row = patterNodes.get(id); if (row) s3Release(row); });\n    })\n    .finally(() => { s3Asking = false; });\n}\n\nfunction s3Chip(roll) {\n  const chip = document.createElement("span");\n  chip.className = "s3-d";\n  chip.style.setProperty("--f", S3_FAMILY[roll.family] || "#7f8ea3");\n  chip.textContent = roll.family + (roll.dice ? " " + roll.dice : "") + " \\u2192 " + (roll.label || "");\n  chip.title = roll.family + (roll.dice ? " rolled " + roll.dice + "/100" : " (not a draw)")\n    + (roll.of ? ", landed on " + roll.index + " of " + roll.of : "") + ": " + (roll.label || "");\n  return chip;\n}\n\n/* #1472: THE DRUM. Every label in it is a candidate that was really in\n   the draw (the recorded reel), and it stops on the one that was drawn.\n   Two passes through the reel, then the pick - the same honesty rule as\n   the panel\'s Rolodex: it never shows a roll that was not recorded. */\nfunction s3Drum(reel, hit) {\n  const box = document.createElement("div");\n  box.className = "s3-drum";\n  const list = document.createElement("ul");\n  box.appendChild(list);\n  const ROW = 20;\n  const render = (rows, h) => {\n    list.textContent = "";\n    rows.forEach((label, i) => {\n      const li = document.createElement("li");\n      li.textContent = label;\n      if (i === h) li.className = "hit";\n      list.appendChild(li);\n    });\n  };\n  render(reel, hit);\n  list.style.transform = "translateY(" + (-hit * ROW) + "px)";\n  box.roll = (ms) => new Promise((done) => {\n    if (reel.length < 2 || ms <= 0) { done(); return; }\n    const spun = reel.concat(reel, reel.slice(0, hit + 1));\n    render(spun, spun.length - 1);\n    list.style.transition = "none";\n    list.style.transform = "translateY(0)";\n    setTimeout(() => {\n      list.style.transition = "transform " + ms + "ms cubic-bezier(.12,.72,.18,1)";\n      list.style.transform = "translateY(" + (-(spun.length - 1) * ROW) + "px)";\n      setTimeout(() => {\n        list.style.transition = "none";\n        render(reel, hit);\n        list.style.transform = "translateY(" + (-hit * ROW) + "px)";\n        done();\n      }, ms + 30);\n    }, 20);\n  });\n  return box;\n}\n\n/* #1472: THE DIE. Blank while it tumbles; it pops to the d100 that was\n   recorded. A decision that was not a draw shows a dash and never rolls. */\nfunction s3Die(value) {\n  const d = document.createElement("span");\n  const v = Number(value) || 0;\n  d.className = "s3-die" + (v ? "" : " none");\n  d.textContent = v ? String(v) : "\\u2014";\n  d.title = v ? "d100 landed on " + v + " (recorded)" : "not a draw";\n  d.roll = (ms) => new Promise((done) => {\n    if (!v || ms <= 0) { done(); return; }\n    d.classList.add("rolling");\n    setTimeout(() => {\n      d.classList.remove("rolling");\n      d.classList.add("pop");\n      setTimeout(() => d.classList.remove("pop"), 400);\n      done();\n    }, ms);\n  });\n  return d;\n}\n\n/* One recorded roll: its family, its drum and its die. */\nfunction s3RollRow(roll) {\n  let reel = (roll.reel || []).filter(Boolean).map(String);\n  const label = String(roll.label || "");\n  if (!reel.length) reel = [label || roll.family || ""];\n  let hit = reel.indexOf(label);\n  if (hit < 0) hit = Math.min(reel.length - 1, Math.max(0, (Number(roll.index) || 1) - 1));\n  const node = document.createElement("div");\n  node.className = "s3-roll";\n  node.style.setProperty("--f", S3_FAMILY[roll.family] || "#7f8ea3");\n  const fam = document.createElement("span");\n  fam.className = "fam";\n  fam.textContent = roll.family || "";\n  const drum = s3Drum(reel, hit);\n  const die = s3Die(roll.dice);\n  node.appendChild(fam);\n  node.appendChild(drum);\n  node.appendChild(die);\n  node.title = roll.family + (roll.dice ? " rolled " + roll.dice + "/100" : " (not a draw)")\n    + (roll.of ? ", landed on " + roll.index + " of " + roll.of : "") + ": " + label;\n  /* The die lands a beat before the drum settles on the result. */\n  node.roll = (ms) => Promise.all([drum.roll(ms), die.roll(Math.round(ms * 0.85))]);\n  return node;\n}\n\nfunction s3Dress(row, comp, animate) {\n  const strip = row.querySelector(".s3-strip");\n  if (!strip) return;\n  strip.textContent = "";\n  row.classList.toggle("s3-has", !!comp);\n  const turn = comp ? comp.turn : null;\n  const rolls = turn ? (turn.rolls || []) : [];\n  if (comp && !turn) {\n    const chip = document.createElement("span");\n    chip.className = "s3-d";\n    chip.textContent = comp.mode === "shadow" ? "System 3 shadow round" : "System 3 round";\n    strip.appendChild(chip);\n  }\n  const card = row.querySelector(".s3-card");\n  if (card && !card.hidden) { card.hidden = true; s3Toggle(row); }   /* open: refresh it */\n  if (!rolls.length) { s3Release(row); return; }\n  const rows = rolls.map((roll) => s3RollRow(roll));\n  rows.forEach((r) => strip.appendChild(r));\n  if (!animate || s3Still()) { s3Release(row); return; }\n  /* #1472: the rolodex and the dice first, the words after the last one\n   * has landed. Each roll starts a beat after the one before it. */\n  const spins = rows.map((r, i) => new Promise((done) => {\n    const ms = Math.min(1400, 900 + (r.querySelectorAll("li").length || 1) * 60);\n    setTimeout(() => { r.roll(ms).then(done, done); }, i * 140);\n  }));\n  Promise.all(spins).then(() => s3Words(row), () => s3Release(row));\n}\n\nfunction s3Toggle(row) {\n  const card = row.querySelector(".s3-card");\n  if (!card) return;\n  if (row.__s3Playing) return;               /* a replay in flight owns the row */\n  const open = card.hidden;\n  card.hidden = !open;\n  row.setAttribute("aria-expanded", String(open));\n  if (!open) return;\n  const id = row.dataset.key;\n  /* a key with a colon is a row with no line id: not a System 3 line */\n  const comp = s3Comp.has(id) ? s3Comp.get(id) : (id.indexOf(":") >= 0 ? null : undefined);\n  s3Replay(row, comp).catch(() => { s3Release(row); row.__s3Playing = false; });\n}\n'),
]

LEDGER_OLD = ("            if (time.time() - _SCRIPT_LEDGER_PRUNED[0]\n"
              "                    >= SCRIPT_LEDGER_PRUNE_EVERY\n"
              "                    and SCRIPT_LEDGER_PATH.stat().st_size\n"
              "                    > SCRIPT_LEDGER_MAX_BYTES):\n"
              "                _script_ledger_prune()\n"
              "    except Exception:  # noqa: BLE001\n"
              "        return 0\n")
LEDGER_NEW = LEDGER_OLD + ("    if globals().get(\"system3_observe_ledger\"):\n"
                           "        globals()[\"system3_observe_ledger\"](block, sid, rows, round_kind)\n")


DOORS = [
    # 2026-09-26, the operator: "the people are still appearing as if they're
    # talking through each other." Measured on the first directed rounds:
    # the full-swath door (45%, 3,000 characters, seats spread) had dealt one
    # comedy transcript across A and B as eight "turns" - a monologue split
    # between two voices, which nothing can answer. Under System 3 the
    # speakerbox reaches the air inside its running order instead, at these
    # same sliders, read by one speaker and answered by the next (engine v2).
    ("doors-stand-down",
     "        elif rate <= 0:\n            rec.update(applies=True, why=\"the dial is at 0%\")\n",
     "        elif (_s3 is not None and getattr(_s3, \"active\", False)\n"
     "              and getattr(_s3, \"sheet\", \"\")):\n"
     "            rec.update(applies=False, why=(\n"
     "                \"System 3 places the speakerbox inside its running order at \"\n"
     "                \"these sliders - read by one speaker and answered by the \"\n"
     "                \"next - rather than dealing a passage across the seats \"\n"
     "                \"after the writing\"))\n"
     "        elif rate <= 0:\n            rec.update(applies=True, why=\"the dial is at 0%\")\n"),
]


def plan(text):
    edits = ([(n, o, r) for n, o, r in EDITS if r is not None] + [("ledger", LEDGER_OLD, LEDGER_NEW)]
             + PANEL + ROWS + TUNE + DOORS)
    return edits


def check(text):
    missing = []
    applied = 0
    for name, old, new in plan(text):
        if text.count(new) == 1 and (old not in new or text.count(old) == text.count(new)):
            applied += 1
            continue
        if text.count(old) != 1:
            missing.append("%s (anchor found %d times)" % (name, text.count(old)))
    return applied, missing


def apply(path):
    raw = open(path, "rb").read().decode("utf-8")
    # The working tree can hold CRLF (git text=auto, index LF). Python reads
    # both identically; the patched file is written LF, matching the index.
    text = raw.replace("\r\n", "\n")
    done = []
    for name, old, new in plan(text):
        if new in text and (old not in new or text.count(old) == text.count(new)):
            done.append(name + " (already)")
            continue
        n = text.count(old)
        assert n == 1, "%s: anchor found %d times" % (name, n)
        text = text.replace(old, new)
        done.append(name)
    if text != raw:
        tmp = path + ".s3tmp"
        with open(tmp, "wb") as fh:
            fh.write(text.encode("utf-8"))
        os.replace(tmp, path)
    return done


if __name__ == "__main__":
    mode, path = sys.argv[1], sys.argv[2]
    text = open(path, "rb").read().decode("utf-8").replace("\r\n", "\n")
    if mode == "--check":
        applied, missing = check(text)
        total = len(plan(text))
        if applied == total:
            print("APPLIED")
            sys.exit(2)
        if missing:
            print("MISSING: " + "; ".join(missing))
            sys.exit(1)
        print("READY (%d of %d already in)" % (applied, total))
        sys.exit(0)
    if mode == "--apply":
        for row in apply(path):
            print(row)
        sys.exit(0)
