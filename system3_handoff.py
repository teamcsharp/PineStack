"""Final spoken dialogue handoffs; no station or transport dependencies."""
from __future__ import annotations
import copy
import hashlib
import json
import math
import re
import system3

DEFAULT_HANDOFF = {
    "enabled": True, "thresholds": [250, 350, 450, 550],
    "continue_probability": .25, "respond_probability": .75,
    "hard_chars": 800, "max_extra_turns": 3, "writer_retries": 1,
}
VERSION = 1


def validate_config(raw):
    if not isinstance(raw, dict):
        raise ValueError("handoff must be an object")
    out = copy.deepcopy(DEFAULT_HANDOFF)
    if "enabled" in raw:
        if not isinstance(raw["enabled"], bool):
            raise ValueError("handoff.enabled must be true or false")
        out["enabled"] = raw["enabled"]
    if "thresholds" in raw:
        values = raw["thresholds"]
        if (not isinstance(values, list) or not values or len(values) > 16
                or any(isinstance(n, bool) or not isinstance(n, int) or not 20 <= n <= 800 for n in values)
                or len(set(values)) != len(values)):
            raise ValueError("handoff.thresholds must be distinct whole character counts from 20 to 800")
        out["thresholds"] = list(values)
    for key in ("continue_probability", "respond_probability"):
        if key in raw:
            n = raw[key]
            if isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) or not 0 <= n <= 1:
                raise ValueError("handoff.%s must be between zero and one" % key)
            out[key] = float(n)
    for key, lo, hi in (("hard_chars", 20, 2000), ("max_extra_turns", 0, 24), ("writer_retries", 0, 3)):
        if key in raw:
            n = raw[key]
            if isinstance(n, bool) or not isinstance(n, int) or not lo <= n <= hi:
                raise ValueError("handoff.%s must be a whole number from %d to %d" % (key, lo, hi))
            out[key] = n
    if max(out["thresholds"]) > out["hard_chars"]:
        raise ValueError("handoff thresholds must not exceed hard_chars")
    return out


def config_of(config):
    return validate_config((config or {}).get("handoff") or {})


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()[:24]


def policy_hash(config):
    return _digest({"policy": config_of(config), "who": (config.get("split") or {}).get("who") or {}})


def _words(text):
    return " ".join(re.findall(r"[a-z0-9']+", str(text or "").replace("’", "'").casefold()))


def _ends(text):
    out = system3.sentence_ends(text)
    if re.search(r"[.!?…][\"”’')\]]*$", text):
        out.append(len(text))
    return sorted(set(out))


def _sentences(text):
    bounds = [0] + _ends(text)
    if bounds[-1] != len(text):
        bounds.append(len(text))
    return [text[a:b].strip() for a, b in zip(bounds, bounds[1:]) if text[a:b].strip()]


def _shorten(text, limit):
    if len(text) <= limit:
        return text, len(text)
    ends = [end for end in _ends(text) if end <= limit]
    if ends:
        end = ends[-1]
        return text[:end].rstrip(), end
    prefix = text[:max(1, limit - 1)]
    end = prefix.rfind(" ")
    if end <= 0:
        return "…", 0
    return prefix[:end].rstrip(" ,;:-") + "…", end


def _protected(turn):
    return any(bool(turn.get(k)) for k in ("protected_copy", "read_exactly", "handoff_protected"))


def _closing(turn, final_original_id):
    return bool(turn.get("mandatory_closing") or turn.get("required_closing") or turn.get("closing")
                or turn.get("graph_type") == "end" or turn.get("end_node")
                or (turn.get("place") == "close" and not (turn.get("handoff_opening") and not final_original_id))
                or (turn["turn_id"] == final_original_id and any(d.get("family") == "FL" for d in turn.get("decisions") or [])))


def _extra_count(conv):
    turns = conv.get("turns") or []
    marked = sum(bool(t.get("handoff_parent") or t.get("split_of") or t.get("inner_reply")
                      or t.get("cast_reaction") or t.get("turn_credit")) for t in turns)
    mainline = (conv.get("timing") or {}).get("mainline_turn_budget")
    delta = max(0, len(turns) - int(mainline)) if mainline is not None else 0
    return max(marked, delta, int((conv.get("handoff") or {}).get("extra_turns") or 0))


def _receipt(conv, turn, text, why, detail=None):
    ev = system3._event(conv, {"turn_id": turn["turn_id"], "turn_index": turn["index"]}, "HANDOFF",
        [{"stage": "receipt", "draw": None, "rule": why}],
        {"id": "RECEIPT", "label": why}, system3._snapshot(conv, turn.get("speaker")),
        meta={"kind": "length receipt", "chars": len(text), "why": why, **(detail or {})})
    ev["state_after"] = ev["state_before"]
    turn.setdefault("decisions", []).append({"family": "HANDOFF", "event_id": ev["event_id"],
                                            "item": "RECEIPT", "label": why})
    return ev["event_id"]


