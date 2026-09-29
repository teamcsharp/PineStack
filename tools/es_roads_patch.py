"""[es-roads] The emotion engine reaches EVERY seat's take, and the air record
says which feeling shaped each one.

THE CAUSE, PER ROAD. performance_vector(es=...) is the one door through which
an ES roll becomes a take: the vector carries the row's voice block as
vec["es"], voice_generate hands that block to the engine first
(es_voice.engine_opts: XTTS/F5 speed and temperature) and perf_apply does the
rest (tempo, melody, effort, pauses). Only three roads opened it - the
lookahead (#1232), speak_turns' per-turn vector and dj_speak's own line node.
The roads that hold a System 3 STAMP instead of an entry or a handle built the
vector without it, so their takes aired neutral:

  dj_speak with a stamp handed in (a round's chunk on the per-turn road, a
  chapter's replies, a split's later parts, a banked shelf row: manager memo,
  station ID) - it plans a node of its own only when it has none, so a
  stamped line kept performance_vector(who, voice): plain. That vector is also
  what shaped a shelf take on the way out (_es_pantry_perform) and what a
  missed take was rendered live with.
  _s3_split_render - a later part made ahead: performance_vector(who, voice).
  prep_render_line - the single-take shelf road: performance_vector(who,
  voice), though a station ID and the rows the recast desk re-records carry
  their node's stamp.
  speak_turns' raw fallback (#777) - the round's own turns, no ES asked.

THE CURE, THROUGH THE OWNING ROAD. The runtime answers "what does the turn
this stamp names feel like" (system3_perf_of_stamp: the conversation in
memory, else read from the store off the loop; a split part inherits the turn
it was cut from). dj_speak asks it for a stamped line; speak_turns hands
dj_speak the turn vector it already built (perf=), so the take, the shelf
re-perform and a live re-render all speak the same row; _s3_split_render and
prep_render_line are handed the stamp their road already holds. The raw
fallback asks the entry's turn dice like the main road does.

THE STAMP. The ES voice block now names its row (system3.es_row: table,
category, item, label, intensity - through turn_stamp's perf and the line
handle), performance_vector carries it out as vec["es_row"], and every seat's
ring row gets entry["es"] = {road, table, category, item, label, intensity,
voice, baked} or {road, none: why}; screenplay_line_row keeps it as
row["perf"]["es"]. tools/es_coverage.py reads it.

es_probe --dsp gains --levels (the live intensities, beside 1.0 and 0.5).

Targets (relative to the repo root given, default "."): app.py, system3.py,
system3_runtime.py, tools/es_probe.py. --check exits 0 ready / 2 applied /
1 missing. --apply is idempotent and all-or-nothing across the four files,
LF only. ON THE HOST.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

A, S3, RT, PROBE = "app.py", "system3.py", "system3_runtime.py", "tools/es_probe.py"

EDITS = [
    # ---- system3.py: which ES row shaped a turn --------------------------------------------
    (S3, "s3-es-row",
     'def turn_stamp(conv, t):\n'
     '    """What rides a script line: the chain that produced it, compactly."""\n',
     'def es_row(turn):\n'
     '    """[es-roads] Which ES row shaped a turn - table, category, item, label and\n'
     '    the intensity it was rolled at - for the air record. None: no feeling rolled."""\n'
     '    for d in (turn or {}).get("decisions") or []:\n'
     '        if d.get("family") == "ES" and d.get("item"):\n'
     '            return {k: d.get(k) for k in ("table", "category", "item", "label", "intensity")\n'
     '                    if d.get(k) is not None}\n'
     '    return None\n'
     '\n'
     '\n'
     'def turn_stamp(conv, t):\n'
     '    """What rides a script line: the chain that produced it, compactly."""\n', 1),
    (S3, "s3-stamp-row",
     '                     **({"voice": perf["voice"]} if perf.get("voice") is not None else {})},   # [s3-es-voice]\n',
     '                     **({"voice": perf["voice"]} if perf.get("voice") is not None else {}),   # [s3-es-voice]\n'
     '                     **({"row": es_row(t)} if es_row(t) else {})},   # [es-roads] which row, how hard\n', 1),

    # ---- system3_runtime.py: the stamp's feeling ------------------------------------------------
    (RT, "rt-perf-of-stamp",
     '    def perf_voice(self, entry, turns, text, who=""):\n',
     '    def perf_of_stamp(self, stamp, who="", disk=False):\n'
     '        """[es-roads] ES -> the voice for a road that holds a STAMP, not the round\n'
     '        entry or the line handle: the turn it names, as {"dims": the state for\n'
     '        performance_vector(state=), "voice": the ES row\'s voice block with its\n'
     '        "row"}. A split part inherits the turn it was cut from. The conversation\n'
     '        is read from memory; `disk` reads the store when it has aged out (a\n'
     '        banked shelf row) - call that off the event loop. None: no such active\n'
     '        turn, or no feeling on it."""\n'
     '        try:\n'
     '            if not isinstance(stamp, dict) or not stamp.get("conversation_id") or not stamp.get("turn_id"):\n'
     '                return None\n'
     '            cid = str(stamp["conversation_id"])\n'
     '            conv = self.recent.get(cid)\n'
     '            if conv is None and disk:\n'
     '                conv = self.store.conversation(cid, with_events=False)\n'
     '            if not conv or (conv.get("mode") or stamp.get("mode")) != "active":\n'
     '                return None\n'
     '            turns = {str(t.get("turn_id")): t for t in conv.get("turns") or []}\n'
     '            t = turns.get(str(stamp["turn_id"]))\n'
     '            perf = (t or {}).get("performance") or {}\n'
     '            if not perf.get("dims") and not perf.get("voice"):\n'
     '                t = turns.get(str(((stamp.get("split") or {}).get("of_turn")) or (t or {}).get("split_of") or ""))\n'
     '                perf = (t or {}).get("performance") or {}\n'
     '            dims = perf.get("dims") if isinstance(perf.get("dims"), dict) else None\n'
     '            voice = perf.get("voice") if isinstance(perf.get("voice"), dict) else None\n'
     '            if not dims and voice is None:\n'
     '                return None\n'
     '            with self.lock:\n'
     '                self.metrics["stamp_perf"] = int(self.metrics.get("stamp_perf") or 0) + 1\n'
     '            return {"dims": ({d: float(dims.get(d) or 0) for d in system3.EMOTION_DIMS} if dims else None),\n'
     '                    "voice": (dict(voice, row=system3.es_row(t) or {}) if voice is not None else None)}\n'
     '        except Exception as exc:  # noqa: BLE001\n'
     '            self.fail("stamp performance", exc)\n'
     '            return None\n'
     '\n'
     '    def perf_voice(self, entry, turns, text, who=""):\n', 1),
    (RT, "rt-perf-voice-row",
     '                self.metrics["voice_applied"] = int(self.metrics.get("voice_applied") or 0) + 1\n'
     '            return dict(got)\n',
     '                self.metrics["voice_applied"] = int(self.metrics.get("voice_applied") or 0) + 1\n'
     '            # [es-roads] and which ES row it is, for the air record (a stamp from\n'
     '            # before the row rode it names the feeling and its intensity only)\n'
     '            row = (stamp.get("perf") or {}).get("row")\n'
     '            if not isinstance(row, dict):\n'
     '                row = {k: v for k, v in (("label", stamp.get("es")), ("intensity", stamp.get("intensity")))\n'
     '                       if v is not None}\n'
     '            return dict(got, row=dict(row))\n', 1),
    (RT, "rt-handle-row",
     '            handle.voice = (dict(perf["voice"]) if isinstance(perf.get("voice"), dict) and handle.active else None)\n',
     '            handle.voice = (dict(perf["voice"], row=system3.es_row(first) or {})   # [es-roads] and which row\n'
     '                            if isinstance(perf.get("voice"), dict) and handle.active else None)\n', 1),
    (RT, "rt-export",
     '    namespace["system3_perf_voice"] = rt.perf_voice                  # [s3-es-voice]\n',
     '    namespace["system3_perf_voice"] = rt.perf_voice                  # [s3-es-voice]\n'
     '    namespace["system3_perf_of_stamp"] = rt.perf_of_stamp            # [es-roads]\n', 1),

    # ---- app.py: the vector names its row ------------------------------------------------------
    (A, "app-vec-row",
     '    if _es_on:\n'
     '        out["es"] = _es                                     # [s3-es-voice] the engines\' share + the melody\'s middle\n',
     '    if _es_on:\n'
     '        out["es"] = _es                                     # [s3-es-voice] the engines\' share + the melody\'s middle\n'
     '        if isinstance(es.get("row"), dict) and es["row"]:   # [es-roads] which ES row, how hard\n'
     '            out["es_row"] = {k: es["row"][k] for k in ES_ROW_KEYS if es["row"].get(k) is not None}\n', 1),
    # ---- app.py: the helpers, beside the chunk stamp -------------------------------------------
    (A, "app-helpers",
     'async def _s3_split_speak(kind: str, track: dict[str, Any] | None, parts: list[dict[str, Any]],\n',
     '# [es-roads] THE FEELING A STAMP NAMES, AND THE AIR RECORD OF IT. A road that\n'
     '# holds a System 3 stamp (a chapter\'s reply, a split part, a round\'s chunk, a\n'
     '# banked shelf row) asks the runtime what the turn it names feels like, and\n'
     '# builds its vector with it - the one door (performance_vector(es=)) through\n'
     '# which a roll reaches the engine and the DSP. Every seat\'s ring row then says\n'
     '# which row shaped its take, or why none did.\n'
     'ES_ROW_KEYS = ("table", "category", "item", "label", "intensity")\n'
     '\n'
     '\n'
     'async def _s3_stamp_perf(stamp: Any, who: str = "") -> tuple[dict[str, Any] | None, str]:\n'
     '    """[es-roads] ({"dims", "voice"}, "") for the turn a stamp names, or\n'
     '    (None, why not). Memory first; the store (off the loop) for a stamp\n'
     '    whose conversation has aged out of it."""\n'
     '    ask = globals().get("system3_perf_of_stamp")\n'
     '    if not callable(ask):\n'
     '        return None, "System 3 is not loaded"\n'
     '    if not isinstance(stamp, dict) or not stamp.get("conversation_id") or not stamp.get("turn_id"):\n'
     '        return None, "the line has no System 3 turn"\n'
     '    try:\n'
     '        got = ask(stamp, who)\n'
     '        if got is None and stamp.get("mode") == "active":\n'
     '            got = await asyncio.to_thread(ask, stamp, who, True)\n'
     '    except Exception as exc:  # noqa: BLE001\n'
     '        return None, "the turn could not be read (%s)" % type(exc).__name__\n'
     '    if not got:\n'
     '        return None, "its turn is not an active one with a feeling"\n'
     '    return got, ("" if isinstance(got.get("voice"), dict) else "its ES row has no voice")\n'
     '\n'
     '\n'
     'def es_air_stamp(vec: Any, road: str, baked: Any = None, why: str = "") -> dict[str, Any]:\n'
     '    """[es-roads] Which ES row shaped a take, for the air record: the road,\n'
     '    table/category/item/label/intensity, the voice block, and whether the take\n'
     '    audio carries it (None: not known on this road). {"road", "none": why}\n'
     '    when no ES reached it."""\n'
     '    es = vec.get("es") if isinstance(vec, dict) else None\n'
     '    if isinstance(es, dict) and es:\n'
     '        row = vec.get("es_row") if isinstance(vec.get("es_row"), dict) else {}\n'
     '        out: dict[str, Any] = {"road": road, **{k: row[k] for k in ES_ROW_KEYS if row.get(k) is not None},\n'
     '                               "voice": {k: es[k] for k in _es_voice.KEYS if k in es}}\n'
     '        if baked is not None:\n'
     '            out["baked"] = bool(baked)\n'
     '        return out\n'
     '    return {"road": road, "none": str(why or "no ES roll reached this take")[:120]}\n'
     '\n'
     '\n'
     'async def _s3_split_speak(kind: str, track: dict[str, Any] | None, parts: list[dict[str, Any]],\n', 1),
    # ---- app.py: _s3_split_render gets its part's stamp ------------------------------------------
    (A, "app-split-sig",
     'async def _s3_split_render(text: str, who: str, voice: str) -> dict[str, Any] | None:\n',
     'async def _s3_split_render(text: str, who: str, voice: str,\n'
     '                           stamp: Any = None) -> dict[str, Any] | None:   # [es-roads] the part\'s node\n', 1),
    (A, "app-split-vec",
     '        fx = dict(voice_effect_pick() or {})\n'
     '        vec = performance_vector(who, voice or "")\n',
     '        fx = dict(voice_effect_pick() or {})\n'
     '        _es_got = (await _s3_stamp_perf(stamp, who))[0]      # [es-roads] the part\'s own feeling\n'
     '        vec = performance_vector(who, voice or "", state=(_es_got or {}).get("dims"),\n'
     '                                 es=(_es_got or {}).get("voice"))\n', 1),
    (A, "app-split-call",
     'clip=await _s3_split_render(words, pwho, pvoice),\n',
     'clip=await _s3_split_render(words, pwho, pvoice, stamp=p.get("stamp")),   # [es-roads]\n', 1),
    # ---- app.py: dj_speak takes the turn's vector, or asks its stamp ------------------------------
    (A, "app-speak-sig",
     '                   round_as: str = "", sid: str = "",\n'
     '                   bound: dict[str, Any] | None = None,   # [#1237]\n',
     '                   round_as: str = "", sid: str = "",\n'
     '                   perf: dict[str, Any] | None = None,     # [es-roads] the turn\'s own vector\n'
     '                   bound: dict[str, Any] | None = None,   # [#1237]\n', 2),
    (A, "app-speak-pass",
     '            checked=checked, remember_text=remember_text, round_as=round_as,\n',
     '            checked=checked, remember_text=remember_text, round_as=round_as,\n'
     '            perf=perf,                                  # [es-roads]\n', 1),
    (A, "app-speak-vec",
     '    if _s3_perf or isinstance(_s3_voice, dict):\n'
     '        vec = performance_vector(who, voice or "", state=_s3_perf,\n'
     '                                 es=_s3_voice if isinstance(_s3_voice, dict) else None)\n',
     '    if _s3_perf or isinstance(_s3_voice, dict):\n'
     '        vec = performance_vector(who, voice or "", state=_s3_perf,\n'
     '                                 es=_s3_voice if isinstance(_s3_voice, dict) else None)\n'
     '    _es_road, _es_why = "dj_speak/line", ""                   # [es-roads] which road shaped it\n'
     '    if _s3_perf or isinstance(_s3_voice, dict):\n'
     '        _es_why = "" if isinstance(_s3_voice, dict) else "the line\'s ES row has no voice"\n'
     '    elif _s3_spoken_handle is not None:\n'
     '        _es_why = "the line\'s node rolled no feeling"\n'
     '    elif isinstance(perf, dict) and perf:\n'
     '        # [es-roads] the road that made the turn hands its vector in (speak_turns):\n'
     '        # the take was cut with it, a shelf re-perform and a live re-render use it\n'
     '        vec, _es_road = perf, "speak_turns/turn"\n'
     '        _es_why = "" if perf.get("es") else "the round\'s turn carried no ES voice"\n'
     '    else:\n'
     '        # [es-roads] a stamped line (a chapter\'s reply, a split part, a banked shelf\n'
     '        # row, a chunk without its vector): the turn the stamp names\n'
     '        _es_road = "dj_speak/stamp"\n'
     '        _es_got, _es_why = await _s3_stamp_perf(system3, who)\n'
     '        if _es_got:\n'
     '            vec = performance_vector(who, voice or "", state=_es_got.get("dims"),\n'
     '                                     es=_es_got.get("voice"))\n', 1),
    (A, "app-speak-baked",
     '    # The station-wide cadence slider owns autonomous speech even when the\n',
     '    _es_take = bool(clip.get("es")) if isinstance(clip, dict) else None   # [es-roads] the take carries it\n'
     '    # The station-wide cadence slider owns autonomous speech even when the\n', 1),
    (A, "app-speak-entry",
     '        entry["fx"] = {k: str(v) for k, v in fx.items() if k != "perf"}\n',
     '        entry["fx"] = {k: str(v) for k, v in fx.items() if k != "perf"}\n'
     '    if who in ("dj", "cohost", "caller", "caller2", "third"):   # [es-roads] which feeling shaped the take\n'
     '        entry["es"] = es_air_stamp(vec, _es_road, baked=_es_take, why=_es_why)\n', 1),
    # ---- app.py: speak_turns hands its turn vector to dj_speak ------------------------------------
    (A, "app-turns-perf",
     '            source_text=source_text,\n'
     '            clip=ready,\n',
     '            source_text=source_text,\n'
     '            perf=item.get("vec") or None,    # [es-roads] the turn\'s vector: its take\'s feeling\n'
     '            clip=ready,\n', 1),
    # ---- app.py: speak_turns' raw fallback asks the turn dice too ---------------------------------
    (A, "app-turns-raw",
     '            vec = performance_vector(\n'
     '                who, (caller_voice if who == caller_seat  # #1164\n'
     '                      else caller2_voice if who == "caller2"\n'
     '                      else voices.get(who)) or "")\n'
     '            playlist.append({\n',
     '            vec = performance_vector(\n'
     '                who, (caller_voice if who == caller_seat  # #1164\n'
     '                      else caller2_voice if who == "caller2"\n'
     '                      else voices.get(who)) or "",\n'
     '                state=(globals()["system3_perf_state"](ready_meta, turns, text, who)   # [es-roads]\n'
     '                       if _s3_active() and globals().get("system3_perf_state") else None),\n'
     '                es=(globals()["system3_perf_voice"](ready_meta, turns, text, who)\n'
     '                    if _s3_active() and globals().get("system3_perf_voice") else None))\n'
     '            playlist.append({\n', 1),
    # ---- app.py: the coalesced road's rows say it too ---------------------------------------------
    (A, "app-render-baked",
     '                        "fallback": str(clip.get("fallback") or ""),\n'
     '                    }\n',
     '                        "fallback": str(clip.get("fallback") or ""),\n'
     '                        "es_baked": bool(clip.get("es")),     # [es-roads]\n'
     '                    }\n', 1),
    (A, "app-coalesced-es",
     '                        # #782: the dossier, on the coalesced road too —\n',
     '                        **({"es": es_air_stamp(                  # [es-roads] which feeling shaped it\n'
     '                            aired_items[_ti].get("vec"), "speak_turns/coalesced",\n'
     '                            baked=(aired_items[_ti].get("render") or {}).get("es_baked"),\n'
     '                            why="the round\'s turn carried no ES voice")}\n'
     '                           if 0 <= _ti < len(aired_items) and who in ("dj", "cohost", "caller", "caller2", "third")\n'
     '                           else {}),\n'
     '                        # #782: the dossier, on the coalesced road too —\n', 1),
    # ---- app.py: the single-take shelf road takes its row's stamp --------------------------------
    (A, "app-prep-sig",
     'async def prep_render_line(text: str, who: str,\n'
     '                           voice: str = "",\n'
     '                           kind: str = "") -> dict[str, Any] | None:\n',
     'async def prep_render_line(text: str, who: str,\n'
     '                           voice: str = "",\n'
     '                           kind: str = "",\n'
     '                           stamp: dict[str, Any] | None = None) -> dict[str, Any] | None:   # [es-roads]\n', 1),
    (A, "app-prep-vec",
     '    fx = dict(voice_effect_pick())\n'
     '    vec = performance_vector(who, voice)\n'
     '    if vec:\n'
     '        fx["perf"] = vec\n'
     '    if who in ("dj", "cohost", "caller", "third"):\n',
     '    fx = dict(voice_effect_pick())\n'
     '    # [es-roads] a shelf row that already has its node is recorded with its\n'
     '    # feeling; one without (an ad, a track talk) gets it at air (the re-perform)\n'
     '    _es_got = (await _s3_stamp_perf(stamp, who))[0]\n'
     '    vec = performance_vector(who, voice, state=(_es_got or {}).get("dims"),\n'
     '                             es=(_es_got or {}).get("voice"))\n'
     '    if vec:\n'
     '        fx["perf"] = vec\n'
     '    if who in ("dj", "cohost", "caller", "third"):\n', 1),
    (A, "app-prep-id",
     '    made = await prep_render_line(text, "drop", drop_voice,\n'
     '                                  kind="station_id")       # #978\n',
     '    made = await prep_render_line(text, "drop", drop_voice,\n'
     '                                  kind="station_id",       # #978\n'
     '                                  stamp=_row.get("system3"))   # [es-roads]\n', 1),
    (A, "app-prep-shelf",
     '            made = await prep_render_line(text, who,\n'
     '                                          str(row.get("voice") or ""),\n'
     '                                          kind=str(kind))\n',
     '            made = await prep_render_line(text, who,\n'
     '                                          str(row.get("voice") or ""),\n'
     '                                          kind=str(kind),\n'
     '                                          stamp=row.get("system3"))   # [es-roads]\n', 1),
    (A, "app-prep-recast",
     '                    made = await prep_render_line(\n'
     '                        str(row.get("text") or ""), str(item.get("who") or ""),\n'
     '                        str(item.get("voice") or ""), kind=kind)\n',
     '                    made = await prep_render_line(\n'
     '                        str(row.get("text") or ""), str(item.get("who") or ""),\n'
     '                        str(item.get("voice") or ""), kind=kind,\n'
     '                        stamp=row.get("system3"))   # [es-roads]\n', 1),
    # ---- app.py: the air record keeps it ----------------------------------------------------------
    (A, "app-screenplay-es",
     '                           if k in ("pace", "energy", "pitch_var", "filler")}\n'
     '        except Exception:  # noqa: BLE001\n'
     '            pass\n'
     '    return row\n',
     '                           if k in ("pace", "energy", "pitch_var", "filler")}\n'
     '        except Exception:  # noqa: BLE001\n'
     '            pass\n'
     '    if isinstance(entry.get("es"), dict):          # [es-roads] which ES row shaped the take\n'
     '        row.setdefault("perf", {})["es"] = dict(entry["es"])\n'
     '    return row\n', 1),

    # ---- tools/es_probe.py: the live intensities ----------------------------------------------
    (PROBE, "probe-levels-def",
     'def dsp_pass(takes_dir, app_path):\n',
     'def dsp_pass(takes_dir, app_path, levels=()):   # [es-roads] + the live intensities\n', 1),
    (PROBE, "probe-levels-loop",
     '            cid = cat["id"]\n'
     '            for level in (1.0, 0.5):\n',
     '            cid = cat["id"]\n'
     '            for level in sorted(set((1.0, 0.5) + tuple(levels)), reverse=True):   # [es-roads]\n', 1),
    (PROBE, "probe-levels-arg",
     '    ap.add_argument("--json")\n',
     '    ap.add_argument("--json")\n'
     '    ap.add_argument("--levels", default="", help="[es-roads] more intensities for --dsp, e.g. the live p10,median,p90")\n', 1),
    (PROBE, "probe-levels-call",
     '        got = dsp_pass(a.dsp, a.app)\n',
     '        got = dsp_pass(a.dsp, a.app, tuple(float(x) for x in a.levels.split(",") if x.strip()))   # [es-roads]\n', 1),
]


