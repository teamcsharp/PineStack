"""[s3-rounds] System 3's rolls reach the air: the writer lane, the seed-only
round, the beat echo, the prompt randoms, the version bump.

Measured 2026-09-27 over 8 h (docs/SYSTEM3_ROLLOUT.md, "Batch 5"):
  * the transcript-repair harvest held the ONE writer lane 54% of the hour
    (610 calls x 25.6 s) and 89% of its replies came back unpunctuated;
  * every round that arrived while it did was refused admission, ask_model
    returned "", and dj_banter prepended the seed passage - so 26 of 33 live
    banter rounds aired as ONE turn of raw transcript, bound one second after
    they were planned; news/memo/gallery System 2 rounds bound ZERO turns;
  * the banked beat writer re-emitted the "immutable" transcript in 163 of
    302 replies and zip() seated the copies as the new turns;
  * four station-side random() directives (tempers, "openly shocked", the
    diatribe interjections, the station-name mention) fought the per-turn ES
    in ~120 one-call prompts - none of them in the Rolodex.

app.py edits, in order of appearance:
  harvest-category   "station:harvest" is its own admission category (cap 1)
  lane-yields        _harvest_yields / _live_round_waits: the harvest waits
                     while any round writer is waiting or active; a LIVE round
                     waits (bounded) for a slot instead of being refused
  ask-purpose-live   mark.live -> purpose "... live"
  ask-deferred       a deferred ROUND raises WritingDeferred (never "")
  one-call-mark      dj_banter names its write: round / caller, live or not
  deferred-withhold  a deferred round is recorded WITHHELD on its conversation
  empty-withhold     a writer that returned no turns withholds the round -
                     the seed passage never stands in for it
  dice/shock/mention/diatribe   the four prompt randoms stand down when
                     System 3 owns the round (its TEMPER/SHOCK/MENTION/INTERJECT
                     rolls are in the running order instead)
  show-memory        "moods right now" stands down under System 3 (the CARRY is the mood)
  harvest-*          the harvest names itself, yields, and a document whose
                     repair came back unpunctuated is marked and skipped 12 h;
                     one harvest per speakbox draw
  beat-fresh         _beat_fresh_only drops the lines a beat handed back that
                     were already spoken before they are seated
  panel-v5           the panel imports system3.js?v=5

Idempotent: --check exits 0 ready / 2 applied / 1 missing; --apply writes LF
atomically. Run it ON THE HOST (app.py is local disk there).
"""
import os
import sys
import tempfile
from pathlib import Path