def _roll(conv, turn, stream, stage, options, excluded=None, forced=""):
    rows = [{"id": ident, "label": label, "base": weight, "weight": weight,
             "why": ["%s roulette" % stage]} for ident, label, weight in options]
    draw = None if forced else stream.next("HANDOFF:%s:%s" % (turn["turn_id"], stage))
    pick = next(i for i, row in enumerate(rows) if row["id"] == forced) if forced else system3.pick_index(
        [row["weight"] for row in rows], draw["u"])
    ev = system3._event(conv, {"turn_id": turn["turn_id"], "turn_index": turn["index"]}, "HANDOFF",
        [system3._stage(stage, rows, pick, draw, excluded)],
        {"id": rows[pick]["id"], "label": rows[pick]["label"]},
        system3._snapshot(conv, turn.get("speaker")), meta={"kind": stage, "forced": bool(forced)}, rng=draw)
    ev["state_after"] = ev["state_before"]
    turn.setdefault("decisions", []).append({"family": "HANDOFF", "event_id": ev["event_id"],
                                            "item": rows[pick]["id"], "label": rows[pick]["label"]})
    return rows[pick]["id"], ev["event_id"]


def _fresh_child(conv, config, parent, person, stream, ordinal, mode):
    seat = str(person["seat"])
    if not system3.participant(conv, seat):
        system3._split_participant(conv, person)
    conv.setdefault("inputs", {}).setdefault("roles", {})[seat] = str(person.get("who") or seat)
    conv["inputs"].setdefault("names", {})[seat] = str(person.get("name") or seat)
    tid = "%sh%d" % (parent["turn_id"], ordinal)
    child = {
        "turn_id": tid, "index": parent["index"] + 1, "speaker": seat,
        "name": person.get("name") or seat, "who": person.get("who") or seat,
        "step": "handoff", "step_label": "Responds to the preceding sentences" if mode == "respond" else "Carries the remaining ideas",
        "phase": parent.get("phase") or "OPEN", "cycle": parent.get("cycle", 0),
        "decisions": [], "directions": [], "speakerbox": [], "sfx": None, "sfxguy": None, "tint": None,
        "performance": None, "text": "", "script_index": None, "status": "planned",
        "handoff_parent": parent["turn_id"], "handoff_mode": mode,
        "reply_to": {"turn_id": parent["turn_id"], "speaker": parent["speaker"],
                     "name": parent.get("name") or parent["speaker"], "index": parent["index"]},
    }
    ctx = {"conv": conv, "turn_id": tid, "turn_index": child["index"], "speaker": seat,
           "phase": child["phase"], "prev_keys": set(), "recent_rounds": set(), "turns_left": 1,
           "controls": (conv.get("settings") or {}).get("controls") or {}, "availability": {},
           "personalities": config.get("personalities") or {}, "speaker_emotion_cat": "",
           "prev_lean": None, "event_emotions": {}}
    person_state = system3.participant(conv, seat)
    for family in ("ES", "RS"):
        spec, ev = system3.weighted_decision(conv, config, ctx, stream, family)
        dec = {"family": family, "event_id": ev["event_id"], "item": (spec or {}).get("id"),
               "table": (spec or {}).get("table"), "category": (spec or {}).get("category"),
               "label": (spec or {}).get("label"), "text": (spec or {}).get("text", "")}
        if spec and family == "ES":
            draw = stream.next("HANDOFF:%s:ES:intensity" % tid)
            intensity = round(.2 + .6 * draw["u"], 3)
            ev["stages"].append({"stage": "intensity", "draw": draw, "rule": "0.2 + 0.6u", "selected": intensity})
            ev["selected"]["intensity"] = dec["intensity"] = intensity
            dec["direction"] = system3.es_direction(config, spec, str(child["name"]))
            child["performance"] = system3.performance_intent(spec, intensity, conv["dynamics"],
                                                            base_arousal=system3._es_base_arousal(config, spec))
            voice = system3.es_voice(config, spec)
            if voice is not None:
                child["performance"]["voice"] = system3.voice_intent(voice, intensity)
            ctx["speaker_emotion_cat"] = spec["category"]
            if person_state:
                person_state["emotion"] = {"table": spec["table"], "category": spec["category"], "id": spec["id"],
                    "label": spec["label"], "intensity": intensity, "source": "handoff", "dims": child["performance"]["dims"]}
        elif spec:
            child["directions"].append({"family": family, "text": spec.get("text", ""), "label": spec["label"]})
        child["decisions"].append(dec)
        ev["state_after"] = system3._snapshot(conv, seat)
    child["decision_bundle_id"] = "%s:b%s" % (tid, _digest(child["decisions"])[:8])
    return child


def _duplicate_reason(text, previous):
    key = _words(text)
    if not key:
        return "empty reply"
    if any(key == _words(old) for old in previous):
        return "copies an earlier turn exactly"
    old_sentences = {_words(s) for old in previous for s in _sentences(old) if len(_words(s).split()) >= 8}
    for sentence in _sentences(text):
        words = _words(sentence)
        if words in old_sentences:
            quoted = any(_words(q) == words for group in re.findall(r'"([^"\n]+)"|“([^”\n]+)”', text) for q in group if q)
            remainder = _words(text).replace(words, "", 1).split()
            if quoted and len(words.split()) <= 12 and len(remainder) >= 3:
                continue
            return "copies an earlier sentence exactly"
    return ""


