#!/usr/bin/env python3
"""[h3-speak] app.py: the hourly H3 video's dialogue is the H3SPEAK node - what people were heard
saying on air (else a Speakerbox document, else FORCED), rolled by System 3; {station} and every
slot filled; the last gate refuses a prompt holding {...} or glued titles. 10 edits."""

# ---- the patch contract (marker-idempotent) --------------------------------
# --check PATH  exit 0 ready (every edit ready or applied, at least one ready),
#               2 applied (every edit applied), 1 missing (an anchor is gone).
# --apply PATH  applies the ready edits in order, writes LF atomically; exit 0
#               on success, 2 when there was nothing to do, 1 when missing.
# An edit is APPLIED when its marker (a line only its inserted text has) is in
# the file, READY when its anchor occurs exactly once, else MISSING.
import os
import sys
import tempfile


def state_of(text, edit):
    if edit["marker"] in text:
        return "applied"
    n = text.count(edit["anchor"])
    return "ready" if n == 1 else ("missing (anchor x%d)" % n)


def apply_one(text, edit):
    if edit["kind"] == "replace":
        return text.replace(edit["anchor"], edit["text"], 1)
    if edit["kind"] == "before":
        return text.replace(edit["anchor"], edit["text"] + edit["anchor"], 1)
    if edit["kind"] == "after":
        return text.replace(edit["anchor"], edit["anchor"] + edit["text"], 1)
    raise ValueError(edit["kind"])


def run(edits, argv):
    if len(argv) != 3 or argv[1] not in ("--check", "--apply"):
        print("usage: %s --check|--apply PATH" % argv[0])
        return 1
    mode, path = argv[1], argv[2]
    with open(path, "r", encoding="utf-8", newline="") as fh:
        text = fh.read()
    text = text.replace("\r\n", "\n")
    states = []
    work = text
    for e in edits:                     # sequential: a later anchor may sit in an earlier edit's text
        st = state_of(work, e)
        states.append(st)
        print("  %-10s %s" % (st.split(" ")[0], e["name"]) + ("" if st in ("ready", "applied") else "  <- " + st))
        if st == "ready":
            work = apply_one(work, e)
    if any(s not in ("ready", "applied") for s in states):
        print("MISSING: %d of %d edits" % (sum(1 for s in states if s not in ("ready", "applied")), len(edits)))
        return 1
    if all(s == "applied" for s in states):
        print("APPLIED: all %d edits" % len(edits))
        return 2
    if mode == "--check":
        print("READY: %d to apply, %d applied" % (states.count("ready"), states.count("applied")))
        return 0
    for e in edits:
        if e["marker"] not in work:
            print("apply failed: %s did not land" % e["name"])
            return 1
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".h3speak.")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(work)
    try:
        os.chmod(tmp, os.stat(path).st_mode & 0o7777)
    except OSError:
        pass
    os.replace(tmp, path)
    print("applied %d edits -> %s" % (states.count("ready"), path))
    return 0