EDITS = [
    ("harvest-category",
     '    if "tint" in purpose:\n'
     '        return "tint", _ollama_category_cap("tint", purpose)\n'
     '    return "station", _ollama_category_cap("station", purpose)\n',
     '    if "tint" in purpose:\n'
     '        return "tint", _ollama_category_cap("tint", purpose)\n'
     '    if purpose == "station:harvest":\n'
     '        # [s3-rounds] the transcript-repair harvest is its own category: one\n'
     '        # at a time, and it yields to every round writer (_harvest_yields)\n'
     '        return "harvest", 1\n'
     '    return "station", _ollama_category_cap("station", purpose)\n', 1),
    ("lane-yields",
     '@_LAB_RUNTIME.model_call\n'
     'async def call_ollama(\n',
     'LIVE_ROUND_WAIT = 45.0          # [s3-rounds] seconds a LIVE round waits for its writer slot\n'
     'HARVEST_YIELD_MOST = 180.0      # [s3-rounds] seconds the harvest yields to round writers\n'
     '\n'
     '\n'
     'async def _harvest_yields(model: str, purpose: str, most: float = HARVEST_YIELD_MOST,\n'
     '                          beat: float = 1.5) -> float:\n'
     '    """[s3-rounds] THE HARVEST WAITS FOR THE SHOW. Measured 2026-09-27: the\n'
     '    transcript-repair harvest (speakbox_harvest) held the writer lane 54% of\n'
     '    the hour - 610 calls, 25.6 s each - and every live round that arrived\n'
     '    while it did was refused admission, came back "", and aired as its seed\n'
     '    passage alone. A harvest now waits while any station round writer is\n'
     '    waiting or active on the same model, up to `most` seconds, then goes."""\n'
     '    if str(purpose or "") != "station:harvest":\n'
     '        return 0.0\n'
     '    began = time.monotonic()\n'
     '    try:\n'
     '        while time.monotonic() - began < most:\n'
     '            if not any(str(row.get("model")) == str(model)\n'
     '                       and str(row.get("category")) == "station"\n'
     '                       and row.get("state") in ("waiting", "active")\n'
     '                       for row in list(_OLLAMA_JOBS.values())):\n'
     '                break\n'
     '            await asyncio.sleep(beat)\n'
     '    except Exception:  # noqa: BLE001\n'
     '        pass\n'
     '    return time.monotonic() - began\n'
     '\n'
     '\n'
     'async def _live_round_waits(model: str, purpose: str, category: str, cap: int,\n'
     '                            most: float = LIVE_ROUND_WAIT, beat: float = 1.0) -> float:\n'
     '    """[s3-rounds] A LIVE round (its purpose ends " live") waits for a writer\n'
     '    slot rather than being refused on the spot - the refusal returned "" and\n'
     '    the round aired as its seed alone. Bounded by `most`; past it the caller\n'
     '    still sees the deferral, and System 3 withholds the round and says so."""\n'
     '    if not cap or not str(purpose or "").endswith(" live"):\n'
     '        return 0.0\n'
     '    began = time.monotonic()\n'
     '    try:\n'
     '        while time.monotonic() - began < most:\n'
     '            held = sum(row["model"] == model and row["category"] == category\n'
     '                       for row in list(_OLLAMA_JOBS.values()))\n'
     '            if held < cap:\n'
     '                break\n'
     '            await asyncio.sleep(beat)\n'
     '    except Exception:  # noqa: BLE001\n'
     '        pass\n'
     '    return time.monotonic() - began\n'
     '\n'
     '\n'
     '@_LAB_RUNTIME.model_call\n'
     'async def call_ollama(\n', 1),
    ("lane-admission",
     '    orch_used("the writing model", str(model)[:60])\n'
     '    category, _cap = _ollama_category(purpose)\n'
     '    admitted = sum(row["model"] == model and row["category"] == category\n'
     '                   for row in _OLLAMA_JOBS.values())\n',
     '    orch_used("the writing model", str(model)[:60])\n'
     '    category, _cap = _ollama_category(purpose)\n'
     '    await _harvest_yields(model, purpose)                       # [s3-rounds]\n'
     '    await _live_round_waits(model, purpose, category, _cap)     # [s3-rounds]\n'
     '    admitted = sum(row["model"] == model and row["category"] == category\n'
     '                   for row in _OLLAMA_JOBS.values())\n', 1),
    ("ask-purpose-live",
     '        purpose=("sfx_tint_reserve" if _is_tint and _SFX_RESERVE_WRITING.get()\n'
     '                 else "station:" + str((mark or {}).get("kind") or "writing")),\n',
     '        purpose=("sfx_tint_reserve" if _is_tint and _SFX_RESERVE_WRITING.get()\n'
     '                 else "station:" + str((mark or {}).get("kind") or "writing")\n'
     '                 + (" live" if (mark or {}).get("live") else "")),    # [s3-rounds]\n', 1),
    ("ask-deferred",
     '        if "tint" in _mark_kind or _mark_kind == "banter beat":\n'
     '            raise WritingDeferred(str(result.get("reason") or "the writer is fully admitted"))\n'
     '        return ""                       # no compute/quality failure is charged\n',
     '        if "tint" in _mark_kind or _mark_kind in ("banter beat", "round", "caller"):\n'
     '            # [s3-rounds] a ROUND\'s deferral is raised, never swallowed: "" here\n'
     '            # became a one-turn round (the seed passage alone) 26 times in 8 h\n'
     '            raise WritingDeferred(str(result.get("reason") or "the writer is fully admitted"))\n'
     '        return ""                       # no compute/quality failure is charged\n', 1),
    ("one-call-mark",
     '                mark=({"kind": "caller"} if caller_name else None),\n',
     '                mark=({"kind": "caller", "live": not bank} if caller_name\n'
     '                      else {"kind": "round", "live": not bank}),   # [s3-rounds]\n', 1),
    ("deferred-withhold",
     '    except WritingDeferred as exc:\n'
     '        pipeline_log("lookahead", "the banked beat chain remains owed - "\n'
     '                     + str(exc)[:160])\n'
     '        return []\n',
     '    except WritingDeferred as exc:\n'
     '        pipeline_log("lookahead", "the banked beat chain remains owed - "\n'
     '                     + str(exc)[:160])\n'
     '        if _s3 is not None and globals().get("system3_withhold"):      # [s3-rounds]\n'
     '            globals()["system3_withhold"](_s3, "the writer was deferred: " + str(exc)[:160], "writing")\n'
     '        return []\n', 1),
    ("empty-withhold",
     '    # #805: ask_model returns "" when the reply fragment-binned — not an\n'
     '    # exception, and previously not a call either. Same guarantee.\n'
     '    if caller_name and not spoken_text(script or "") and _s3 is not None and getattr(_s3, "active", False):\n',
     '    if _s3_owns and not caller_name and not banter_turns(script or ""):\n'
     '        # [s3-rounds] NEVER THE SEED ALONE. A writer that returned nothing (a\n'
     '        # fragment-binned reply, a refused draft) fell through to the seed\n'
     '        # prepend below and aired as ONE turn of raw transcript with no reply\n'
     '        # and no close - 26 of 33 live banter rounds in 8 h, bound one second\n'
     '        # after they were planned. The round is withheld and says why.\n'
     '        if globals().get("system3_withhold"):\n'
     '            globals()["system3_withhold"](_s3, "the writer returned no turns", "writing")\n'
     '        pipeline_log("system3", "round withheld: the writer returned no turns - the seed passage does "\n'
     '                     "not stand in for a conversation", extra=str(road or "banter"))\n'
     '        return []\n'
     '    # #805: ask_model returns "" when the reply fragment-binned — not an\n'
     '    # exception, and previously not a call either. Same guarantee.\n'
     '    if caller_name and not spoken_text(script or "") and _s3 is not None and getattr(_s3, "active", False):\n', 1),
    ("shock-random",
     '            f"previous one. At least once, {random.choice([\'A\', \'B\'])} is "\n'
     '            f"openly {unrepeated([\'shocked\', \'surprised\', \'furious\', \'in disbelief\', \'delighted\', \'appalled\'], \'internalize\')} "\n'
     '            "at what the other has JUST said, says so, and the rest of the "\n'
     '            "conversation is driven by that. This time: "\n',
     '            "previous one. "\n'
     '            # [s3-rounds] under System 3 the SHOCK roll places this beat on a turn\n'
     '            + ("" if _s3_owns else\n'
     '               f"At least once, {random.choice([\'A\', \'B\'])} is "\n'
     '               f"openly {unrepeated([\'shocked\', \'surprised\', \'furious\', \'in disbelief\', \'delighted\', \'appalled\'], \'internalize\')} "\n'
     '               "at what the other has JUST said, says so, and the rest of the "\n'
     '               "conversation is driven by that. ")\n'
     '            + "This time: "\n', 1),
    ("mention-random",
     '            + (f"Work the station\'s name, {dj[\'station_name\']}, in naturally "\n'
     '               "once — the pair are proud of where they work (#459). "\n'
     '               if random.random() < 0.3 else\n'
     '               "Do not lean on the station\'s name this round — the station "\n'
     '               "IDs handle that (#355). ")\n',
     '            + ("" if _s3_owns else                       # [s3-rounds] the MENTION roll\n'
     '               f"Work the station\'s name, {dj[\'station_name\']}, in naturally "\n'
     '               "once — the pair are proud of where they work (#459). "\n'
     '               if random.random() < 0.3 else\n'
     '               "Do not lean on the station\'s name this round — the station "\n'
     '               "IDs handle that (#355). ")\n', 1),
    ("dice-random",
     '               if dj.get("dice_hosts") else "")\n',
     '               if dj.get("dice_hosts") and not _s3_owns else "")   # [s3-rounds] TEMPER rolls it\n', 1),
    ("diatribe-random",
     '               if dj.get("diatribe_interjections") and not caller_name else "")\n',
     '               if dj.get("diatribe_interjections") and not caller_name and not _s3_owns else "")   # [s3-rounds] INTERJECT rolls it\n', 1),
    ("show-memory-call",
     '            f"{show_memory(own_material=own_material)}{call_flow}"\n',
     '            f"{show_memory(own_material=own_material, system3=_s3_active())}{call_flow}"\n', 1),
    ("show-memory-def",
     'def show_memory(own_material: bool = False) -> str:\n',
     'def show_memory(own_material: bool = False, system3: bool = False) -> str:\n', 1),
    ("show-memory-moods",
     '    if moods:\n'
     '        bits.append("moods right now: " + ", ".join(\n',
     '    if moods and not system3:          # [s3-rounds] under System 3 the ES rolls and the CARRY are the mood\n'
     '        bits.append("moods right now: " + ", ".join(\n', 1),
    ("harvest-helpers",
     'async def speakbox_harvest(doc: Path, rid: str = "") -> list[str]:\n',
     'HARVEST_BAD_FOR = 12 * 3600.0     # [s3-rounds] a document whose repair came back unpunctuated waits this long\n'
     '_HARVEST_BAD: dict[str, float] = {}\n'
     '_HARVEST_BAD_PATH = data_path("speakbox_harvest_bad.json")\n'
     '\n'
     '\n'
     'def _harvest_bad_load() -> None:\n'
     '    if _HARVEST_BAD:\n'
     '        return\n'
     '    try:\n'
     '        got = json.loads(_HARVEST_BAD_PATH.read_text(encoding="utf-8"))\n'
     '        if isinstance(got, dict):\n'
     '            _HARVEST_BAD.update({str(k): float(v) for k, v in got.items()})\n'
     '    except Exception:  # noqa: BLE001\n'
     '        pass\n'
     '\n'
     '\n'
     'def harvest_unrepaired(text: str) -> bool:\n'
     '    """[s3-rounds] A transcript repair that is still a transcript: fewer than\n'
     '    one sentence end per 300 characters over a reply long enough to judge\n'
     '    (505 of 566 replies on 2026-09-27 had none at all)."""\n'
     '    body = str(text or "").strip()\n'
     '    if len(body) < 300:\n'
     '        return not body\n'
     '    ends = len(re.findall(r"[.!?]", body))\n'
     '    return ends * 300 < len(body)\n'
     '\n'
     '\n'
     'def harvest_mark_bad(doc: Path, found: str = "") -> None:\n'
     '    _harvest_bad_load()\n'
     '    _HARVEST_BAD[doc.name] = time.time()\n'
     '    try:\n'
     '        _HARVEST_BAD_PATH.write_text(json.dumps(_HARVEST_BAD), encoding="utf-8")\n'
     '    except Exception:  # noqa: BLE001\n'
     '        pass\n'
     '    pipeline_log("speakbox", f"the transcript repair of {doc.name} came back unpunctuated - the document "\n'
     '                             f"is skipped for {int(HARVEST_BAD_FOR // 3600)} h; sentence windows stand in",\n'
     '                 extra=str(found or "")[:600])\n'
     '\n'
     '\n'
     'def harvest_skipped(doc: Path) -> bool:\n'
     '    _harvest_bad_load()\n'
     '    at = _HARVEST_BAD.get(doc.name)\n'
     '    if not at:\n'
     '        return False\n'
     '    if time.time() - float(at) > HARVEST_BAD_FOR:\n'
     '        _HARVEST_BAD.pop(doc.name, None)\n'
     '        return False\n'
     '    return True\n'
     '\n'
     '\n'
     'async def speakbox_harvest(doc: Path, rid: str = "") -> list[str]:\n', 1),
    ("harvest-call",
     '            + body, limit=5200, result_contract="transcript_repair")  # #1039\n'
     '    except Exception:\n'
     '        return []\n'
     '\n'
     '    # "Here is the repaired text:" is not one of the gems.\n',
     '            + body, limit=5200, result_contract="transcript_repair",\n'
     '            mark={"kind": "harvest"})  # #1039  [s3-rounds] its own lane category; yields to rounds\n'
     '    except Exception:\n'
     '        return []\n'
     '    if harvest_unrepaired(found):\n'
     '        # [s3-rounds] the model handed the transcript back as it came - no\n'
     '        # sentence in it. Shelving that as gems put unpunctuated transcript in\n'
     '        # the hosts\' mouths and asked for the same repair again on the next\n'
     '        # draw. The document is marked and skipped; sentence windows stand in.\n'
     '        harvest_mark_bad(doc, found)\n'
     '        return []\n'
     '\n'
     '    # "Here is the repaired text:" is not one of the gems.\n', 1),
    ("harvest-once-flag",
     '    for doc in order[:6]:               # a doc of pure headings is not fatal\n',
     '    _harvested = False                  # [s3-rounds] one model repair per draw, at most\n'
     '    for doc in order[:6]:               # a doc of pure headings is not fatal\n', 1),
    ("harvest-once-gate",
     '            # Nothing left they have not used: read the document again at a\n'
     '            # different point rather than repeat themselves.\n'
     '            gems = await speakbox_harvest(doc, key) or gems\n'
     '            if not gems:                # the model is down; the show is not\n',
     '            # Nothing left they have not used: read the document again at a\n'
     '            # different point rather than repeat themselves.\n'
     '            # [s3-rounds] one harvest per draw, never a document whose repair\n'
     '            # came back unpunctuated: six failing repairs in one draw (25 s\n'
     '            # each) was how the harvest took over the writer lane\n'
     '            if not _harvested and not harvest_skipped(doc):\n'
     '                _harvested = True\n'
     '                gems = await speakbox_harvest(doc, key) or gems\n'
     '            if not gems:                # the model is down; the show is not\n', 1),
    ("beat-fresh-def",
     'def _beat_answers(previous: str, fresh: str) -> bool:\n',
     'def _beat_fresh_only(parsed: list[tuple[str, str]],\n'
     '                     made: list[tuple[str, str]]) -> list[tuple[str, str]]:\n'
     '    """[s3-rounds] Drop the lines a beat handed back that were already\n'
     '    spoken. The writer re-emits the "immutable" completed transcript in\n'
     '    half its replies (163 of 302, 2026-09-27) and the zip below seated\n'
     '    those copies as the NEW turns - B\'s rolled "dread, takes the lead"\n'
     '    aired as B\'s earlier line word for word - while the fresh lines it\n'
     '    wrote after them were thrown away. A candidate that matches a made\n'
     '    line, or an earlier candidate in the same reply, is not a turn."""\n'
     '    import difflib\n'
     '\n'
     '    def key(text: str) -> str:\n'
     '        return " ".join(re.findall(r"[a-z0-9\']+", str(text or "").lower()))\n'
     '    seen = [key(text) for _m, text in made if str(text or "").strip()]\n'
     '    out: list[tuple[str, str]] = []\n'
     '    for marker, text in parsed:\n'
     '        k = key(text)\n'
     '        if not k:\n'
     '            continue\n'
     '        dup = False\n'
     '        for old in seen:\n'
     '            if k == old or (len(k) >= 24 and len(old) >= 24 and (k in old or old in k)):\n'
     '                dup = True\n'
     '                break\n'
     '            if len(k) >= 24 and difflib.SequenceMatcher(None, k, old, autojunk=False).ratio() >= 0.85:\n'
     '                dup = True\n'
     '                break\n'
     '        if dup:\n'
     '            continue\n'
     '        seen.append(k)\n'
     '        out.append((marker, text))\n'
     '    return out\n'
     '\n'
     '\n'
     'def _beat_answers(previous: str, fresh: str) -> bool:\n', 1),
    ("beat-fresh-use",
     '        parsed = banter_turns(raw or "")\n'
     '        clean: list[tuple[str, str]] = []\n'
     '        for row, candidate in zip(rows, parsed):\n',
     '        parsed = _beat_fresh_only(banter_turns(raw or ""), made)    # [s3-rounds]\n'
     '        clean: list[tuple[str, str]] = []\n'
     '        for row, candidate in zip(rows, parsed):\n', 1),
    ("beat-correction",
     '            "Use one of its concrete words in the first reply."\n'
     '            if retry else "")\n',
     '            "Use one of its concrete words in the first reply. Do not repeat any line from the "\n'
     '            "completed transcript; every listed turn is a NEW line."\n'
     '            if retry else "")\n', 1),
    ("harvest-pause-consts",
     'HARVEST_BAD_FOR = 12 * 3600.0     # [s3-rounds] a document whose repair came back unpunctuated waits this long\n',
     'HARVEST_BAD_FOR = 12 * 3600.0     # [s3-rounds] a document whose repair came back unpunctuated waits this long\n'
     'HARVEST_PAUSE_AFTER = 5           # [s3-rounds] unrepaired repairs in a row before the harvest pauses...\n'
     'HARVEST_PAUSE_FOR = 3600.0        # ...for this long: the model cannot do it tonight\n', 1),
    ("harvest-pause-streak",
     'def harvest_mark_bad(doc: Path, found: str = "") -> None:\n'
     '    _harvest_bad_load()\n'
     '    _HARVEST_BAD[doc.name] = time.time()\n',
     'def harvest_mark_bad(doc: Path, found: str = "") -> None:\n'
     '    _harvest_bad_load()\n'
     '    _HARVEST_BAD[doc.name] = time.time()\n'
     '    # [s3-rounds] five unrepaired in a row: the model cannot do this tonight;\n'
     '    # the harvest pauses an hour rather than trying every document in turn\n'
     '    _HARVEST_BAD["__streak__"] = float(_HARVEST_BAD.get("__streak__") or 0) + 1\n'
     '    if _HARVEST_BAD["__streak__"] >= HARVEST_PAUSE_AFTER:\n'
     '        _HARVEST_BAD["__pause_until__"] = time.time() + HARVEST_PAUSE_FOR\n'
     '        _HARVEST_BAD["__streak__"] = 0.0\n'
     '        pipeline_log("speakbox", "the transcript repair has come back unpunctuated %d times running - the "\n'
     '                                 "harvest pauses for %d min; sentence windows stand in"\n'
     '                     % (HARVEST_PAUSE_AFTER, int(HARVEST_PAUSE_FOR // 60)))\n', 1),
    ("harvest-pause-skip",
     'def harvest_skipped(doc: Path) -> bool:\n'
     '    _harvest_bad_load()\n'
     '    at = _HARVEST_BAD.get(doc.name)\n',
     'def harvest_skipped(doc: Path) -> bool:\n'
     '    _harvest_bad_load()\n'
     '    if float(_HARVEST_BAD.get("__pause_until__") or 0) > time.time():\n'
     '        return True                 # [s3-rounds] the harvest is paused\n'
     '    at = _HARVEST_BAD.get(doc.name)\n', 1),
    ("harvest-pause-reset",
     '        harvest_mark_bad(doc, found)\n'
     '        return []\n'
     '\n'
     '    # "Here is the repaired text:" is not one of the gems.\n',
     '        harvest_mark_bad(doc, found)\n'
     '        return []\n'
     '    _harvest_bad_load()\n'
     '    _HARVEST_BAD["__streak__"] = 0.0          # [s3-rounds] a real repair ends the run\n'
     '\n'
     '    # "Here is the repaired text:" is not one of the gems.\n', 1),
    ("panel-v5",
     '    const module = await import("/system3/system3.js?v=4");\n',
     '    const module = await import("/system3/system3.js?v=5");\n', 1),
]