async def _write(request, writer, previous, budget, retries):
    reply, reason, attempts = "", "", []
    for attempt in range(retries + 1):
        visit = dict(request, attempt=attempt + 1, rejection=reason)
        try:
            raw = await writer(visit)
            raw = " ".join(str(raw or "").split())
            raw = re.sub(r"^[A-Z]:\s*", "", raw)
            reply, consumed = _shorten(raw, budget)
            reason = _duplicate_reason(reply, previous)
            if not raw or consumed == 0:
                reason = "empty usable reply"
            attempts.append({"attempt": attempt + 1, "chars": len(raw), "kept_chars": len(reply),
                             "rejection": reason, "writing_receipt": copy.deepcopy(visit.get("writing_receipt") or {})})
        except Exception as exc:
            if type(exc).__name__ == "WritingDeferred":
                raise
            reason = "%s: %s" % (type(exc).__name__, str(exc)[:160])
            attempts.append({"attempt": attempt + 1, "rejection": reason,
                             "writing_receipt": copy.deepcopy(visit.get("writing_receipt") or {})})
        if not reason:
            break
    return reply, reason, attempts


def _required_leg(conv, turn):
    turns = conv.get("turns") or []
    last = turns[-1]["turn_id"] if len(turns) > 1 else ""
    return bool(_protected(turn) or _closing(turn, last)
                or ((conv.get("call_structure") or conv.get("road_structure"))
                    and turn.get("place") in ("open", "close")))


async def complete_unwritten_legs(conv, config, rows, writer, tint_cuts=None):
    """Finish required legs the copy gate proves the draft never wrote.

    These use their ORIGINAL identities and directions, before any recording
    or ledger commitment. A gate/tint-rejected leg is never revived here.
    """
    gate = conv.get("turn_gate") or {}
    if gate.get("held"):
        raise ValueError("the copy gate withheld this exchange")
    dropped = {row.get("turn_id") for row in gate.get("turns") or [] if row.get("state") == "dropped"}
    if any(t["turn_id"] in dropped and _required_leg(conv, t) for t in conv.get("turns") or []):
        raise ValueError("the copy gate rejected a required conversation leg")
    unwritten = set(gate.get("unwritten_turn_ids") or [])
    missing = [t for t in conv.get("turns") or [] if t["turn_id"] in unwritten and _required_leg(conv, t)]
    if not missing:
        return list(rows), tint_cuts
    if len(missing) > 3 or any(_protected(t) for t in missing):
        raise ValueError("the writer omitted protected or too many required conversation legs")
    approved = gate.get("output_turn_ids")
    source = list((tint_cuts or {}).get("source_rows") or rows)
    by_id = {t["turn_id"]: t for t in conv.get("turns") or []}
    if (not isinstance(approved, list) or len(approved) != len(source)
            or len(set(approved)) != len(approved)
            or approved != [t["turn_id"] for t in conv.get("turns") or [] if t["turn_id"] in set(approved)]
            or any(tid not in by_id or tid in unwritten for tid in approved)
            or any(by_id[tid]["speaker"] != str(row[0]) for tid, row in zip(approved, source))):
        raise ValueError("required leg completion needs an exact copy-gate source receipt")
    source_map = dict(zip(approved, source))
    cuts = (tint_cuts or {}).get("cut_indexes") or []
    if any(isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < len(approved) for i in cuts):
        raise ValueError("the tint cut receipt has invalid source indexes")
    cut_ids = {approved[i] for i in cuts}
    active_ids = [tid for tid in approved if tid not in cut_ids]
    if len(active_ids) != len(rows):
        raise ValueError("required leg completion differs from the active tint receipt")
    active_map = dict(zip(active_ids, rows))
    policy = config_of(config)
    completed = []
    for turn in missing:
        previous = [active_map[t["turn_id"]] for t in conv["turns"]
                    if t["index"] < turn["index"] and t["turn_id"] in active_map]
        closing = _closing(turn, conv["turns"][-1]["turn_id"])
        request = {"mode": "reanchor", "turn_id": turn["turn_id"], "parent_turn_id": turn["turn_id"],
            "name": turn.get("name") or turn["speaker"], "seat": turn["speaker"],
            "who": turn.get("who") or (conv.get("inputs") or {}).get("roles", {}).get(turn["speaker"]),
            "char_budget": min(min(policy["thresholds"]), policy["hard_chars"]),
            "preceding_text": previous[-1][1] if previous else "", "previous_turns": previous[-6:],
            "remaining_ideas": "Finish this exchange with a concrete ending, then return to the music." if closing
                               else "Write the assigned protocol leg in response to the preceding speaker.",
            "directions": copy.deepcopy(turn.get("directions") or []),
            "es": next((d for d in turn.get("decisions") or [] if d.get("family") == "ES"), {}),
            "rs": next((d for d in turn.get("decisions") or [] if d.get("family") in ("RS", "IRS")), {}),
            "original_purpose": {k: copy.deepcopy(turn[k]) for k in ("step", "step_label", "phase", "protocol", "leg", "graph_type", "place") if k in turn},
            "mandatory_closing": closing, "repair_reason": "the draft never wrote this required leg"}
        reply, rejection, attempts = await _write(request, writer, [text for _seat, text in previous], request["char_budget"], 1)
        if rejection or system3.direction_echo(reply, system3.conv_direction_kit(conv)):
            raise ValueError("unwritten required leg completion failed: %s" % (rejection or "direction echo"))
        caught = system3.gate_check(conv, turn["index"], reply, [("the preceding turn", text) for _seat, text in previous])
        if caught:
            raise ValueError("unwritten required leg failed the copy gate: %s" % caught.get("why"))
        if closing and not re.search(system3.CUES["close"], reply, re.I):
            raise ValueError("unwritten required closing did not complete the exchange")
        active_map[turn["turn_id"]] = source_map[turn["turn_id"]] = (turn["speaker"], reply)
        previous_ids = [t["turn_id"] for t in conv["turns"]
                        if t["index"] < turn["index"] and t["turn_id"] in active_map]
        if previous_ids:
            preceding = by_id[previous_ids[-1]]
            turn["unwritten_reply_to"] = copy.deepcopy(turn.get("reply_to") or {})
            turn["reply_to"] = {"turn_id": preceding["turn_id"], "index": preceding["index"],
                                "speaker": preceding["speaker"]}
        turn.setdefault("handoff_writing", []).extend(a.get("writing_receipt") or {} for a in attempts)
        completed.append({"turn_id": turn["turn_id"], "why": "required leg absent from the writer draft", "attempts": attempts})
    gate["unwritten_turn_ids"] = [tid for tid in gate.get("unwritten_turn_ids") or [] if tid not in active_map]
    ids = [t["turn_id"] for t in conv["turns"] if t["turn_id"] in source_map]
    gate["output_turn_ids"] = ids
    conv["handoff_required_completion"] = completed
    final = [active_map[tid] for tid in ids if tid in active_map]
    if tint_cuts:
        tint_cuts = {"source_rows": [source_map[tid] for tid in ids],
                     "cut_indexes": [i for i, tid in enumerate(ids) if tid in cut_ids], "output_rows": final}
    return final, tint_cuts


