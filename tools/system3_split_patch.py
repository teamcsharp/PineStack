"""[s3-split] The SPLIT node at the station's doors, and the text caps that
cut a line mid-word.

The operator, 2026-09-28: "Find out why this message split and I want you to
prevent that from happening. Don't want any messages getting cut off when
they're being spoken on the air. But also for a message like this that exceeds
a certain amount of characters, we need to introduce the roulette of a split
node, which basically allows a particular message to be split and who says it
... ad spots ... monologues ... A long statment or ad read or manager read can
have up to 3 splits with splits being a checkbox we can enable to a particular
message node."

  split-helpers / dj-speak-* / split-point / split-cadence-hold
      a single line whose node splits is shared out where its words are final
      (_dj_speak_floorless, after the busy-box door, before the render): the
      later parts are made ahead and spoken straight after the first, in
      order, under one floor, each in its reader's voice, each its own line
      with its own stamp (system3_runtime.split_line; system3.split_turn); the
      SFX cadence welds after the last part only
  split-part-not-a-repeat   a later part is a piece of a read the #494 ring
      already holds whole
  upstairs-*   the manager's page split as it is written: his recording keeps
      part 1, a booth voice reads the rest on before the pair react; the row
      keeps its stamp and parts (upstairs_update dropped `system3`)
  ledger-text-whole / ad-*-whole / upstairs-save-whole   the station's own
      caps: the script ledger cut station IDs at 2,000 characters (they ran
      112-150 s); the ad book cut a read at 1,200 - and a stored read reruns
      those words aloud
  gold-*   a gold bar was a turn's LAST chunk's take filed under the whole
      turn's words, and fired as a fragment (162 characters in 2.4 s, 5 times):
      only a take that holds its turn is banked, and a banked take that cannot
      hold its words loses the take (the line stays, as gold_trim does)
  page-cut-*   #1237's targeted cut stopped a record's intro mid-word when it
      was sounding; now only the queued clips go with their record

Needs system3_runtime.py with [s3-split] (system3_split_line, system3_note_pace
in the namespace); without it every split door stands aside and lines air whole.

--check exits 0 ready / 2 applied / 1 missing. --apply is idempotent, atomic
and LF-only. ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

EDITS = [
    ('split-helpers',
     'async def _dj_speak_floorless(kind: str, track: dict[str, Any] | None = None,\n',
     '# --- [s3-split] THE SPLIT NODE AT THE MICROPHONE --------------------------------\n#\n# The operator, 2026-09-28: "for a message like this that exceeds a certain\n# amount of characters, we need to introduce the roulette of a split node,\n# which basically allows a particular message to be split and who says it ...\n# ad spots ... monologues ... if the person\'s about to say something that\'s\n# going to exceed a minute or approach forty-five seconds, then that should be\n# split with another person in the studio who\'s also able to say it insert\n# themselves and continue it."\n#\n# Every single line reaches the air through dj_speak -> _dj_speak_floorless.\n# There - its words final (written, scrubbed, tinted, checked), the box not\n# holding it back, nothing rendered yet - the line\'s own System 3 node is\n# asked (system3_split_line). A node whose splits box is ticked and whose read\n# runs past the threshold at the voice\'s pace comes back in parts, each with\n# the studio member the roulette picked, the way the Insertion list drew and\n# the stamp its own ledger row carries. The later parts are made (rendered)\n# before the first part airs - the read starts no later than the whole of it\n# would have - and dj_speak speaks them straight after it, in order, under\n# the same floor, each a message of its own. The SFX cadence welds after the\n# last part only: a split read counts as one line. A whole take made ahead\n# (the pantry) is not a reason to read it whole - the parts are voiced now.\n# The manager\'s page is split the same way when it is written: his recording\n# keeps the first part and a booth voice reads on.\n#\n# _S3_SPLIT_TAIL: dj_speak\'s box for the parts after the first - set around\n# its one call, claimed by the first split on that same task.\n# _S3_SPLIT_HOLD: set while a part that is not the last one is spoken.\n_S3_SPLIT_TAIL: ContextVar[dict[str, Any] | None] = ContextVar("s3_split_tail", default=None)\n_S3_SPLIT_HOLD: ContextVar[bool] = ContextVar("s3_split_hold", default=False)\n\n\nasync def _s3_split_render(text: str, who: str, voice: str) -> dict[str, Any] | None:\n    """[s3-split] A later part\'s take, made before the first part airs, so the\n    parts follow one another with no render between them: the seat\'s voice,\n    its engine, the booth\'s usual effects and delivery. None when it could not\n    be made (the part then renders when its turn comes)."""\n    try:\n        engine = voice_engine_for(voice or "")\n        if engine == "voxtral" and not (await voxtral_health())["ready"]:\n            engine = ""\n        fx = dict(voice_effect_pick() or {})\n        vec = performance_vector(who, voice or "")\n        if vec:\n            fx["perf"] = vec\n        strip = (str(dj_settings().get(f"strip_{who}") or "")\n                 if who in ("dj", "cohost", "caller", "third") else "")\n        if strip:\n            fx["strip"] = strip\n        clip = await voice_render_any(text, voice or _event_voice("default"), engine, fx=fx,\n                                      who=who, script_index=1, script_total=1)\n        return clip if (clip or {}).get("path") else None\n    except Exception as exc:  # noqa: BLE001\n        pipeline_log("system3", "[s3-split] a part could not be made ahead - it renders when it airs",\n                     extra=("%s: %s" % (type(exc).__name__, exc))[:200])\n        return None\n\n\nasync def _s3_split_line(kind: str, spoken: str, who: str, forced: Any, stamp: Any,\n                         handle: Any) -> tuple[str, dict[str, Any], list[dict[str, Any]]] | None:\n    """[s3-split] Ask the line\'s node whether the read is shared out. Returns\n    (the first part\'s words, its stamp, the later parts - each with its\n    reader, voice, words, stamp and its take made ahead) or None: the read\n    airs whole (the node does not split, the read is under the threshold, it\n    has no sentence end to cut at, nobody else is in the studio, a fault)."""\n    ask = globals().get("system3_split_line")\n    if not ask or not isinstance(stamp, dict) or not stamp.get("conversation_id"):\n        return None\n    prepared = False\n    try:\n        _pv = forced or _event_voice("default")\n        prepared = _pantry_key_ready(pantry_key(spoken, _pv, voice_engine_for(forced or "") or voice_engine_for(_pv)))\n    except Exception:  # noqa: BLE001\n        prepared = False\n    try:\n        got = ask(stamp, spoken, who=who, dj=dj_settings(), handle=handle, kind=kind,\n                  away=seat_away_who(), prepared=prepared)\n    except Exception as exc:  # noqa: BLE001\n        pipeline_log("system3", "[s3-split] the split node could not be asked - the read airs whole",\n                     extra=("%s: %s" % (type(exc).__name__, exc))[:200])\n        return None\n    parts = (got or {}).get("parts") or []\n    if not (got or {}).get("split") or len(parts) < 2:\n        return None\n    voices = await session_voices()\n    rest: list[dict[str, Any]] = []\n    for p in parts[1:]:\n        pwho = str(p.get("who") or "dj")\n        pvoice = str(p.get("voice") or "") or configured_radio_voice(pwho, voices.get(pwho) or "")\n        words = spoken_text(str(p.get("text") or ""))\n        if kind not in ("station_id", "reply"):\n            words = station_name_scrub(words)\n        rest.append(dict(p, text=words, voice=pvoice, clip=await _s3_split_render(words, pwho, pvoice),\n                         whole=str(got.get("whole") or spoken)))\n    pipeline_log("system3", "[s3-split] a %s read is shared out: %s" % (\n                     kind, " / ".join(str(p.get("name") or p.get("who")) for p in parts)),\n                 extra=" | ".join("%s: %s" % (p.get("name"), str(p.get("text") or "")[:90]) for p in parts))\n    return str(parts[0].get("text") or spoken), dict(parts[0].get("stamp") or stamp), rest\n\n\nasync def _s3_split_speak(kind: str, track: dict[str, Any] | None, parts: list[dict[str, Any]],\n                          sid: str = "", round_as: str = "", bound: dict[str, Any] | None = None,\n                          bound_part: str = "", sting: bool = True) -> list[str]:\n    """[s3-split] The parts after the first, in order, each in its reader\'s\n    own voice and each a line of its own - under one floor, so nothing is\n    spoken between them. A part that cannot be voiced stops the read there,\n    and says so (a part is never voiced twice, nor out of its order)."""\n    said: list[str] = []\n    owned = await _floor_take(f"a long {kind} read, shared out")\n    try:\n        for n, p in enumerate(parts):\n            words = str(p.get("text") or "").strip()\n            if not words:\n                continue\n            if radio_paused():\n                pipeline_log("drop", "[s3-split] the station paused mid-read: %d part(s) left unsaid"\n                             % (len(parts) - n))\n                break\n            got = ""\n            _hold = _S3_SPLIT_HOLD.set(n < len(parts) - 1)\n            try:\n                got = await _dj_speak_floorless(\n                    kind, track, line=words, who=str(p.get("who") or "dj"),\n                    voice=(str(p.get("voice") or "") or None), name=str(p.get("name") or ""),\n                    clip=p.get("clip"), checked=True, remember_text=words, sting=sting, sid=sid,\n                    round_as=round_as, bound=bound, bound_part=bound_part,\n                    system3=(dict(p.get("stamp") or {}) or None))\n            except Exception as exc:  # noqa: BLE001\n                pipeline_log("drop", "[s3-split] part %s of a split read failed" % p.get("part"),\n                             extra=("%s: %s" % (type(exc).__name__, exc))[:200])\n            finally:\n                _S3_SPLIT_HOLD.reset(_hold)\n            if not got:\n                pipeline_log("drop", "[s3-split] part %s of %s (%s) was not voiced - the read stops there"\n                             % (p.get("part"), p.get("of"), p.get("name") or p.get("who")), extra=words[:300])\n                break\n            said.append(got)\n    finally:\n        _floor_drop(owned)\n    return said\n\n\nasync def _s3_split_page(row: dict[str, Any], handle: Any, text: str) -> None:\n    """[s3-split] The manager\'s page on its node, as it is written: past the\n    threshold at his pace, his recording keeps the first part and the rest is\n    read on by the booth - each part with its reader, their words and the\n    stamp its line carries, kept on the page\'s row, so a page recorded now and\n    aired later still reads on."""\n    ask = globals().get("system3_split_line")\n    if not ask or handle is None or not getattr(handle, "stamp", None):\n        return\n    try:\n        got = ask(dict(handle.stamp), text, who="manager", dj=dj_settings(), handle=handle, kind="manager",\n                  away=seat_away_who())\n    except Exception as exc:  # noqa: BLE001\n        pipeline_log("system3", "[s3-split] the page\'s split node could not be asked - it airs whole",\n                     extra=("%s: %s" % (type(exc).__name__, exc))[:200])\n        return\n    parts = (got or {}).get("parts") or []\n    if not (got or {}).get("split") or len(parts) < 2:\n        return\n    rest = [{k: p.get(k) for k in ("part", "of", "who", "seat", "name", "voice", "text", "body",\n                                   "lead_in", "how", "stamp")} for p in parts[1:]]\n    split = {"whole": str(got.get("whole") or text), "parts": rest}\n    first = str(parts[0].get("body") or text)\n    stamp = dict(parts[0].get("stamp") or handle.stamp)\n    upstairs_update(str(row.get("id") or ""), text=first, split=split, system3=stamp)\n    row.update(text=first, split=split, system3=stamp)\n    pipeline_log("system3", "[s3-split] a page from upstairs is shared out: the manager, then "\n                 + " / ".join(str(p.get("name") or p.get("who")) for p in rest))\n\n\nasync def _dj_speak_floorless(kind: str, track: dict[str, Any] | None = None,\n', 1),
    ('dj-speak-box',
     '    try:\n        return await _dj_speak_floorless(\n',
     '    _s3_box: dict[str, Any] = {"parts": [], "claimed": False,                  # [s3-split] the parts after the first\n                               "task": asyncio.current_task()}\n    _s3_tok = _S3_SPLIT_TAIL.set(_s3_box)\n    try:\n        said = await _dj_speak_floorless(\n', 1),
    ('dj-speak-parts',
     '            system3=system3)   # [s3-roads]\n    finally:\n        _floor_drop(_owned)\n',
     '            system3=system3)   # [s3-roads]\n        if said and _s3_box["parts"]:\n            # [s3-split] THE READ GOES ON in the voices the roulette picked: each part a\n            # line of its own, in order, under this same floor\n            await _s3_split_speak(kind, track, _s3_box["parts"], sid=sid, round_as=round_as,\n                                  bound=bound, bound_part=bound_part, sting=sting)\n            said = str(_s3_box["parts"][0].get("whole") or said)\n        elif _s3_box["parts"]:\n            pipeline_log("drop", "[s3-split] the first part of a split %s read did not go out - "\n                                 "the parts after it go with it" % kind)\n        return said\n    finally:\n        _S3_SPLIT_TAIL.reset(_s3_tok)                                           # [s3-split]\n        _floor_drop(_owned)\n', 1),
    ('split-point',
     '    # Remembered only now: a seed marked heard before the busy-drop above\n    # retired lines that never aired.\n    if seed:\n        speakbox_remember(seed)\n',
     '    # Remembered only now: a seed marked heard before the busy-drop above\n    # retired lines that never aired.\n    if seed:\n        speakbox_remember(seed)\n    # [s3-split] THE SPLIT NODE, at the one door every single line passes: the\n    # words are final, the box is not holding the line back (a held line is\n    # replayed whole) and nothing is rendered yet. A long read on a node whose\n    # splits box is ticked is shared out here - this call speaks the first part,\n    # dj_speak the rest, straight after it, each in its reader\'s own voice.\n    _s3_hold_sting = bool(_S3_SPLIT_HOLD.get())\n    _s3_box = _S3_SPLIT_TAIL.get()\n    if (isinstance(_s3_box, dict) and not _s3_box.get("claimed") and clip is None and not by_hand\n            and _s3_box.get("task") is asyncio.current_task() and isinstance(system3, dict)):\n        _s3_box["claimed"] = True\n        _s3_split = await _s3_split_line(kind, spoken, who, forced, system3, _s3_spoken_handle)\n        if _s3_split:\n            spoken, system3 = _s3_split[0], _s3_split[1]\n            _s3_box["parts"] = list(_s3_split[2])\n            _s3_hold_sting = True                   # the SFX cadence welds after the last part\n            _s3_line_remember(line_id, system3, who, spoken)   # part 1: its own stamp, its own words\n', 1),
    ('split-cadence-hold',
     '    if clip and _sfx_single_cadence_wanted(sting, by_hand, kind):\n',
     '    if clip and _sfx_single_cadence_wanted(sting, by_hand, kind) and not _s3_hold_sting:   # [s3-split] not mid-read\n', 1),
    ('split-part-not-a-repeat',
     '    if not by_hand and kind != "station_id":\n',
     '    if not by_hand and kind != "station_id" and not (system3 or {}).get("split"):   # [s3-split] a part of a read checked whole\n', 1),
    ('upstairs-write-split',
     '    if seed:\n        speakbox_remember(seed)\n    return row\n',
     '    if _s3l is not None and _s3l.active and isinstance(row, dict) and row.get("id"):   # [s3-split] the page, shared out\n        await _s3_split_page(row, _s3l, text)\n    if seed:\n        speakbox_remember(seed)\n    return row\n', 1),
    ('upstairs-page-reads-on',
     '    pipeline_log("air", "a page from upstairs went out - "\n                        f"{made.get(\'vocode\') or \'vocoded\'} (#749)")\n',
     '    pipeline_log("air", "a page from upstairs went out - "\n                        f"{made.get(\'vocode\') or \'vocoded\'} (#749)")\n    if globals().get("system3_note_pace"):                                    # [s3-split] his pace, for the rule\n        globals()["system3_note_pace"]("manager", len(" ".join(spoken.split())), seconds)\n    # [s3-split] A PAGE THE SPLIT NODE SHARED OUT: his recording carried the first\n    # part; a booth voice picks the rest up and reads it on, in order, before the\n    # pair react to the whole of it\n    _page_split = made.get("split") if isinstance(made.get("split"), dict) else {}\n    if _page_split.get("parts"):\n        try:\n            await _s3_split_speak("interject", _RADIO.get("now"), list(_page_split["parts"]),\n                                  round_as="manager", sting=False)\n        except Exception as _exc:  # noqa: BLE001\n            pipeline_log("drop", "[s3-split] the rest of a split page could not be read on",\n                         extra=("%s: %s" % (type(_exc).__name__, _exc))[:200])\n        spoken = str(_page_split.get("whole") or spoken)\n', 1),
    ('upstairs-update-keeps',
     '                if key in ("text", "gripe", "context", "voice", "vocode",\n                           "audio"):\n                    row[key] = str(value)[:2000]\n                elif key in ("uses", "last"):\n                    row[key] = int(value)\n',
     '                if key in ("text", "gripe", "context", "voice", "vocode",\n                           "audio"):\n                    row[key] = str(value) if key == "text" else str(value)[:2000]   # [s3-split] a page\'s words whole\n                elif key in ("uses", "last"):\n                    row[key] = int(value)\n                elif key in ("system3", "split") and isinstance(value, (dict, list)):   # [s3-split] its node, its parts\n                    row[key] = copy.deepcopy(value)\n', 1),
    ('upstairs-save-whole',
     '                 "text": str(text)[:2000], "gripe": str(gripe)[:200],\n',
     '                 "text": str(text), "gripe": str(gripe)[:200],               # [s3-split] a page\'s words whole\n', 1),
    ('ledger-text-whole',
     '            "text": str(row.get("text") or "")[:2000],\n',
     '            "text": str(row.get("text") or ""),                              # [s3-split] whole: a 2,000 cap cut station IDs mid-word\n', 1),
    ('ad-save-whole',
     '            "text": text[:1200],\n',
     '            "text": text,                                                    # [s3-split] whole: a rerun reads these words aloud\n', 1),
    ('ad-update-whole',
     '                    if key in ("product", "text", "kind", "audio", "voice",\n                               "bed", "seed_file", "seed_text", "seed_mind"):\n                        row[key] = str(value)[:1200]\n',
     '                    if key in ("product", "text", "kind", "audio", "voice",\n                               "bed", "seed_file", "seed_text", "seed_mind"):\n                        row[key] = str(value) if key == "text" else str(value)[:1200]   # [s3-split] a read\'s words whole\n', 1),
    ('gold-take-helpers',
     'def _gold_rows() -> list[dict[str, Any]]:\n',
     'def _gold_take_holds(item: dict[str, Any]) -> bool:\n    """[s3-split] Whether one chunk\'s take holds its whole turn. The air notes a\n    gold bar on a turn\'s LAST chunk, under the whole turn\'s words - so a turn\n    the render cut into pieces was banked as its tail\'s audio under all of its\n    words, and fired later as a fragment (measured 2026-09-28: 162 characters\n    in a 2.4 s take, aired five times). Only a take that holds the turn is a bar."""\n    turn = _gold_norm(item.get("turn_text") or "").split()\n    if not turn:\n        return True\n    chunk = set(_gold_norm(item.get("chunk") or "").split())\n    return sum(1 for w in turn if w in chunk) >= 0.9 * len(turn)\n\n\ndef _gold_take_fits(row: dict[str, Any]) -> bool:\n    """[s3-split] A banked bar whose take is far too short for its words (over 40\n    characters a second; speech measured on air runs 13 to 36) is a turn\'s tail\n    filed under the whole turn."""\n    try:\n        secs = float(row.get("seconds") or 0)\n    except (TypeError, ValueError):\n        return True\n    return secs <= 0 or len(" ".join(str(row.get("text") or "").split())) <= 40 * secs + 10\n\n\ndef _gold_rows() -> list[dict[str, Any]]:\n', 1),
    ('gold-rows-fit',
     '            rows = [r for r in got if isinstance(r, dict)] if isinstance(got, list) else []\n',
     '            rows = [r for r in got if isinstance(r, dict)] if isinstance(got, list) else []\n            for _r in rows:                                     # [s3-split] a take that cannot hold its words\n                if _r.get("path") and not _gold_take_fits(_r):\n                    _r["path"] = ""                             # the take goes, the line stays (as gold_trim)\n', 1),
    ('gold-note-whole-turn',
     '                    if ready_takes is None and item.get("turn_end") and item["who"] in ("dj", "cohost", "third"):\n',
     '                    if (ready_takes is None and item.get("turn_end") and item["who"] in ("dj", "cohost", "third")\n                            and _gold_take_holds(item)):                   # [s3-split] a take that holds its turn\n', 1),
    ('page-cut-panel',
     '      if (djVoiceNow && cutIds.indexOf(String(djVoiceNow.row_id || "")) >= 0) {\n        djVoiceEpoch += 1;\n        (djVoiceEls || []).forEach((a) => {\n          if (a && a.src) {\n            try { a.pause(); a.removeAttribute("src"); a.load(); } catch (e) {}\n          }\n        });\n        djVoiceBusy = false;\n        djVoiceLive = 0;\n        djVoiceNow = null;\n        djStreamNow = null;\n        djStreamLiveId = "";\n        djSpeaking = false;\n        djApplyGain();\n        djTalkMarkLive();\n        setTimeout(djVoiceNext, 50);\n      }\n',
     '      /* [s3-split] the clip already SOUNDING plays to its end: "Don\'t want any\n       * messages getting cut off when they\'re being spoken on the air" (the\n       * operator, 2026-09-28). Only the clips still queued behind it go with\n       * their record. */\n', 1),
    ('page-cut-radio',
     '      if (voiceNowTs && voiceCurrentClip\n          && cutIds.indexOf(String(voiceCurrentClip.row_id || "")) >= 0) {\n        voiceAck(voiceCurrentClip, "error", "cut with its record (#1237)");\n        voiceEpoch += 1;\n        try { voice.pause(); voice.removeAttribute("src"); voice.load(); } catch (e) {}\n        voiceBusy = false;\n        voiceNowTs = 0;\n        if (ducking) { ducking = false; applyLevels(); }\n        voiceNext();\n      }\n',
     '      /* [s3-split] a clip already sounding plays to its end - a message is\n       * never cut off while it is spoken; the queued ones go with their record */\n', 1),
]


def plan(text):
    """Every edit, in order."""
    return list(EDITS)


def marker_of(old, new):
    """The edit's own line: the first line of `new` that is not in `old` and
    carries the [s3-split] tag - an insert whose anchor another patch has since
    built on is still known as applied."""
    olds = set(old.splitlines())
    lines = [ln for ln in new.splitlines() if ln.strip() and ln not in olds]
    tagged = [ln for ln in lines if "[s3-split]" in ln]
    return (tagged or lines or [new])[0]


def state_of(text, old, new, count):
    n_new = text.count(new)
    n_old = text.count(old)
    if n_new >= 1 and n_old == new.count(old) * n_new:
        return "applied"
    if n_new == 0 and text.count(marker_of(old, new)) == 1:
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
    compile(text, str(path), "exec")
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