# [integration 2026-09-28] system3_module_v6_patch.py edited inside this tool's 'panel-v5' text
# (panel-v6): "applied" is that text with those edits folded in. The anchor is
# unchanged, so a fresh file is patched exactly as before.
# [s3-banks-roll 2026-09-28] system3_banks_roll_patch.py (s3js-vbump) bumped the
# import to ?v=7 inside that same text; folded forward again.
_RECONCILED_PANEL_V5 = '    const module = await import("/system3/system3.js?v=7");   // [s3-banks-roll] replay / gold / listening chips on the turn\n'
EDITS = [(e[0], e[1], _RECONCILED_PANEL_V5, e[3]) if e[0] == 'panel-v5' else e for e in EDITS]

def plan(text):
    return list(EDITS)


def marker_of(old, new):
    """The most distinctive line an edit inserts: the longest line of `new`
    that is not a line of `old`. Its presence means the edit is applied, even
    after a later edit changed the block around it (the way the harvest-pause
    edits change the harvest helpers)."""
    old_lines = set(old.splitlines())
    cands = [ln for ln in new.splitlines() if ln.strip() and ln not in old_lines]
    return max(cands, key=len) if cands else new


def state_of(text, old, new, count):
    if marker_of(old, new) in text:
        return "applied"
    n_old = text.count(old)
    if n_old == count:
        return "ready"
    return "anchor found %d times, wanted %d; not applied" % (n_old, count)