EDITS = [{'anchor': 'import comfy_workshop\n',
  'kind': 'after',
  'marker': 'import h3_speak                          # [h3-speak]',
  'name': 'import h3_speak',
  'text': "import h3_speak                          # [h3-speak] the hourly video's dialogue: whole "
          'sentences, rolled\n'},
 {'anchor': '# --- [h3-prompts] THE HOURLY PROMPTS: PRESETS THE OPERATOR SAVES, CYCLES, ROLLS --\n',
  'kind': 'before',
  'marker': "# --- [h3-speak] THE HOURLY VIDEO'S DIALOGUE: WHAT PEOPLE SAID ON AIR, ROLLED ---",
  'name': 'the H3SPEAK node (gather / take / gate)',
  'text': "# --- [h3-speak] THE HOURLY VIDEO'S DIALOGUE: WHAT PEOPLE SAID ON AIR, ROLLED ---\n"
          '#\n'
          '# "these are being added onto my prompts and they dont make sense as\n'
          '#  sentences. They have the people saying weird stuff ... Do a roulette RNG\n'
          '#  node for H3 output" ... "I wanted it to be a roulette, R N G roll of\n'
          '#  something that one of the people said on the station. Maybe emotionally on\n'
          '#  the station or a monologue" (operator, 2026-09-29).\n'
          '#\n'
          "# The hour's {conversation} was the last three rows of the chat ring - board\n"
          '# clip titles, "Song analysis complete: ..." rows, a Japanese song title -\n'
          '# glued together, and H3 made the people on screen say it. It is now the\n'
          "# H3SPEAK node, every piece a System 3 roll, recorded on the hour's rolls:\n"
          '#   the pool     what a person (host, co-host, third seat, caller, guest, the\n'
          '#                manager) was HEARD saying - this hour first, widening to two\n'
          "#                days - as lines and monologues (one speaker's run of turns);\n"
          '#   h3.speak_lean      which kind to take: a monologue, an emotional line, any\n'
          '#                      line (POOLS1 - the desk re-weights or retires a kind);\n'
          '#   h3.speak_line      which line or monologue, leaned on by the feeling System 3\n'
          '#                      rolled for it (its ES intensity) or its length;\n'
          '#   h3.speak_count     how many whole sentences (POOLS1: 1, 2, 3), stepped down\n'
          "#                      until a run of them fits the clip's seconds;\n"
          '#   h3.speak_sentences which run, when more than one fits.\n'
          '# No aired line passes: Speakerbox rolls a document (h3.speak_doc) and the\n'
          '# same count and sentence dice run over it. Nothing passes: the named FORCED\n'
          "# node - the preset's own line, else a line off POOLS1 h3.speak_forced.\n"
          "# Every sentence obeys h3_speak.sentence_why and goes through the station's\n"
          "# speakable normalizer; the rolled line is the render's spoken copy and the\n"
          "# brief's {conversation}. {station} and {hour} are filled everywhere; a slot\n"
          '# no road fills is dropped and logged, and h3_speak_gate refuses anything\n'
          '# that still holds "{...}" or the old glued titles, at the last door.\n'
          "H3_SPEAK_SECONDS = H3_HOURLY_WINDOW_S          # one render: the clip road's window\n"
          'H3_SPEAK_WHO = ("dj", "cohost", "third", "caller", "guest", "manager")\n'
          'H3_SPEAK_SKIP_KINDS = frozenset({"emergency_host", "station_id", "marker", "sfx", "drop", '
          '"chat",\n'
          '                                 "image_analysis", "song_analysis", "hangup"})   # stock copy and '
          'paperwork\n'
          'H3_SPEAK_WINDOWS = (3600.0, 3 * 3600.0, 12 * 3600.0, 48 * 3600.0)   # the air log keeps two days\n'
          'H3_SPEAK_MIN_POOL = 6\n'
          "H3_SPEAK_ES_ROUNDS = 60                        # System 3 rounds read for the lines' feelings\n"
          'H3_SPEAK_DOC_TRIES = 3\n'
          'H3_SPEAK_LEANS = ["a monologue", "an emotional line", "any line"]\n'
          'H3_SPEAK_COUNTS = ["1", "2", "3"]\n'
          'H3_SPEAK_FORCED = ["You are listening to {station}, and we are glad you are here.",\n'
          '                   "Stay with us, because this is {station}.",\n'
          '                   "Tune in tonight and every night to {station}."]\n'
          'H3_SPEAK_LEAN_LABEL = "what kind of aired talk the hourly H3 video\'s people say (a monologue, an '
          'emotional line, any line)"\n'
          'H3_SPEAK_LINE_LABEL = "which line or monologue said on air the hourly H3 video\'s people say"\n'
          'H3_SPEAK_DOC_LABEL = "which Speakerbox document the hourly H3 video\'s dialogue comes from (no '
          'aired line passed)"\n'
          'H3_SPEAK_COUNT_LABEL = "how many whole sentences the hourly H3 video\'s people say"\n'
          'H3_SPEAK_SENT_LABEL = "which run of whole sentences the hourly H3 video\'s people say"\n'
          'H3_SPEAK_FORCED_LABEL = "the FORCED line the hourly H3 video\'s people say when no rolled '
          'sentence passes"\n'
          'H3_SPEAK_POOL_FRESH_S = 600.0\n'
          '_H3_SPEAK_POOL: list[Any] = [None]    # the pool the hourly door gathered, for the hour it '
          'resolves next\n'
          '\n'
          '\n'
          'def h3_speak_pool_take() -> Any:\n'
          '    """The pool h3_hourly_render just gathered (async, off the loop), taken\n'
          '    once by the hour it resolves (h3_prompts_hour, sync); None when stale or\n'
          '    already taken - a stale pool never speaks for a later hour."""\n'
          '    pool, _H3_SPEAK_POOL[0] = _H3_SPEAK_POOL[0], None\n'
          '    if isinstance(pool, dict) and time.time() - float(pool.get("at") or 0) <= '
          'H3_SPEAK_POOL_FRESH_S:\n'
          '        return pool\n'
          '    return None\n'
          '\n'
          '\n'
          'def h3_speak_station() -> str:\n'
          '    try:\n'
          '        name = str(dj_settings().get("station_name") or "").strip()\n'
          '    except Exception:  # noqa: BLE001\n'
          '        name = ""\n'
          '    return name or "Pine Box FM"\n'
          '\n'
          '\n'
          'def h3_speak_normalize(text: Any) -> str:\n'
          '    """The station\'s speakable normalizer ([es-near]): markup resolved, action\n'
          '    parentheses dropped, plain ASCII, a sentence end - capitalised."""\n'
          '    try:\n'
          '        said = _es_voice.speakable(str(text or ""), "h3", _xtts_sanitize)\n'
          '    except Exception:  # noqa: BLE001\n'
          '        said = _xtts_sanitize(str(text or ""))\n'
          '    return h3_speak.first_upper(said)\n'
          '\n'
          '\n'
          'def h3_speak_fill(template: Any, quiet: bool = False, **values: Any) -> str:\n'
          '    """h3_prompts_fill, with {station} and {hour} always known; a {slot} no\n'
          '    road fills is taken out (and logged) - never sent as written."""\n'
          '    values.setdefault("station", h3_speak_station())\n'
          '    values.setdefault("hour", time.strftime("%H:%M"))\n'
          '    out, left = h3_speak.clean_placeholders(h3_prompts_fill(template, **values))\n'
          '    # a filled sentence\'s own stop meets the template\'s ("{goal}. Keep"): one stop, an ellipsis '
          'kept\n'
          '    out = re.sub(r"(?<!\\.)([.!?])\\.(?!\\.)(?=\\s|$)", r"\\1", out)\n'
          '    if left and not quiet:\n'
          '        pipeline_log("ads", "hourly H3 prompts: %s filled by no road - taken out" % ", '
          '".join(left)[:160])\n'
          '    return out\n'
          '\n'
          '\n'
          'def _h3_speak_own_reserve(seconds: float) -> int:\n'
          '    """The longest own line a saved preset (or the pinned one) says: the room\n'
          '    the gathered lines leave for it, whichever preset the hour lands on."""\n'
          '    store = _H3_PROMPTS_MEM[0] if isinstance(_H3_PROMPTS_MEM[0], dict) else {}\n'
          '    presets = list(store.get("presets") or [])\n'
          '    pin = store.get("next") if isinstance(store.get("next"), dict) else {}\n'
          '    if isinstance(pin.get("preset"), dict):\n'
          '        presets.append(pin["preset"])\n'
          '    most, whole = 0, h3_speak.word_cap(seconds)\n'
          '    for p in presets:\n'
          '        own = h3_speak_normalize(h3_speak_fill(str((p or {}).get("speech") or ""), quiet=True))\n'
          '        n = len(own.split())\n'
          '        if own and n <= whole and not h3_speak.speech_why(own):\n'
          '            most = max(most, n)\n'
          '    return most\n'
          '\n'
          '\n'
          'def _h3_speak_feelings(items: list[dict[str, Any]]) -> None:\n'
          '    """Each item\'s feeling: the emotion and intensity System 3 rolled for its\n'
          "    lines (the performance on the planned turn), read through the review's\n"
          '    read-only door onto the ledger. The strongest line of a monologue counts.\n'
          '    A worker thread; an unlinked line simply has none."""\n'
          '    ids = [i for it in items for i in it.get("ids") or [] if i]\n'
          '    if not ids:\n'
          '        return\n'
          '    db = _review_s3_db()\n'
          '    if db is None:\n'
          '        return\n'
          '    try:\n'
          '        links: dict[str, tuple[str, str]] = {}\n'
          '        for at in range(0, len(ids), 400):\n'
          '            part = ids[at:at + 400]\n'
          '            for lid, cid, tid in db.execute("SELECT line_id, conversation_id, turn_id FROM lines '
          'WHERE line_id IN (%s)"\n'
          '                                            % ",".join("?" * len(part)), part).fetchall():\n'
          '                links[str(lid)] = (str(cid or ""), str(tid or ""))\n'
          '        cache: dict[str, Any] = {}\n'
          '        budget = {"left": H3_SPEAK_ES_ROUNDS}\n'
          '        for it in items:\n'
          '            best = None\n'
          '            for lid in it.get("ids") or []:\n'
          '                cid, tid = links.get(lid, ("", ""))\n'
          '                if not cid:\n'
          '                    continue\n'
          '                conv = _review_s3_round(db, cid, cache, budget)\n'
          '                if not conv:\n'
          '                    continue\n'
          '                turn = _review_s3_turn(conv, tid, "")\n'
          '                perf = (turn or {}).get("performance") or {}\n'
          '                if perf.get("emotion"):\n'
          '                    try:\n'
          '                        inten = float(perf.get("intensity") or 0.0)\n'
          '                    except (TypeError, ValueError):\n'
          '                        inten = 0.0\n'
          '                    if best is None or inten > best[1]:\n'
          '                        best = (str(perf["emotion"])[:40], round(inten, 3), cid, tid)\n'
          '            if best:\n'
          '                it["emotion"], it["intensity"], it["conversation_id"], it["turn_id"] = best\n'
          '    finally:\n'
          '        try:\n'
          '            db.close()\n'
          '        except Exception:  # noqa: BLE001\n'
          '            pass\n'
          '\n'
          '\n'
          'def _h3_speak_air_pool(cap: int, now: float = 0.0) -> dict[str, Any]:\n'
          '    """What people were heard saying, as the node\'s shelf: this hour first,\n'
          '    widening until the shelf holds enough (two days at most). A worker thread."""\n'
          '    now = now or time.time()\n'
          '    items: list[dict[str, Any]] = []\n'
          '    window, heard = H3_SPEAK_WINDOWS[0], 0\n'
          '    for window in H3_SPEAK_WINDOWS:\n'
          '        rows = [r for r in airlog_rows(now - window, now + 60.0, who=list(H3_SPEAK_WHO))\n'
          '                if (r.get("heard_ack_at") or r.get("aired") in AIRLOG_AIRED)\n'
          '                and str(r.get("kind") or "") not in H3_SPEAK_SKIP_KINDS]\n'
          '        heard = len(rows)\n'
          '        items = h3_speak.air_items(rows, cap)\n'
          '        if len(items) >= H3_SPEAK_MIN_POOL:\n'
          '            break\n'
          '    try:\n'
          '        _h3_speak_feelings(items)\n'
          '    except Exception as exc:  # noqa: BLE001 - a line without its feeling is still a line\n'
          '        pipeline_log("ads", "hourly H3 dialogue: the feelings could not be read (%s)" % '
          'type(exc).__name__)\n'
          '    return {"items": items, "window_s": window, "heard": heard}\n'
          '\n'
          '\n'
          'def _h3_speak_doc_read(path: Path) -> list[tuple[int, str]]:\n'
          '    try:\n'
          '        return h3_speak.candidates(path.read_text(errors="replace"))\n'
          '    except OSError:\n'
          '        return []\n'
          '\n'
          '\n'
          'async def h3_speak_gather(seconds: float = 0.0) -> dict[str, Any]:\n'
          '    """[h3-speak] The pool the hour\'s dialogue is rolled from: what people were\n'
          '    heard saying on air; when none of it is whole sentences, a Speakerbox\n'
          '    document System 3 rolls (h3.speak_doc). The line and sentence dice run\n'
          "    once the hour's preset is known (h3_speak_take). A fault is named on the\n"
          '    pool and the node goes FORCED - the hour\'s render is never lost to it."""\n'
          '    try:\n'
          '        return await _h3_speak_gather(seconds)\n'
          '    except Exception as exc:  # noqa: BLE001\n'
          '        pipeline_log("ads", "hourly H3 dialogue: the pool could not be gathered (%s)" % '
          'type(exc).__name__)\n'
          '        return {"at": time.time(), "seconds": float(seconds or H3_SPEAK_SECONDS), "source": "", '
          '"items": [],\n'
          '                "why": "the pool could not be gathered (%s)" % type(exc).__name__}\n'
          '\n'
          '\n'
          'async def _h3_speak_gather(seconds: float = 0.0) -> dict[str, Any]:\n'
          '    seconds = float(seconds or H3_SPEAK_SECONDS)\n'
          '    cap = h3_speak.word_cap(seconds, _h3_speak_own_reserve(seconds))\n'
          '    got: dict[str, Any] = {"at": time.time(), "seconds": seconds, "cap": cap, "source": "", '
          '"items": [],\n'
          '                           "doc": "", "cands": [], "why": "", "window_s": 0.0, "heard": 0}\n'
          '    try:\n'
          '        air = await asyncio.to_thread(_h3_speak_air_pool, cap)\n'
          '    except Exception as exc:  # noqa: BLE001\n'
          '        air = {"items": [], "why": "the air log could not be read (%s)" % type(exc).__name__}\n'
          '    got.update(window_s=air.get("window_s") or 0.0, heard=int(air.get("heard") or 0))\n'
          '    if air.get("items"):\n'
          '        got.update(source="air", items=air["items"])\n'
          '        return got\n'
          '    got["why"] = air.get("why") or ("nothing a person was heard saying in the last %d hours is '
          'whole sentences"\n'
          '                                    % round(float(got["window_s"] or 0) / 3600))\n'
          '    try:\n'
          '        files = speakbox_files()\n'
          '        weights, uses = mind_weights(""), speakbox_uses("")\n'
          '        shelf = [(p, speakbox_weight(p.name, weights, "", uses)) for p in files]\n'
          '    except Exception:  # noqa: BLE001\n'
          '        shelf = []\n'
          '    shelf = [(p, w) for p, w in shelf if w > 0]\n'
          '    for attempt in range(H3_SPEAK_DOC_TRIES):\n'
          '        if not shelf:\n'
          '            break\n'
          '        k = s3_weighted("h3.speak_doc", [p.name for p, _ in shelf], [float(w) for _, w in shelf], '
          'H3_SPEAK_DOC_LABEL)\n'
          '        k = k if isinstance(k, int) and 0 <= k < len(shelf) else 0\n'
          '        h3_hourly_roll_note("speak_doc", "h3.speak_doc")\n'
          '        path = shelf.pop(k)[0]\n'
          '        cands = await asyncio.to_thread(_h3_speak_doc_read, path)\n'
          '        if h3_speak.runs(cands, 1, cap):\n'
          '            got.update(source="speakerbox", doc=path.name, cands=cands, doc_tries=attempt + 1)\n'
          '            return got\n'
          '    got["why"] += "; and no Speakerbox document rolled had a whole sentence that fits"\n'
          '    return got\n'
          '\n'
          '\n'
          'def _h3_speak_sentences(cands: list[tuple[int, str]], cap: int) -> tuple[list[str], int, int]:\n'
          '    """The count die, then the run die: (sentences, count rolled, count taken)."""\n'
          '    try:\n'
          '        want = int(s3_choice("h3.speak_count", H3_SPEAK_COUNTS, H3_SPEAK_COUNT_LABEL))\n'
          '    except (TypeError, ValueError, IndexError):\n'
          '        want = 1\n'
          '    want = max(1, min(max(h3_speak.COUNTS), want))\n'
          '    h3_hourly_roll_note("speak_count", "h3.speak_count")\n'
          '    for n in range(want, 0, -1):\n'
          '        opts = h3_speak.runs(cands, n, cap)\n'
          '        if not opts:\n'
          '            continue\n'
          '        k = 0\n'
          '        if len(opts) > 1:\n'
          '            k = s3_weighted("h3.speak_sentences", [" ".join(o)[:80] for o in opts], [1.0] * '
          'len(opts),\n'
          '                            H3_SPEAK_SENT_LABEL)\n'
          '            k = k if isinstance(k, int) and 0 <= k < len(opts) else 0\n'
          '            h3_hourly_roll_note("speak_sentences", "h3.speak_sentences")\n'
          '        said = [h3_speak_normalize(s) for s in opts[k]]\n'
          '        if all(not h3_speak.sentence_why(s) for s in said) and sum(len(s.split()) for s in said) '
          '<= cap:\n'
          '            return said, want, n\n'
          '        return [], want, 0\n'
          '    return [], want, 0\n'
          '\n'
          '\n'
          'def h3_speak_take(pool: Any, preset_line: str = "") -> dict[str, Any]:\n'
          '    """[h3-speak] The H3SPEAK node for one hour, once its preset is known: the\n'
          "    rolls over the pool, the spoken line (the preset's own line first, then\n"
          '    the sentences) and the {conversation} they fill - else FORCED. On the\n'
          '    event loop: dice and a few sentences, no reads. A fault goes FORCED with\n'
          '    its name on the record."""\n'
          '    try:\n'
          '        return _h3_speak_take(pool, preset_line)\n'
          '    except Exception as exc:  # noqa: BLE001\n'
          '        why = "the node faulted (%s)" % type(exc).__name__\n'
          '        pipeline_log("ads", "hourly H3 dialogue: FORCED - " + why)\n'
          '        own = h3_speak_normalize(h3_speak_fill(preset_line, quiet=True)) if str(preset_line or '
          '"").strip() else ""\n'
          '        line = own if own and not h3_speak.speech_why(own) else h3_speak_normalize("This is %s." '
          '% h3_speak_station())\n'
          '        return {"node": "H3SPEAK", "verdict": "forced", "source": "forced", "line": line, '
          '"conversation": line,\n'
          '                "sentences": [], "why": why, "forced_by": "the fault road (no dice)",\n'
          '                "origin": {"node": "H3SPEAK", "road": "h3_hourly", "verdict": "forced", "source": '
          '"forced",\n'
          '                           "forced_by": "the fault road (no dice)"}}\n'
          '\n'
          '\n'
          'def _h3_speak_take(pool: Any, preset_line: str = "") -> dict[str, Any]:\n'
          '    pool = pool if isinstance(pool, dict) else {}\n'
          '    seconds = float(pool.get("seconds") or H3_SPEAK_SECONDS)\n'
          '    own = h3_speak_normalize(h3_speak_fill(preset_line, quiet=True)) if str(preset_line or '
          '"").strip() else ""\n'
          '    own_ok = bool(own) and not h3_speak.speech_why(own) and len(own.split()) <= '
          'h3_speak.word_cap(seconds)\n'
          '    cap = h3_speak.word_cap(seconds, len(own.split()) if own_ok else 0)\n'
          '    said: list[str] = []\n'
          '    want = took = 0\n'
          '    item: dict[str, Any] | None = None\n'
          '    lean, why = "", str(pool.get("why") or "")\n'
          '    source = str(pool.get("source") or "")\n'
          '    if source == "air":\n'
          '        shelf = [it for it in pool.get("items") or [] if h3_speak.runs(it.get("cands") or [], 1, '
          'cap)]\n'
          '        if shelf:\n'
          '            leans = [x for x in s3_pool("h3.speak_lean", H3_SPEAK_LEANS, H3_SPEAK_LEAN_LABEL) if '
          'x in H3_SPEAK_LEANS]\n'
          '            leans = leans or list(H3_SPEAK_LEANS)\n'
          '            lean = leans[_S3Dice("h3.speak_lean", H3_SPEAK_LEAN_LABEL).pick("h3.speak_lean", '
          'leans)]\n'
          '            h3_hourly_roll_note("speak_lean", "h3.speak_lean")\n'
          '            kind = [it for it in shelf if lean == "any line"\n'
          '                    or (lean == "a monologue" and int(it.get("turns") or 1) >= 2)\n'
          '                    or (lean == "an emotional line" and it.get("emotion"))] or shelf\n'
          '            now = time.time()\n'
          '            labels = ["%s: %s" % (it.get("name") or it.get("who") or "?", " ".join(s for _, s in '
          'it["cands"][:2])[:70])\n'
          '                      for it in kind]\n'
          '            k = s3_weighted("h3.speak_line", labels, [h3_speak.item_weight(it, lean, now) for it '
          'in kind],\n'
          '                            H3_SPEAK_LINE_LABEL)\n'
          '            item = kind[k if isinstance(k, int) and 0 <= k < len(kind) else 0]\n'
          '            h3_hourly_roll_note("speak_line", "h3.speak_line")\n'
          '            said, want, took = _h3_speak_sentences(item["cands"], cap)\n'
          '            if not said:\n'
          '                why = "the rolled line has no run of whole sentences within %d words" % cap\n'
          '        else:\n'
          '            why = "no aired line fits %d words beside the preset\'s own line" % cap\n'
          '    elif source == "speakerbox":\n'
          '        said, want, took = _h3_speak_sentences(pool.get("cands") or [], cap)\n'
          '        if not said:\n'
          '            why = "the rolled document has no run of whole sentences within %d words" % cap\n'
          '    forced_by = ""\n'
          '    if said:\n'
          '        verdict = "rolled"\n'
          '        line = " ".join(([own] if own_ok else []) + said)\n'
          '        conversation = " ".join(said)\n'
          '    else:\n'
          '        verdict = "forced"\n'
          '        if own_ok:\n'
          '            line, forced_by = own, "the preset\'s own line"\n'
          '        else:\n'
          '            opts = [h3_speak_normalize(h3_speak_fill(x, quiet=True))\n'
          '                    for x in s3_pool("h3.speak_forced", H3_SPEAK_FORCED, H3_SPEAK_FORCED_LABEL)]\n'
          '            opts = [x for x in opts if x and not h3_speak.speech_why(x)\n'
          '                    and len(x.split()) <= h3_speak.word_cap(seconds)]\n'
          '            opts = opts or [h3_speak_normalize("This is %s." % h3_speak_station())]\n'
          '            line = opts[_S3Dice("h3.speak_forced", H3_SPEAK_FORCED_LABEL).pick("h3.speak_forced", '
          'opts)]\n'
          '            h3_hourly_roll_note("speak_forced", "h3.speak_forced")\n'
          '            forced_by = "the FORCED table (POOLS1 h3.speak_forced)"\n'
          '        conversation = line\n'
          '        pipeline_log("ads", "hourly H3 dialogue: FORCED - %s (%s)" % (forced_by, why or "nothing '
          'to roll"))\n'
          '    src = ("air" if said and source == "air" else "speakerbox" if said else "forced")\n'
          '    stamp: dict[str, Any] = {"node": "H3SPEAK", "road": "h3_hourly", "verdict": verdict, '
          '"source": src}\n'
          '    if src == "air" and item:\n'
          '        stamp.update(line_ids=list(item.get("ids") or [])[:12], round=item.get("sid") or "",\n'
          '                     conversation_id=item.get("conversation_id") or "", '
          'turn_id=item.get("turn_id") or "")\n'
          '    elif src == "speakerbox":\n'
          '        stamp["doc"] = str(pool.get("doc") or "")\n'
          '    else:\n'
          '        stamp["forced_by"] = forced_by\n'
          '    out = {"node": "H3SPEAK", "verdict": verdict, "source": src, "line": line, "conversation": '
          'conversation,\n'
          '           "sentences": said, "own": own if own_ok else "", "cap_words": cap, "seconds": '
          'seconds,\n'
          '           "count": {"rolled": want, "took": took}, "lean": lean,\n'
          '           "window_s": pool.get("window_s") or 0.0, "why": why if verdict == "forced" else "",\n'
          '           "forced_by": forced_by, "doc": str(pool.get("doc") or "") if src == "speakerbox" else '
          '"",\n'
          '           "origin": stamp}\n'
          '    if src == "air" and item:\n'
          '        out["said"] = {k: item.get(k) for k in ("who", "name", "kind", "round", "sid", "at", '
          '"turns",\n'
          '                                                 "emotion", "intensity") if item.get(k) not in '
          '(None, "")}\n'
          '    pipeline_log("ads", "hourly H3 dialogue (%s, %s): %s" % (verdict, src, line[:160]))\n'
          '    return out\n'
          '\n'
          '\n'
          'def h3_speak_gate(prompt: str, speech: str, payload: dict[str, Any]) -> str:\n'
          '    """[h3-speak] THE LAST GATE before ComfyUI: \'\' to send, else why the prompt\n'
          '    is refused (logged). Every render: no unfilled {placeholder}, no status\n'
          '    row. An hourly render, whose words System 3 rolled: its spoken line is\n'
          '    whole sentences and its conversation carries none of the glued titles."""\n'
          '    hourly = bool(payload.get("hourly"))\n'
          '    rec = payload.get("h3_prompts") if isinstance(payload.get("h3_prompts"), dict) else {}\n'
          '    why = h3_speak.gate(prompt, speech if hourly else "",\n'
          '                        conversation=(rec.get("conversation") if hourly and rec else None), '
          'strict=hourly)\n'
          '    if why:\n'
          '        pipeline_log("ads", "H3 prompt REFUSED at the last gate (%s): %s | %s"\n'
          '                     % ("hourly" if hourly else str(payload.get("purpose") or "render"), why, '
          'str(prompt)[:240]))\n'
          '    return why\n'
          '\n'
          '\n'},
 {'anchor': '    goal = h3_hourly_ad_prompt()\n',
  'kind': 'before',
  'marker': '    _h3_gather = globals().get("h3_speak_gather")',
  'name': 'the hourly door gathers the pool',
  'text': '    _h3_gather = globals().get("h3_speak_gather")                 # [h3-speak] the dialogue\'s '
          'pool:\n'
          "    if _h3_gather:                                                # the hour's preset rolls over "
          'it\n'
          '        _H3_SPEAK_POOL[0] = await _h3_gather()\n'},
 {'anchor': 'def h3_prompts_hour(conversation: str, record: str = "") -> dict[str, Any]:\n',
  'kind': 'replace',
  'marker': 'def h3_prompts_hour(conversation: str, record: str = "", speak: Any = None) -> dict[str, Any]:',
  'name': 'h3_prompts_hour takes the pool',
  'text': 'def h3_prompts_hour(conversation: str, record: str = "", speak: Any = None) -> dict[str, Any]:\n'},
 {'anchor': '    fields = h3_prompts_fields(preset)\n'
            '    goal = (h3_prompts_fill(fields["goal"], conversation=conversation, record=record)\n'
            '            or h3_prompts_fill(H3_PROMPTS_DEFAULT["goal"], conversation=conversation, '
            'record=record))\n',
  'kind': 'replace',
  'marker': '    _take, _fill = globals().get("h3_speak_take"), globals().get("h3_speak_fill") or '
            'h3_prompts_fill',
  'name': "the hour's brief: the node's words, {station} filled",
  'text': '    fields = h3_prompts_fields(preset)\n'
          "    # [h3-speak] the H3SPEAK node rolls the hour's dialogue over the pool: its\n"
          '    # sentences are the {conversation}, its line the words spoken; {station}\n'
          '    # and {hour} are filled and a slot no road fills is taken out\n'
          '    _take, _fill = globals().get("h3_speak_take"), globals().get("h3_speak_fill") or '
          'h3_prompts_fill\n'
          '    if speak is None and globals().get("h3_speak_pool_take"):\n'
          '        speak = h3_speak_pool_take()          # the pool the hourly door just gathered, once\n'
          '    _speak = _take(speak, fields.get("speech") or "") if speak is not None and _take else None\n'
          '    if _speak is not None:\n'
          '        conversation = _speak["conversation"]\n'
          '    goal = (_fill(fields["goal"], conversation=conversation, record=record)\n'
          '            or _fill(H3_PROMPTS_DEFAULT["goal"], conversation=conversation, record=record))\n'},
 {'anchor': '             "goal": goal}\n    _H3_PROMPTS_HOURS.append(entry)\n',
  'kind': 'replace',
  'marker': '             "goal": goal, "speak": _speak}',
  'name': "the hour's record keeps the node",
  'text': '             "goal": goal, "speak": _speak}                   # [h3-speak] the node, its dice and '
          'origin\n'
          '    _H3_PROMPTS_HOURS.append(entry)\n'},
 {'anchor': '    line = h3_prompts_fill(fields["speech"], **values) if fields["speech"] else str(speech or '
            '"")\n',
  'kind': 'replace',
  'marker': '    _speak = hour.get("speak") if isinstance(hour.get("speak"), dict) else None      # '
            '[h3-speak]',
  'name': "a road's line is the node's line",
  'text': '    _speak = hour.get("speak") if isinstance(hour.get("speak"), dict) else None      # '
          '[h3-speak]\n'
          '    _fill = globals().get("h3_speak_fill") or h3_prompts_fill      # {station}, {hour}; a stray '
          'slot out\n'
          '    line = (_speak["line"] if _speak and _speak.get("line")\n'
          '            else _fill(fields["speech"], **values) if fields["speech"] else str(speech or ""))\n'},
 {'anchor': '            "direction": h3_prompts_fill(fields[road], **values)[:1800] or values["goal"],\n',
  'kind': 'replace',
  'marker': '            "speak": _speak,                                                  # [h3-speak]',
  'name': "a road's direction: every slot filled, the node on the record",
  'text': '            "speak": _speak,                                                  # [h3-speak]\n'
          '            "direction": _fill(fields[road], **values)[:1800] or values["goal"],\n'},
 {'anchor': '        purpose=purpose, style=payload.get("style"))                   # [h3-brief] one style '
            'term per road\n',
  'kind': 'after',
  'marker': '    _h3_gate = globals().get("h3_speak_gate")',
  'name': 'the last gate before ComfyUI',
  'text': '    _h3_gate = globals().get("h3_speak_gate")                      # [h3-speak] the last gate\n'
          '    _h3_refused = _h3_gate(final_prompt, speech, payload) if _h3_gate else ""\n'
          '    if _h3_refused:\n'
          '        raise HTTPException(status_code=422, detail="H3 prompt refused: " + _h3_refused)\n'},
 {'anchor': '                except HTTPException as exc:\n'
            '                    # A source can disappear between selection and dispatch.\n',
  'kind': 'replace',
  'marker': '                    if exc.status_code == 422:                     # [h3-speak]',
  'name': 'a refused prompt is never retried',
  'text': '                except HTTPException as exc:\n'
          '                    if exc.status_code == 422:                     # [h3-speak] the last gate '
          'refused its words:\n'
          '                        await asyncio.to_thread(queue.cancel, item["id"], '
          'str(exc.detail)[:480])   # never retried\n'
          '                        return 0, freed_for\n'
          '                    # A source can disappear between selection and dispatch.\n'}]

if __name__ == "__main__":
    sys.exit(run(EDITS, sys.argv))
