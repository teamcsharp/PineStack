"""Bounded pre-recording dialogue recovery; the caller owns attempts and time.

One operation makes at most one exchange-writing request. This module never
records audio, weakens final alignment, or schedules another operation.
"""
from __future__ import annotations

import copy
import re

import system3
import system3_handoff


OPERATIONS = ("repair", "rewrite", "reroll", "rebuild")
FREE_TOPICS = (
    "Which everyday invention deserves a ridiculous improvement?",
    "What makes a terrible set of directions memorable?",
    "Debate the most impractical imaginary household gadget.",
    "What would a lost sock say if it could explain itself?",
    "Invent competing rules for an imaginary neighborhood game.",
    "Which small inconvenience would make the funniest fictional mystery?",
)


def parse_exchange(value, turns):
    """Require exactly one labelled, nonempty line for each current turn."""
    if not isinstance(value, str):
        raise ValueError("recovery writer must return a labelled dialogue script")
    parsed = []
    for line in value.splitlines():
        if not line.strip():
            continue
        matched = re.fullmatch(r"\s*([ABCDE]):\s*(\S.*?)\s*", line)
        if not matched:
            raise ValueError("recovery output includes unlabelled or empty dialogue")
        parsed.append((matched[1], matched[2]))
    if len(parsed) != len(turns) or any(
        seat != str(turn.get("speaker"))
        for (seat, _text), turn in zip(parsed, turns)
    ):
        raise ValueError("recovery rows must align with every planned turn")
    return parsed


def _known_rows(turns, rows, allow_extra=False, source_turn_ids=None):
    """Only an aligned prefix or a turn's stored text proves its identity.

    Once markers diverge, repeated seats make positional repair ambiguous.
    Their words remain source evidence, never reassigned to another turn.
    """
    if source_turn_ids is not None:
        identities = [str(tid) if tid is not None else "" for tid in source_turn_ids]
        claimed = [tid for tid in identities if tid]
        by_id = {str(turn["turn_id"]): turn for turn in turns}
        if (len(identities) != len(rows) or len(set(claimed)) != len(claimed)
                or (not allow_extra and any(tid not in by_id for tid in identities))):
            raise ValueError("proven recovery source identities do not match the current plan")
        indexes = {str(turn["turn_id"]): index for index, turn in enumerate(turns)}
        identified = [tid for tid in identities if tid in by_id]
        if [indexes[tid] for tid in identified] != sorted(indexes[tid] for tid in identified):
            raise ValueError("proven recovery source identities changed their planned order")
        known = {str(turn["turn_id"]): (str(turn["speaker"]), str(turn["text"]).strip())
                 for turn in turns if str(turn.get("text") or "").strip()}
        for tid, (seat, supplied) in zip(identities, rows):
            if tid not in by_id:
                # A previous gate may reference a turn removed by an older
                # structural revision. Rewriting retains its row as source
                # evidence; it never acquires a current turn by position.
                continue
            if str(seat) != str(by_id[tid]["speaker"]):
                raise ValueError("proven recovery wording belongs to a different speaker")
            if str(supplied or "").strip():
                known[tid] = (str(seat), str(supplied).strip())
        return known
    if len(rows) > len(turns) and not allow_extra:
        raise ValueError("recovery cannot silently discard unplanned dialogue rows")
    known, prefix = {}, True
    for index, turn in enumerate(turns):
        text = str(turn.get("text") or "").strip()
        if index < len(rows):
            seat, supplied = rows[index]
            prefix = prefix and str(seat) == str(turn.get("speaker"))
            if prefix and str(supplied or "").strip():
                text = str(supplied).strip()
        if text:
            known[str(turn["turn_id"])] = (str(turn["speaker"]), text)
    return known


def _can_change_topic(conv, protected):
    inputs, subject = conv.get("inputs") or {}, conv.get("subject") or {}
    road = str((conv.get("identity") or {}).get("road_kind") or inputs.get("road") or "")
    return bool(road == "banter" and subject.get("authority") == "free"
                and not protected and not subject.get("sources")
                and not subject.get("seeded") and not subject.get("exchange")
                and not inputs.get("call") and not inputs.get("news")
                and not inputs.get("own_material") and not inputs.get("source"))