def check(text):
    """Sequential: an edit may anchor on text an earlier edit inserted, so the
    later anchors are judged on the file as the earlier edits would leave it."""
    applied, missing = 0, []
    work = text
    for name, old, new, count in plan(text):
        state = state_of(work, old, new, count)
        if state == "applied":
            applied += 1
        elif state == "ready":
            work = work.replace(old, new)
        else:
            missing.append("%s: %s" % (name, state))
    return applied, missing


def apply(path):
    p = Path(path)
    text = p.read_bytes().decode("utf-8")
    if "\r\n" in text:
        text = text.replace("\r\n", "\n")
    applied, missing = check(text)
    if missing:
        print("\n".join(missing))
        return 1
    if applied == len(plan(text)):
        print("already applied")
        return 2
    done = 0
    for name, old, new, count in plan(text):
        if state_of(text, old, new, count) == "applied":
            continue
        assert text.count(old) == count, name
        text = text.replace(old, new)
        done += 1
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=p.name + ".", suffix=".tmp")
    with os.fdopen(fd, "wb") as fh:
        fh.write(text.encode("utf-8"))
    os.replace(tmp, str(p))
    print("applied %d edit(s)" % done)
    return 0


def main(argv):
    if len(argv) < 3 or argv[1] not in ("--check", "--apply"):
        print("usage: system3_rounds_patch.py --check|--apply <app.py>")
        return 1
    if argv[1] == "--check":
        text = Path(argv[2]).read_bytes().decode("utf-8").replace("\r\n", "\n")
        applied, missing = check(text)
        total = len(plan(text))
        if missing:
            print("\n".join(missing))
            return 1
        if applied == total:
            print("applied (%d/%d)" % (applied, total))
            return 2
        print("ready (%d applied, %d to go)" % (applied, total - applied))
        return 0
    return apply(argv[2])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