def reconcile_copy_gate(conv, rows, tint_cuts=None):
    """Carry the copy gate's explicit omissions into an isolated final plan.

    The gate removes spoken rows while retaining its original roulette plan.
    Only omissions recorded by that gate may disappear from a final handoff;
    a writer's unexplained missing turns still fail the alignment contract.
    """
    turns = conv.get("turns") or []
    gate = conv.get("turn_gate") or {}
    dropped = {str(row.get("turn_id")) for row in gate.get("turns") or []
               if row.get("state") == "dropped" and row.get("turn") is not None
               and row.get("turn_id")}
    if gate.get("held"):
        raise ValueError("the copy gate withheld this exchange")
    unwritten = {str(tid) for tid in gate.get("unwritten_turn_ids") or [] if tid}
    omitted = dropped | unwritten
    approved = gate.get("output_turn_ids")
    if not omitted and not tint_cuts:
        return
    if unwritten and approved is None:
        raise ValueError("unwritten turns require the copy gate's approved turn identities")
    kept = [turn for turn in turns if str(turn.get("turn_id")) not in omitted]
    gate_rows = (tint_cuts or {}).get("source_rows") if tint_cuts else rows
    if (not kept or len(gate_rows) != len(kept)
            or any(str(seat) != str(turn.get("speaker"))
                   for (seat, _text), turn in zip(gate_rows, kept))):
        raise ValueError("final handoff rows must align with copy-gate survivors")
    if approved is not None and list(approved) != [turn["turn_id"] for turn in kept]:
        raise ValueError("final handoff rows differ from the copy gate's approved turn identities")
    tint_removed = []
    if tint_cuts:
        if approved is None:
            raise ValueError("tint cuts require the copy gate's approved turn identities")
        cuts = set(tint_cuts.get("cut_indexes") or [])
        if any(isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < len(kept) for i in cuts):
            raise ValueError("the tint cut receipt has invalid source indexes")
        if list(rows) != list(tint_cuts.get("output_rows") or []):
            raise ValueError("final handoff rows differ from the active tint cut receipt")
        tint_removed = [turn for i, turn in enumerate(kept) if i in cuts]
        kept = [turn for i, turn in enumerate(kept) if i not in cuts]
        if len(rows) != len(kept) or any(str(seat) != str(t["speaker"]) for (seat, _), t in zip(rows, kept)):
            raise ValueError("final handoff rows differ from the proven tinted survivors")
        omitted.update(t["turn_id"] for t in tint_removed)
    missing = [turn for turn in turns if str(turn.get("turn_id")) in unwritten]
    if any(_required_leg(conv, turn) for turn in turns if turn["turn_id"] in omitted):
        raise ValueError("the writer omitted a required conversation leg")
    removed = [turn for turn in turns if str(turn.get("turn_id")) in omitted]
    conv["handoff_gate"] = {"dropped_turn_ids": [turn["turn_id"] for turn in removed],
                            "dropped_turns": copy.deepcopy(removed),
                            "unwritten_turn_ids": [turn["turn_id"] for turn in missing],
                            "tint_cut_turn_ids": [turn["turn_id"] for turn in tint_removed]}
    conv["turns"] = kept
    indexes = {turn["turn_id"]: index for index, turn in enumerate(kept)}
    for index, turn in enumerate(kept):
        turn["index"] = index
        target = turn.get("reply_to") or {}
        if target.get("turn_id") in omitted:
            turn["gate_reply_to"] = copy.deepcopy(target)
            turn["reply_to"] = ({"turn_id": kept[index - 1]["turn_id"],
                                 "index": index - 1, "speaker": kept[index - 1]["speaker"]}
                                if index else {})
        elif target.get("turn_id") in indexes:
            target["index"] = indexes[target["turn_id"]]