def plan(files):
    return list(EDITS)


def state_of(text, old, new, count):
    n_new = text.count(new)
    n_old = text.count(old)
    if n_new >= 1 and n_new == count and n_old == new.count(old) * n_new:
        return "applied"
    if n_new == 0 and n_old == count:
        return "ready"
    return "anchor found %d times, wanted %d; replacement found %d times" % (n_old, count, n_new)


def read(root, rel):
    return (Path(root) / rel).read_bytes().decode("utf-8").replace("\r\n", "\n")


def check(root):
    texts = {rel: read(root, rel) for rel in {e[0] for e in EDITS}}
    applied, missing = 0, []
    for rel, name, old, new, count in EDITS:
        state = state_of(texts[rel], old, new, count)
        if state == "applied":
            applied += 1
        elif state != "ready":
            missing.append("%s:%s (%s)" % (rel, name, state))
    return applied, missing, texts


def apply(root):
    applied, missing, texts = check(root)
    if applied == len(EDITS):
        return 2
    if missing:
        for m in missing:
            print("missing:", m)
        return 1
    for rel, name, old, new, count in EDITS:
        if state_of(texts[rel], old, new, count) == "applied":
            continue
        assert texts[rel].count(old) == count, "%s: anchor found %d times" % (name, texts[rel].count(old))
        texts[rel] = texts[rel].replace(old, new)
    for rel, text in texts.items():            # every file's edits verified above: write all
        assert "\r" not in text
        path = Path(root) / rel
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
    root = next((a for a in argv if not a.startswith("--")), ".")
    if do_apply:
        code = apply(root)
        print({0: "APPLIED", 1: "ANCHORS MISSING - nothing written", 2: "already applied"}[code])
        return code
    applied, missing, _texts = check(root)
    if missing:
        for m in missing:
            print("missing:", m)
        print("%d of %d applied" % (applied, len(EDITS)))
        return 1
    if applied == len(EDITS):
        print("already applied (%d edits)" % len(EDITS))
        return 2
    print("ready: %d edits, %d already in" % (len(EDITS), applied))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