def _rebuild(conv, config, variant, protected, known):
    old = copy.deepcopy(conv)
    if old.get("lines"):
        raise ValueError("recorded or committed dialogue cannot be rebuilt")
    inputs = copy.deepcopy(old.get("inputs") or {})
    participants = copy.deepcopy(old.get("participants") or [])
    seats = [str(person["actor_id"]) for person in participants]
    if not seats:
        raise ValueError("recovery needs the original speaker identities")
    inputs["seats"] = seats
    inputs["names"] = {str(p["actor_id"]): p.get("name") or p["actor_id"] for p in participants}
    inputs["roles"] = {str(p["actor_id"]): p.get("role") or "" for p in participants}
    inputs["subject"] = copy.deepcopy(old.get("subject") or {})
    road = str(old["identity"].get("road_kind") or "banter")
    revision = int(old["identity"].get("revision") or 1) + 1
    namespace = "%s:recovery:r%d" % (old["identity"]["conversation_id"], revision)
    rebuilt = system3.new_conversation(inputs, config, old["settings"],
        seed=variant["seed"], conversation_id=namespace)
    rebuilt["identity"].update(copy.deepcopy(old["identity"]))
    rebuilt["identity"].update(conversation_id=namespace, revision=revision)
    rebuilt["identity"].pop("script_digest", None)
    rebuilt["participants"] = copy.deepcopy(participants)
    if old.get("call_structure"):
        system3.plan_call(rebuilt, config, inputs)
    elif road == "caller":
        rows = [(index + 1, turn["speaker"], turn.get("protocol") or turn.get("step_label") or "Respond.")
                for index, turn in enumerate(old.get("turns") or [])]
        system3.plan_protocol(rebuilt, config, rows, inputs)
    elif old.get("road_structure"):
        if len(seats) == 1:
            system3.plan_line(rebuilt, config, inputs)
        else:
            system3.plan_legs(rebuilt, config, inputs, road)
    elif old.get("graph_structure") and road != "banter":
        graph = (system3.road_structure(config, road) or {}).get("graph") or {}
        system3.plan_graph(rebuilt, config, graph, inputs=inputs, road=road)
    else:
        system3.plan_more(rebuilt, config, inputs=inputs)
    if any(str(turn.get("speaker")) not in seats for turn in rebuilt["turns"]):
        raise ValueError("recovery rebuild introduced a different speaker")
    # Preserve exact-reading legs at their original relative locations. They
    # retain ancestry IDs; fresh plan legs never impersonate their text.
    old_turns = old.get("turns") or []
    fixed = [turn for turn in old_turns if str(turn["turn_id"]) in protected]
    fixed_ids = {str(turn["turn_id"]) for turn in fixed}
    fresh = [turn for turn in rebuilt["turns"] if str(turn["turn_id"]) not in fixed_ids]
    for turn in fixed:
        index = min(int(turn.get("index") or 0), len(fresh))
        if index < len(fresh) and fresh[index]["speaker"] == turn["speaker"]:
            fresh[index] = copy.deepcopy(turn)
        else:
            fresh.insert(index, copy.deepcopy(turn))
    # A mandatory landing keeps its actor, purpose and facts, even if the
    # new structure selected another closing. It remains the final leg.
    closing = next((turn for turn in reversed(old_turns)
                    if system3_handoff._closing(turn, old_turns[-1]["turn_id"])), None)
    if closing:
        final_fresh_id = fresh[-1]["turn_id"] if fresh else ""
        fresh = [turn for turn in fresh if str(turn["turn_id"]) in fixed_ids
                 or not system3_handoff._closing(turn, final_fresh_id)]
        fresh = [turn for turn in fresh if str(turn["turn_id"]) != str(closing["turn_id"])]
        fresh.append(copy.deepcopy(closing))
    if not fresh:
        raise ValueError("recovery rebuild produced no planned turns")
    for index, turn in enumerate(fresh):
        if closing and turn["turn_id"] == closing["turn_id"]:
            turn["recovery_required_conclusion"] = known.get(str(turn["turn_id"]), ("", ""))[1] or str(turn.get("text") or "")
        turn["index"] = index
        turn["script_index"] = None
        turn["status"] = "planned"
        turn["text"] = known.get(str(turn["turn_id"]), ("", ""))[1] if str(turn["turn_id"]) in protected else ""
        # A rebuilt adjacency is explicit rather than stale old indexes.
        turn["reply_to"] = ({"turn_id": fresh[index - 1]["turn_id"],
                             "index": index - 1, "speaker": fresh[index - 1]["speaker"]}
                            if index else {})
    rebuilt["turns"] = fresh
    rebuilt["participants"] = participants
    rebuilt["mode"] = old.get("mode", rebuilt["mode"])
    rebuilt["identity"]["conversation_id"] = old["identity"]["conversation_id"]
    rebuilt["dialogue_recovery_ancestry"] = {
        "prior_seed": old.get("seed"), "prior_revision": old["identity"].get("revision", 1),
        "original_turn_ids": [turn["turn_id"] for turn in old_turns],
        "speakers_preserved": True,
    }
    # Keep past decisions identifiable without changing their revisions.
    history = copy.deepcopy(old.get("decision_events") or [])
    for event in history:
        event.setdefault("meta", {})["prior_revision"] = True
    events = rebuilt.get("decision_events", [])
    sequence_base = max((int(event.get("seq") or 0) for event in history), default=-1) + 1
    current_indexes = {turn["turn_id"]: index for index, turn in enumerate(fresh)}
    for index, event in enumerate(events):
        event["seq"] = sequence_base + index
        event["conversation_id"] = old["identity"]["conversation_id"]
        event["turn_index"] = current_indexes.get(event.get("turn_id"), -1)
        if event.get("turn_id") and event["turn_index"] == -1:
            event.setdefault("meta", {})["recovery_replaced"] = True
    rebuilt["decision_events"] = history + events
    for field in ("dialogue_recovery", "dialogue_recovery_unbound", "carry", "callend"):
        if field in old and field not in rebuilt:
            rebuilt[field] = copy.deepcopy(old[field])
    conv.clear()
    conv.update(rebuilt)