async def finalize_exchange(conv, config, rows, candidates, writer, kind=""):
    """Mutate an isolated clone; return aligned rows, receipts and ancestry IDs.

    Mark a sole legacy source turn handoff_opening=True to distinguish its
    place='close' source leg from an actual planned landing. Explicit graph
    ends, mandatory closings and protected exact copies remain preserved.
    """
    policy = config_of(config)
    rows = [(str(m), str(text or "").strip()) for m, text in rows]
    turns = conv.get("turns") or []
    fingerprint = policy_hash(config)
    digest = _digest(rows)
    prior = conv.get("handoff") or {}
    current_ids = [t["turn_id"] for t in turns]
    if prior.get("policy_hash") == fingerprint:
        if digest == prior.get("input_digest") and prior.get("output_rows"):
            cached = [(str(m), str(text)) for m, text in prior["output_rows"]]
            if len(cached) == len(turns) and all(m == t["speaker"] for (m, _), t in zip(cached, turns)):
                return {"rows": cached, "changed": rows != cached, "traces": copy.deepcopy(prior.get("traces") or []),
                    "status": prior.get("status", "ready"), "policy_hash": fingerprint,
                    "original_turn_ids": list(prior.get("original_turn_ids") or current_ids), "turn_ids": current_ids}
        if digest == prior.get("output_digest"):
            return {"rows": rows, "changed": False, "traces": copy.deepcopy(prior.get("traces") or []),
                    "status": prior.get("status", "ready"), "policy_hash": fingerprint,
                    "original_turn_ids": current_ids, "turn_ids": current_ids}
    if len(rows) != len(turns) or any(m != t["speaker"] for (m, _), t in zip(rows, turns)):
        raise ValueError("final handoff rows must align with every planned turn")
    if any(not text for _m, text in rows):
        raise ValueError("final handoff rows must be nonempty")
    original_ids = current_ids
    stream = system3.DrawStream(str(conv["seed"]) + "|handoff", int(conv.get("handoff_draws") or 0))
    extra = _extra_count(conv)
    originals = list(turns)
    output_turns, output_rows, traces = [], [], []
    split_weights = (config.get("split") or {}).get("who") or system3.DEFAULT_SPLIT["who"]
    people, seen = [], set()
    for person in candidates or []:
        if isinstance(person, dict) and person.get("seat") and str(person["seat"]) not in seen:
            seen.add(str(person["seat"]))
            people.append(dict(person, seat=str(person["seat"])))

    async def finish_turn(turn, text, preset=None):
        nonlocal extra
        turn["index"] = len(output_turns)
        event = ""
        if _protected(turn) or not policy["enabled"]:
            threshold = None
        elif preset is None:
            value, event = _roll(conv, turn, stream, "threshold",
                                [(str(n), "%d characters" % n, 1.) for n in policy["thresholds"]])
            threshold = int(value)
        else:
            threshold = preset
        trace = {"turn_id": turn["turn_id"], "speaker": turn["speaker"], "kind": kind,
                 "original_chars": len(text), "threshold": threshold, "hard_chars": policy["hard_chars"],
                 "threshold_event": event, "checkpoints": [], "insertions": [], "dropped_chars": 0,
                 "extra_before": extra, "max_extra_turns": policy["max_extra_turns"], "protected": _protected(turn), "policy_hash": fingerprint, "original_text": text,
                 "source_opening": bool(turn.get("handoff_opening"))}
        traces.append(trace)
        turn["length_trace"] = trace
        if _protected(turn):
            trace["status"] = "protected_copy"
            trace["receipt"] = _receipt(conv, turn, text, str(turn.get("handoff_protection_reason") or "explicit exact reading is preserved; handoff exempt"))
            kept, tail, boundary = text, "", len(text)
        elif not policy["enabled"]:
            kept, tail, boundary = text, "", len(text)
            trace["status"] = "disabled"
            trace["receipt"] = _receipt(conv, turn, text, "length roulette disabled; accidental exact copies still checked")
        elif _closing(turn, original_ids[-1] if len(original_ids) > 1 else ""):
            kept, tail, boundary = text, "", len(text)
            trace["status"], trace["closing_kept_last"] = "closing_kept_last", True

            if len(text) > threshold:
                budget = min(threshold, policy["hard_chars"])
                request = {"mode": "shorten", "preceding_text": output_rows[-1][1] if output_rows else "",
                    "remaining_ideas": text, "name": turn.get("name") or turn["speaker"], "seat": turn["speaker"],
                    "who": turn.get("who") or (conv.get("inputs") or {}).get("roles", {}).get(turn["speaker"], turn["speaker"]),
                    "char_budget": budget, "directions": copy.deepcopy(turn.get("directions") or []),
                    "es": next((d for d in turn.get("decisions") or [] if d.get("family") == "ES"), {}),
                    "rs": next((d for d in turn.get("decisions") or [] if d.get("family") == "RS"), {}),
                    "parent_turn_id": turn["turn_id"], "turn_id": turn["turn_id"],
                    "previous_turns": copy.deepcopy(output_rows[-6:]),
                    "original_purpose": {k: copy.deepcopy(turn[k]) for k in ("step", "step_label", "phase", "protocol", "leg", "graph_type", "place") if k in turn},
                    "mandatory_closing": True, "kind": kind}
                kept, rejection, attempts = await _write(request, writer, [t for _m, t in output_rows], budget, policy["writer_retries"])
                if rejection:
                    raise ValueError("mandatory closing shortening failed on %s: %s" % (turn["turn_id"], rejection))
                trace["closing_shorten"] = {"original_text": text, "final_text": kept, "attempts": attempts,
                    "context_digest": _digest(output_rows)}
                trace["dropped_chars"] = max(0, len(text) - len(kept))
                turn.setdefault("handoff_writing", []).extend(a.get("writing_receipt") or {} for a in attempts)
            trace["receipt"] = _receipt(conv, turn, kept, "mandatory closing kept last; no handoff after the closing")
        else:
            boundary, forced = None, False
            for end in _ends(text):
                if end < threshold:
                    continue
                forced = end >= policy["hard_chars"]
                outcome, eid = _roll(conv, turn, stream, "checkpoint", [
                    ("CONTINUE", "current speaker continues", 0. if forced else policy["continue_probability"]),
                    ("HANDOFF", "another speaker enters", 1. if forced else 1. - policy["continue_probability"])],
                    forced="HANDOFF" if forced else "")
                trace["checkpoints"].append({"offset": end, "event_id": eid, "outcome": outcome, "forced": forced})
                if outcome == "HANDOFF":
                    boundary = end
                    break
            if boundary is None and len(text) > policy["hard_chars"]:
                boundary, forced = policy["hard_chars"], True
                trace["receipt"] = _receipt(conv, turn, text, "hard cap reached without a usable sentence ending")
            if boundary is None:
                kept, tail, boundary = text, "", len(text)
                trace["status"] = "under_threshold" if len(text) <= threshold else "continued"
            else:
                trace["boundary_offset"] = boundary
                kept = text[:boundary].strip()
                if len(kept) > policy["hard_chars"] or (forced and boundary not in _ends(text)):
                    kept, boundary = _shorten(text, policy["hard_chars"])
                    trace["forced_shortening"] = {"why": "the sentence exceeds the hard character cap",
                        "kept_source_offset": boundary, "hard_chars": policy["hard_chars"]}
                trace["kept_source_offset"] = boundary
                tail = text[boundary:].strip()
                trace["status"] = "boundary_handoff" if tail else "complete"
                trace["forced"] = forced
        output_turns.append(turn)
        output_rows.append((turn["speaker"], kept))
        turn["text"], turn["status"], turn["script_index"] = kept, "generated", turn["index"]
        if tail:
            options, excluded = [], []
            for person in people:
                who = str(person.get("who") or person["seat"])
                weight = float(split_weights.get(who, 1.))
                why = ("current speaker" if person["seat"] == turn["speaker"] else
                       str(person.get("unavailable_reason") or "not present") if person.get("available") is False or person.get("away") else
                       "speaker weight is zero" if weight <= 0 else "")
                if why:
                    excluded.append({"id": person["seat"], "label": person.get("name") or who, "why": why})
                else:
                    options.append((person["seat"], str(person.get("name") or who), weight))
            if extra >= policy["max_extra_turns"] or not options:
                why = "extra turn budget exhausted" if extra >= policy["max_extra_turns"] else "no eligible speaker"
                trace["status"] = "budget_shortened" if extra >= policy["max_extra_turns"] else "no_speaker_shortened"
                trace["dropped_chars"], trace["dropped_text"] = len(tail), tail
                trace["receipt"] = _receipt(conv, turn, text, why, {"excluded": excluded, "dropped_chars": len(tail)})
            else:
                seat, who_event = _roll(conv, turn, stream, "speaker", options, excluded)
                mode, mode_event = _roll(conv, turn, stream, "mode", [
                    ("respond", "respond to the preceding sentences", policy["respond_probability"]),
                    ("carry", "carry the remaining ideas", 1. - policy["respond_probability"])])
                person = next(p for p in people if p["seat"] == seat)
                actor_state_before = copy.deepcopy(conv.get("participants") or [])
                inputs_before = copy.deepcopy(conv.get("inputs") or {})
                child = _fresh_child(conv, config, turn, person, stream, extra + 1, mode)
                value, threshold_event = _roll(conv, child, stream, "threshold",
                    [(str(n), "%d characters" % n, 1.) for n in policy["thresholds"]])
                child_threshold = int(value)
                budget = child_threshold if mode == "respond" else policy["hard_chars"]
                request = {"mode": mode, "preceding_text": kept, "remaining_ideas": tail,
                    "name": child["name"], "seat": seat, "who": child["who"], "char_budget": budget,
                    "directions": copy.deepcopy(child["directions"]),
                    "es": next((d for d in child["decisions"] if d["family"] == "ES"), {}),
                    "rs": next((d for d in child["decisions"] if d["family"] == "RS"), {}),
                    "parent_turn_id": turn["turn_id"], "turn_id": child["turn_id"],
                    "previous_turns": copy.deepcopy(output_rows[-6:]), "kind": kind}
                reply, rejection, attempts = await _write(request, writer, [t for _m, t in output_rows], budget, policy["writer_retries"])
                insertion = {"turn_id": child["turn_id"], "speaker_event": who_event, "mode_event": mode_event,
                             "threshold_event": threshold_event, "mode": mode, "speaker": seat, "attempts": attempts,
                             "status": "written" if not rejection else "writer_failed"}
                trace["insertions"].append(insertion)
                if rejection:
                    conv["participants"], conv["inputs"] = actor_state_before, inputs_before
                    trace["status"] = "writer_failed_shortened"
                    trace["dropped_chars"], trace["dropped_text"] = len(tail), tail
                    _receipt(conv, turn, kept, "handoff writer failed; unspoken tail shortened", {"attempts": attempts})
                else:
                    extra += 1
                    if mode == "respond":
                        trace["dropped_chars"], trace["dropped_text"] = len(tail), tail
                    child["handoff"] = {"mode": mode, "parent_turn_id": turn["turn_id"], "speaker_event": who_event,
                        "mode_event": mode_event, "threshold_event": threshold_event, "preceding_text": kept,
                        "remaining_ideas": tail, "source_chars": len(tail), "writer_attempts": attempts}
                    child["handoff_writing"] = [a.get("writing_receipt") or {} for a in attempts]
                    await finish_turn(child, reply, child_threshold)
                    child["length_trace"]["threshold_event"] = threshold_event
        trace["final_chars"] = len(kept)
        trace["final_text"] = kept
        trace["extra_after"] = extra

    for turn, (_speaker, text) in zip(originals, rows):
        old = turn.get("length_trace") or {}
        if old and old.get("policy_hash") == fingerprint and text == turn.get("text") and old.get("final_chars") == len(text):
            turn["index"] = turn["script_index"] = len(output_turns)
            output_turns.append(turn)
            output_rows.append((turn["speaker"], text))
            traces.append(old)
        else:
            await finish_turn(turn, text)
    # The final words, including mainline rows, get the same exact-copy check.
    previous = []
    original_index = {tid: i for i, tid in enumerate(original_ids)}
    source_changed = {turn["turn_id"] for turn in output_turns if turn["turn_id"] in original_index
                      and (turn.get("length_trace") or {}).get("original_text", turn["text"]) != turn["text"]}
    for i, (speaker, text) in enumerate(output_rows):
        turn = output_turns[i]
        tid = turn["turn_id"]
        trace = turn["length_trace"]
        target = turn.get("reply_to") or {}
        target_id = target.get("turn_id")
        if tid in original_index and not target_id:
            source_index = target.get("index", original_index[tid] - 1)
            if isinstance(source_index, int) and 0 <= source_index < len(original_ids):
                target_id = original_ids[source_index]
        generated_context = (trace.get("closing_shorten") or {}).get("context_digest")
        needs_reanchor = (tid in original_index and (target_id in source_changed or turn.get("gate_reply_to"))
                          and (not generated_context or generated_context != _digest(output_rows[:i])))
        if turn.get("handoff_parent"):
            source_turn = next((t for t in output_turns[:i] if t["turn_id"] == target_id), {})
            needs_reanchor = bool((source_turn.get("length_trace") or {}).get("duplicate_repair")
                                  or (source_turn.get("length_trace") or {}).get("reanchor"))
        if needs_reanchor and previous and not _protected(turn):
            target_text = next((t["text"] for t in output_turns[:i] if t["turn_id"] == target_id), previous[-1])
            request = {"mode": "reanchor", "preceding_text": previous[-1], "target_text": target_text,
                "remaining_ideas": text, "name": turn.get("name") or speaker, "seat": speaker,
                "who": turn.get("who") or (conv.get("inputs") or {}).get("roles", {}).get(speaker, speaker),
                "char_budget": min(trace.get("threshold") or policy["hard_chars"], policy["hard_chars"]),
                "directions": copy.deepcopy(turn.get("directions") or []),
                "es": next((d for d in turn.get("decisions") or [] if d.get("family") == "ES"), {}),
                "rs": next((d for d in turn.get("decisions") or [] if d.get("family") == "RS"), {}),
                "parent_turn_id": target_id, "turn_id": tid, "previous_turns": copy.deepcopy(output_rows[max(0, i - 6):i]),
                "original_purpose": {k: copy.deepcopy(turn[k]) for k in ("step", "step_label", "phase", "protocol", "leg", "graph_type", "place") if k in turn},
                "mandatory_closing": _closing(turn, original_ids[-1] if len(original_ids) > 1 else ""),
                "kind": kind}
            reply, rejection, attempts = await _write(request, writer, previous, request["char_budget"], policy["writer_retries"])
            if rejection:
                raise ValueError("dialogue reanchor failed on %s: %s" % (tid, rejection))
            trace["reanchor"] = {"target_turn_id": target_id, "original_text": text, "final_text": reply, "attempts": attempts}
            trace["final_chars"], trace["final_text"] = len(reply), reply
            turn.setdefault("handoff_writing", []).extend(a.get("writing_receipt") or {} for a in attempts)
            turn["text"] = reply
            output_rows[i] = (speaker, reply)
            source_changed.add(tid)
            _receipt(conv, turn, reply, "reply reanchored to the sentences actually spoken", {"target_turn_id": target_id})
            text = reply
        reason = _duplicate_reason(text, previous)
        echo = system3.direction_echo(text, system3.conv_direction_kit(conv))
        if echo:
            reason = "says the running-order direction aloud: %s" % echo
        if reason and not _protected(turn):
            trace = turn["length_trace"]
            request = {"mode": "repair_duplicate", "repair_reason": reason,
                "preceding_text": previous[-1] if previous else "",
                "remaining_ideas": text, "name": turn.get("name") or speaker, "seat": speaker,
                "who": turn.get("who") or (conv.get("inputs") or {}).get("roles", {}).get(speaker, speaker),
                "char_budget": min(trace.get("threshold") or policy["hard_chars"], policy["hard_chars"]), "directions": copy.deepcopy(turn.get("directions") or []),
                "es": next((d for d in turn.get("decisions") or [] if d.get("family") == "ES"), {}),
                "rs": next((d for d in turn.get("decisions") or [] if d.get("family") == "RS"), {}),
                "mandatory_closing": _closing(turn, original_ids[-1] if len(original_ids) > 1 else ""),
                "original_purpose": {k: copy.deepcopy(turn[k]) for k in ("step", "step_label", "phase", "protocol", "leg", "graph_type", "place") if k in turn},
                "parent_turn_id": turn["turn_id"], "turn_id": turn["turn_id"],
                "previous_turns": copy.deepcopy(output_rows[max(0, i - 6):i]), "kind": kind}
            reply, rejection, attempts = await _write(request, writer, previous, request["char_budget"], 1)
            if rejection:
                raise ValueError("duplicate dialogue repair failed on %s: %s" % (turn["turn_id"], rejection))
            trace["duplicate_repair"] = {"reason": reason, "original_text": text, "final_text": reply, "attempts": attempts}
            trace["final_chars"], trace["final_text"] = len(reply), reply
            source_changed.add(tid)
            turn.setdefault("handoff_writing", []).extend(a.get("writing_receipt") or {} for a in attempts)
            turn["text"] = reply
            output_rows[i] = (speaker, reply)
            _receipt(conv, turn, reply, "duplicate repaired using the existing actor and roulette", {"reason": reason})
            text = reply
        previous.append(text)
    conv["turns"] = output_turns
    indexes = {turn["turn_id"]: i for i, turn in enumerate(output_turns)}
    for i, turn in enumerate(output_turns):
        turn["index"] = turn["script_index"] = i
        target = turn.get("reply_to") or {}
        if target.get("turn_id") in indexes:
            target["index"] = indexes[target["turn_id"]]
            if turn.get("protocol") and "[reply-target=" in turn["protocol"]:
                turn["protocol"] = re.sub(r"\[reply-target=\d+\]", "[reply-target=%d]" % (target["index"] + 1), turn["protocol"])
    conv["handoff_draws"] = stream.n
    conv["handoff"] = {"version": VERSION, "status": "ready" if policy["enabled"] else "disabled", "policy_hash": fingerprint, "policy": policy,
        "input_digest": digest, "output_digest": _digest(output_rows), "output_rows": copy.deepcopy(output_rows),
        "original_turn_ids": original_ids, "extra_turns": extra, "traces": copy.deepcopy(traces)}
    conv.setdefault("timing", {})["turn_budget"] = len(output_turns)
    return {"rows": output_rows, "changed": rows != output_rows, "traces": traces,
            "status": "ready" if policy["enabled"] else "disabled", "policy_hash": fingerprint,
            "original_turn_ids": original_ids, "turn_ids": [t["turn_id"] for t in output_turns]}