async def prepare_recovery(conv, config, rows, candidates, writer, attempt, protected_ids=(), source_turn_ids=None):
    """Mutate an isolated candidate and return strictly aligned spoken rows.

    ``attempt`` is the policy descriptor: operation, seed, variation_id,
    pass, attempt, style_level, with optional rejection and failed_turn_ids.
    Its caller must run the normal final handoff and review gates afterward.
    ``source_turn_ids`` optionally supplies the gate's proven surviving IDs;
    those rows are never inferred by their position or repeated seat marker.
    """
    variant = copy.deepcopy(dict(attempt or {}))
    operation = str(variant.get("operation") or "repair")
    if operation not in OPERATIONS:
        raise ValueError("unknown dialogue recovery operation")
    chapter = str((conv.get("chapter_state") or {}).get("state") or "")
    if (conv.get("lines") or str(conv.get("status") or "") in
            ("chapter_airing", "chapter_aired", "chapter_partial")
            or chapter in ("airing", "in_flight", "aired", "partial")):
        raise ValueError("recorded or committed dialogue cannot be recovered")
    if conv.get("bindings"):
        conv["dialogue_recovery_unbound"] = copy.deepcopy(conv.pop("bindings"))
        conv["bindings"] = []
    variant["seed"] = str(variant.get("seed") or "%s|recovery:%s:%s:%s" % (
        conv.get("seed"), variant.get("pass", 1), variant.get("attempt", 1), operation))
    turns = conv.get("turns") or []
    if not turns:
        raise ValueError("dialogue recovery needs a current plan")
    source_rows = [(str(seat), str(text or "").strip()) for seat, text in rows]
    known = _known_rows(turns, source_rows, allow_extra=operation != "repair",
                        source_turn_ids=source_turn_ids)
    current_ids = {str(turn["turn_id"]) for turn in turns}
    source_evidence = {
        "policy": "Only current identified turns have ownership; stale rows remain unassigned source evidence.",
        "identified_source_turn_ids": [str(tid) for tid in source_turn_ids or []
                                       if str(tid) in current_ids],
        "unassigned_rows": [{"source_index": index, "source_turn_id": str(tid) if tid is not None else "",
                             "speaker": source_rows[index][0]}
                            for index, tid in enumerate(source_turn_ids or []) if str(tid) not in current_ids],
    }
    protected = {str(tid) for tid in protected_ids}
    protected.update(str(turn["turn_id"]) for turn in turns if system3_handoff._protected(turn))
    if any(tid not in known for tid in protected):
        raise ValueError("a protected turn has no identified exact wording")
    for turn in turns:
        if str(turn["turn_id"]) in protected:
            turn["handoff_protected"] = True
    if operation in ("reroll", "rebuild") and _can_change_topic(conv, protected):
        stream = system3.DrawStream(str(variant.get("topic_seed") or variant["seed"]) + "|topic")
        draw = stream.next("RECOVERY:topic")
        topic = FREE_TOPICS[min(len(FREE_TOPICS) - 1, int(draw["u"] * len(FREE_TOPICS)))]
        conv.setdefault("subject", {}).update(topic=topic, active_angle="", keywords=[])
        conv.setdefault("inputs", {})["subject"] = copy.deepcopy(conv["subject"])
        variant["topic"] = {"text": topic, "draw": draw, "premise_preserved": False}
    else:
        variant["topic"] = {"text": (conv.get("subject") or {}).get("topic", ""),
                            "premise_preserved": True}
    if operation == "rebuild":
        _rebuild(conv, config, variant, protected, known)
        turns = conv["turns"]
    conv.pop("handoff", None)
    conv["dialogue_recovery_variant"] = variant
    failed = {str(tid) for tid in variant.get("failed_turn_ids") or []}
    preserved = []
    for index, turn in enumerate(turns):
        tid = str(turn["turn_id"])
        if tid in known and (tid in protected or (operation == "repair" and tid not in failed)):
            seat, text = known[tid]
            if seat != str(turn.get("speaker")):
                raise ValueError("identified wording belongs to a different planned speaker")
            preserved.append({"turn_id": tid, "index": index, "speaker": seat, "text": text,
                              "protected": tid in protected})
    # With no structural gap and no explicit failed identity, the previous
    # gate did not approve the mutable rows. Repair them rather than replay.
    if operation == "repair" and len(preserved) == len(turns) and not failed:
        preserved = [row for row in preserved if row["protected"]]
    if len(preserved) == len(turns):
        return [(row["speaker"], row["text"]) for row in preserved]
    request = {"mode": "recover_exchange", "recovery": variant,
        "planned_turns": copy.deepcopy(turns), "preserved_rows": preserved,
        "source_rows": source_rows, "subject": copy.deepcopy(conv.get("subject") or {}),
        "source_identity_evidence": copy.deepcopy(source_evidence),
        "participants": copy.deepcopy(conv.get("participants") or []),
        "source_context": copy.deepcopy(conv.get("inputs") or {}),
        "rejection": str(variant.get("rejection") or variant.get("reason") or ""),
        "char_budget": system3_handoff.config_of(config)["hard_chars"]}
    output = await writer(request)
    aligned = parse_exchange(output, turns)
    for fixed in preserved:
        if aligned[fixed["index"]] != (fixed["speaker"], fixed["text"]):
            raise ValueError("recovery changed an immutable identified turn")
    for turn, (_seat, text) in zip(turns, aligned):
        turn["text"] = text
        turn["status"] = "generated"
    conv["dialogue_recovery_preparation"] = {
        "operation": operation, "variation_id": variant.get("variation_id"),
        "preserved_turn_ids": [row["turn_id"] for row in preserved],
        "writing_receipt": copy.deepcopy(request.get("writing_receipt") or {}),
        "original_rows": source_rows,
        "source_turn_ids": list(source_turn_ids) if source_turn_ids is not None else None,
        "source_identity_evidence": source_evidence,
    }
    return aligned
