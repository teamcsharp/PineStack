"""Pre-recording handoff adapters; no station imports or playback side effects."""
from __future__ import annotations
import copy
import hashlib
import json
import re
import time
from typing import Any

from dialogue_recovery import failure_feedback


def text_digest(text: Any) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def protected_rows(source: dict[str, Any], rows: list[tuple[str, str]]) -> list[int]:
    """A saved recording is not itself an exemption; explicit exact copy is."""
    if any(source.get(k) is True for k in ("read_exactly", "protected_copy", "handoff_protected")):
        return list(range(len(rows)))
    passages = []
    for passage in source.get("verbatim") or []:
        if isinstance(passage, (list, tuple)) and len(passage) > 1:
            passages.append(" ".join(str(passage[-1] or "").split()))
        elif isinstance(passage, str):
            passages.append(" ".join(passage.split()))
    selected = {i for i in source.get("protected_turns") or []
                if isinstance(i, int) and not isinstance(i, bool) and 0 <= i < len(rows)}
    for i, (_seat, text) in enumerate(rows):
        words = " ".join(str(text or "").split())
        if any(p and p in words for p in passages):
            selected.add(i)
    return sorted(selected)


def _recovery_blocks(request: dict[str, Any], blocks: list[tuple[str, str]]) -> tuple[str, dict[str, Any]]:
    """Replayable prompt changes, restricted to optional creative directions."""
    recovery = request.get("recovery") or request.get("dialogue_recovery_variant") or {}
    if not isinstance(recovery, dict) or not recovery:
        return "\n".join(value for _key, value in blocks), {}
    import system3
    seed = str(recovery.get("seed") or recovery.get("variation_id") or "dialogue-recovery")
    stream = system3.DrawStream(seed + "|writer-prompt")
    ordered = sorted(blocks, key=lambda block: stream.next("RECOVERY:prompt:" + block[0])["u"])
    level = max(0, min(3, int(recovery.get("style_level") or 0)))
    feedback = failure_feedback(request.get("rejection") or request.get("repair_reason") or recovery.get("reason"))
    if feedback["category"] == "turn_structure":
        if request.get("mode") != "recover_exchange":
            feedback["instruction"] = (
                "For this single-turn repair, return only the assigned speaker's spoken words. "
                "Keep the assigned purpose, facts and response to the preceding line. "
                "Do not output JSON, speaker labels, additional turns or production instructions; "
                "the exchange assembler owns the planned order.")
        elif not request.get("identified_output"):
            feedback["instruction"] = (
                "Return exactly one nonempty labelled dialogue line per current planned turn, "
                "in its listed order and assigned speaker. Retain protected wording and every "
                "required leg. Do not output JSON or additional dialogue.")
    method_draw = stream.next("RECOVERY:writing-method")
    methods = (
        "Draft the concrete response first, then apply the speaker's feeling.",
        "Start from a specific detail in the preceding speaker's actual words.",
        "Use a fresh sentence construction and a direct conversational response.",
        "Keep each thought focused; make the response move the exchange forward.",
    )
    method = methods[min(len(methods) - 1, int(method_draw["u"] * len(methods)))]
    styles = (
        "Keep the assigned creative style where it fits the concrete response.",
        "Rhyme is optional. Keep the assigned character, creative style and scene purpose.",
        "Rhyme and optional minimum length targets are unnecessary. Focus each thought; keep the assigned style.",
        "Use brief natural dialogue. Rhyme, decorative style and optional length targets are unnecessary.",
    )
    policy = ("RECOVERY VARIATION (instructions only): " + str(recovery.get("variation_id") or seed)
              + "\nRECOVERY OPERATION: " + str(recovery.get("operation") or "repair")
              + "\nFAILURE CATEGORY: " + feedback["category"]
              + "\nTARGETED REPAIR: " + feedback["instruction"]
              + "\nWRITING METHOD: " + method + "\nCREATIVE POLICY: " + styles[level]
              + " Never relax speaker identity, protected wording, facts, required purpose or the final alignment contract.")
    return policy + "\n" + "\n".join(value for _key, value in ordered), {
        "seed": seed, "order": [key for key, _value in ordered], "style_level": level,
        "variation_id": recovery.get("variation_id"), "method_draw": method_draw,
        "failure_category": feedback["category"], "repair_action": feedback["action"],
    }


def _creative_directions(value: Any, level: int) -> str:
    """Remove optional style clauses from directions, never protected source."""
    words = "\n".join(str(item) for item in value) if isinstance(value, (list, tuple)) else str(value or "")
    if not level:
        return words
    clauses = re.split(r"(?<=[.!?])\s+|\n+|;\s*|\s+and\s+", words)
    phrases = [r"rhyme", r"rhyming", r"multisyllabic"]
    if level >= 2:
        phrases += [r"bar length", r"minimum length", r"minimum.*words", r"at least.*sentences"]
    if level >= 3:
        phrases += [r"cadence", r"ornate", r"decorative", r"stylistic", r"flowery"]
    optional = re.compile(r"\b(?:" + "|".join(phrases) + r")\b", re.I)
    semantic = re.compile(r"\b(?:fact|facts|price|prices|quantity|quantities|name|names|date|dates|"
                          r"source|mandatory|required|preserve|accurate|meaning|do not invent)\b", re.I)
    # Mixed semantic/style requirements stay intact rather than dropping the
    # source obligation while loosening decorative wording.
    return " ".join(clause for clause in clauses if not optional.search(clause) or semantic.search(clause))


def _identified_contract(request, planned, budget):
    fixed = {}
    for row in request.get("preserved_rows") or []:
        index = row.get("index")
        if (not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(planned)
                or row.get("turn_id") != planned[index].get("turn_id")
                or row.get("speaker") != planned[index].get("speaker") or not str(row.get("text") or "").strip()):
            raise ValueError("immutable recovery wording has no matching planned identity")
        if index in fixed:
            raise ValueError("immutable recovery identity is duplicated")
        fixed[index] = str(row["text"])
    keys = {i: "turn_%04d" % i for i in range(len(planned)) if i not in fixed}
    ceiling = max(1, min(20000, int(request.get("output_char_limit") or 6500)))
    # Leave room for JSON keys, quotes and escaping under the operator's cap.
    per_turn = min(budget, (ceiling - 32 * len(keys) - 8) // max(1, 2 * len(keys)))
    if keys and per_turn < 40:
        raise ValueError("the output budget cannot hold every planned recovery turn")
    properties = {key: {"type": "string", "minLength": 1, "maxLength": per_turn} for key in keys.values()}
    schema = {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}
    return keys, fixed, schema, ceiling


def _identified_rows(raw, planned, keys, fixed, clean, schema=None):
    def unique_object(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("identified recovery output repeats a turn key")
            obj[key] = value
        return obj
    value = json.loads(str(raw or ""), object_pairs_hook=unique_object)
    if not isinstance(value, dict) or set(value) != set(keys.values()):
        raise ValueError("identified recovery output must contain exactly its planned turn keys")
    rows = []
    for index, turn in enumerate(planned):
        if index in fixed:
            words = fixed[index]
        else:
            text = value[keys[index]]
            if not isinstance(text, str) or not text.strip():
                raise ValueError("identified recovery turn is empty or not spoken text")
            if schema and len(text) > schema["properties"][keys[index]]["maxLength"]:
                raise ValueError("identified recovery turn exceeds its spoken length budget")
            if re.search(r"(?:^|\n)\s*[ABCDE]\s*:", text):
                raise ValueError("identified recovery turn contains another speaker label")
            words = " ".join(str(clean(text) or "").split())
            if not words:
                raise ValueError("identified recovery cleaning removed the spoken turn")
        rows.append(str(turn["speaker"]) + ": " + words)
    return "\n".join(rows)


async def _write_exchange(request: dict[str, Any], ask: Any, clean: Any) -> str:
    recovery = request.get("recovery") or {}
    level = max(0, min(3, int(recovery.get("style_level") or 0)))
    planned = []
    for index, turn in enumerate(request.get("planned_turns") or []):
        planned.append({"index": index, "turn_id": turn.get("turn_id"), "speaker": turn.get("speaker"),
            "name": turn.get("name"), "purpose": turn.get("protocol") or turn.get("step_label") or turn.get("step"),
            "directions": _creative_directions(turn.get("directions") or "", level),
            "feeling": turn.get("performance"), "reply_to": turn.get("reply_to"),
            "required_conclusion": turn.get("recovery_required_conclusion") or "",
            "mandatory_closing": bool(turn.get("mandatory_closing") or turn.get("required_closing")
                or turn.get("closing") or turn.get("graph_type") == "end" or turn.get("end_node")
                or turn.get("place") == "close")})
    count = len(planned)
    budget = max(40, int(request.get("char_budget") or 450))
    identified = bool(request.get("identified_output"))
    keys, fixed, schema, ceiling = _identified_contract(request, planned, budget) if identified else ({}, {}, None, 0)
    if identified:
        for index, turn in enumerate(planned):
            turn["output_key"] = keys.get(index)
            turn["immutable_supplied_by_system"] = index in fixed
    blocks = [
        ("plan", "CURRENT RUNNING ORDER — every row is mandatory:\n" + json.dumps(planned, ensure_ascii=False, default=str)),
        ("preserved", "IMMUTABLE IDENTIFIED TURNS — repeat their exact words at their listed index:\n"
            + json.dumps(request.get("preserved_rows") or [], ensure_ascii=False, default=str)),
        ("speakers", "ORIGINAL SPEAKERS — retain their names, roles, character and identities:\n"
            + json.dumps(request.get("participants") or [], ensure_ascii=False, default=str)),
        ("subject", "SCENE PREMISE AND REQUIRED FACTS:\n"
            + json.dumps(request.get("subject") or {}, ensure_ascii=False, default=str)),
        ("source", "EARLIER DRAFT — source evidence only; its positions do not override the current plan:\n"
            + json.dumps({"rows": request.get("source_rows") or [],
                          "identity_evidence": request.get("source_identity_evidence") or {}},
                         ensure_ascii=False, default=str)),
        ("context", "GROUNDED SOURCE CONTEXT — preserve facts and required copy:\n"
            + json.dumps(request.get("source_context") or {}, ensure_ascii=False, default=str)),
        ("feedback", "PREVIOUS ATTEMPT FAILED: " + str(request.get("rejection") or "The prior exchange did not pass final preparation.")),
    ]
    body, variation = _recovery_blocks(request, blocks)
    prompt = (f"Recover ONE complete radio exchange with exactly {count} dialogue lines.\n"
        "Output only A:, B:, C:, D: or E: followed by spoken words, one line per current planned turn, "
        "in precisely its listed order. No numbers, preface, commentary, markdown or stage directions.\n"
        f"Each mutable turn must use at most {budget} spoken characters including spaces and punctuation; "
        "protected exact wording is preserved even when longer. Use complete thoughts.\n"
        "Every new line responds to what was actually said. Do not invent observations, events, prices, "
        "times or facts; do not transfer another person's first-person experiences. "
        "Keep required closings last and preserve their required conclusion.\n" + body)
    if identified:
        prompt = prompt.replace(
            "Output only A:, B:, C:, D: or E: followed by spoken words, one line per current planned turn, in precisely its listed order. No numbers, preface, commentary, markdown or stage directions.",
            "Follow the JSON output contract below. The system assigns each value to its planned speaker and position. No preface, commentary, markdown or stage directions.")
        prompt += ("\nOUTPUT CONTRACT: Return only one JSON object with the required keys in this schema. "
                   "Each value contains ONLY the spoken words of the exact planned speaker at that key. "
                   "Do not include speaker labels, extra dialogue lines, or immutable turns; the system supplies immutable wording. "
                   "Use brief, complete linked thoughts and retain every assigned purpose and required closing.\n"
                   + json.dumps(schema, ensure_ascii=False))
    receipt = {"prompt": prompt, "requested_chars": budget, "kind": "dialogue recovery",
        "mode": "recover_exchange", "at": time.time(), "raw_result": "", "clean_result": "",
        "recovery": variation}
    request["writing_receipt"] = receipt
    if identified and not keys:
        receipt["output_contract"] = "identified_turns_json"
        words = _identified_rows("{}", planned, keys, fixed, clean)
        receipt["clean_result"] = words
        return words
    if identified:
        receipt["output_contract"] = "identified_turns_json"
    raw = await ask(prompt, limit=ceiling if identified else min(20000, max(1600, count * budget * 2)), spice=0.55,
        **({"result_schema": schema} if identified else {}),
        result_contract="json" if identified else "structured_turns",
        num_ctx=32768, mark={"kind": "dialogue recovery", "mode": "recover_exchange",
                            "variation_id": recovery.get("variation_id"), "operation": recovery.get("operation")})
    receipt["raw_result"] = str(raw or "")
    if identified:
        words = _identified_rows(raw, planned, keys, fixed, clean, schema)
        receipt["clean_result"] = words
        return words
    output = []
    for line in str(raw or "").splitlines():
        match = re.fullmatch(r"\s*([ABCDE]):\s*(.*?)\s*", line)
        if match:
            output.append(match[1] + ": " + " ".join(str(clean(match[2]) or "").split()))
        elif line.strip():
            # Preserve unexpected text so the strict parser refuses it.
            output.append(line.strip())
    words = "\n".join(output)
    receipt["clean_result"] = words
    return words


async def write_turn(request: dict[str, Any], ask: Any, clean: Any) -> str:
    """Retain the actual prompt and output alongside the rolled action."""
    mode = str(request.get("mode") or "respond")
    if mode == "recover_exchange":
        return await _write_exchange(request, ask, clean)
    budget = max(40, int(request.get("char_budget") or 250))
    actions = {
        "respond": "Respond with a concrete reaction, question, rebuttal or joke. Add something new. You may trim or drop remaining ideas.",
        "carry": "Carry forward remaining ideas in your own voice, connecting them to what was just said. Keep factual terms and amounts accurate.",
        "carry_forward": "Carry forward remaining ideas in your own voice, connecting them to what was just said. Keep factual terms and amounts accurate.",
        "repair_duplicate": "Rewrite this accidental copy as a new response. Keep its assigned purpose and feeling, and add a concrete new thought.",
        "reanchor": "Rewrite the assigned line to answer what was actually spoken. Preserve its purpose, mandatory conclusion, feeling and required facts; do not refer to dropped material.",
        "shorten": "Shorten the material to one complete, focused spoken thought. Keep required facts accurate.",
    }
    rejection = str(request.get("rejection") or request.get("repair_reason") or "")
    recovery = request.get("recovery") or request.get("dialogue_recovery_variant") or {}
    level = max(0, min(3, int(recovery.get("style_level") or 0))) if isinstance(recovery, dict) else 0
    prompt = (
        "Write ONE studio speaker's radio dialogue turn.\n"
        f"SPEAKER: {request.get('name') or request.get('seat') or 'studio speaker'}.\n"
        f"ACTION: {actions.get(mode, actions['respond'])}\n"
        f"MAXIMUM SPOKEN LENGTH: {budget} characters, including spaces and punctuation. "
        "Use one or two complete sentences. Output only spoken words, no speaker label or directions.\n"
        "Do not claim another person's first-person experiences or actions as your own. "
        "Do not invent observations, prices, times or facts. A brief deliberate quote must lead to new content. "
        "Do not copy a preceding sentence wholesale.\n"
        f"PRECEDING SPEAKER SAID: {request.get('preceding_text') or ''}\n"
        f"REMAINING MATERIAL: {request.get('remaining_ideas') or ''}\n"
        f"ROLLED DIRECTIONS: {_creative_directions(request.get('directions'), level)}\n"
        f"FEELING: {request.get('es') or ''}\n"
        f"RESPONSE: {request.get('rs') or ''}\n"
        f"ASSIGNED PURPOSE (instructions only): {request.get('original_purpose') or ''}\n"
        f"RECENT SPOKEN EXCHANGE: {request.get('previous_turns') or ''}\n"
        + (f"PREVIOUS ATTEMPT FAILED: {rejection}\n" if rejection else "")
    )
    variation = {}
    if recovery:
        lines = prompt.splitlines()
        context_start = next((i for i, line in enumerate(lines) if line.startswith("PRECEDING SPEAKER SAID:")), len(lines))
        body, variation = _recovery_blocks(request, [(str(i), line) for i, line in enumerate(lines[context_start:])])
        prompt = "\n".join(lines[:context_start]) + "\n" + body + "\n"
    receipt = {"prompt": prompt, "requested_chars": budget, "kind": "dialogue handoff",
               "mode": mode, "at": time.time(), "raw_result": "", "clean_result": "", "recovery": variation}
    request["writing_receipt"] = receipt
    raw = await ask(prompt, limit=max(160, min(1200, budget * 2)), spice=0.45, num_ctx=16384,
                    mark={"kind": "dialogue handoff", "turn_id": request.get("turn_id"),
                          "parent_turn_id": request.get("parent_turn_id"), "mode": mode})
    receipt["raw_result"] = str(raw or "")
    label = re.escape(str(request.get("name") or "\x00"))
    words = re.sub(r"^\s*(?:[ABCDE]|" + label + r")\s*:\s*", "", str(raw or ""), count=1, flags=re.I)
    words = " ".join(str(clean(words) or "").split())
    receipt["clean_result"] = words
    return words


def apply_script_result(entry: dict[str, Any], result: dict[str, Any], invalidate: Any) -> str:
    """Invalidate every old take and remap index-based source metadata."""
    script = "\n".join(f"{seat}: {text}" for seat, text in result.get("rows") or [])
    before = str(entry.get("script") or "")
    if result.get("changed"):
        entry.setdefault("handoff_source", {"script": before, "use": entry.get("use"),
                                            "script_plain": entry.get("script_plain"),
                                            "script_tinted": entry.get("script_tinted")})
        invalidate(entry)
        entry["script"] = script
        if entry.get("use") == "tinted":
            entry["script_tinted"] = script
        elif entry.get("script_plain") is not None:
            entry["script_plain"] = script
        entry["lines"] = len(result.get("rows") or [])
        old_ids, new_ids = result.get("original_turn_ids") or [], result.get("turn_ids") or []
        if old_ids and new_ids:
            moved = {str(i): str(new_ids.index(tid)) for i, tid in enumerate(old_ids) if tid in new_ids}
            for field in ("turn_source", "turn_dice"):
                if isinstance(entry.get(field), dict):
                    entry[field] = {moved[str(k)]: value for k, value in entry[field].items() if str(k) in moved}
            for topic in entry.get("topics") or []:
                if isinstance(topic, dict) and str(topic.get("at_turn")) in moved:
                    topic["at_turn"] = int(moved[str(topic["at_turn"])])
    entry["handoff_receipt"] = {
        "version": 1, "source_digest": text_digest(before),
        "final_digest": text_digest(script if result.get("changed") else before),
        "status": result.get("status"), "changed": bool(result.get("changed")),
        "policy_hash": result.get("policy_hash"), "traces": copy.deepcopy(result.get("traces") or []),
    }
    return script if result.get("changed") else before


def source_clip_matches(entry: dict[str, Any], row: dict[str, Any]) -> bool:
    return text_digest(entry.get("opening")) == text_digest(row.get("text"))


def clip_matches_row(clip: dict[str, Any], row: dict[str, Any]) -> bool:
    return (clip.get("spoken_digest") == text_digest(row.get("text"))
            and clip.get("spoken_turn_id") == (row.get("stamp") or {}).get("turn_id"))


def stamp_clip(clip: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    return dict(clip, spoken_digest=text_digest(row.get("text")),
                spoken_turn_id=(row.get("stamp") or {}).get("turn_id"))


def receipt_matches_script(entry: dict[str, Any]) -> bool:
    receipt = entry.get("handoff_receipt") or {}
    return (receipt.get("version") == 1
            and receipt.get("status") in ("ready", "disabled")
            and receipt.get("final_digest") == text_digest(entry.get("script")))


def tint_cut_receipt(entry: dict[str, Any], parse: Any) -> dict[str, Any] | None:
    """Prove the active tint's omissions without guessing identities by seat.

    The tint records a source hash and selected output for EVERY source row.
    A cut counts only when that complete record exactly explains the active
    script; abandoned progress and cuts from a former version cannot qualify.
    """
    review = (entry.get("tint") or {}).get("review_turns") or []
    if entry.get("use") != "tinted" or not any(isinstance(r, dict) and r.get("cut") for r in review):
        return None
    names = (str(entry.get("caller_name") or ""), str(entry.get("caller2_name") or ""))
    source = parse(str(entry.get("script_plain") or ""), *names)
    active = parse(str(entry.get("script") or ""), *names)
    if len(review) != len(source) or not source:
        raise ValueError("the tint cut receipt does not cover every source turn")
    expected, cuts = [], []
    for index, ((seat, text), row) in enumerate(zip(source, review)):
        digest = hashlib.sha1(str(text).encode("utf-8", "ignore")).hexdigest()
        if not isinstance(row, dict) or row.get("marker") != seat or row.get("source") != digest:
            raise ValueError("the tint cut receipt differs from its source turn")
        if row.get("cut"):
            if str(row.get("rejected_source") or "") != str(text):
                raise ValueError("the tint cut receipt lacks its rejected source")
            cuts.append(index)
        else:
            expected.append((seat, str(row.get("text") or "")))
    # Compare through the station parser, which performs the same spoken
    # cleaning on both the active script and the progress record.
    expected = parse("\n".join("%s: %s" % row for row in expected), *names)
    if active != expected:
        raise ValueError("the active script does not match the proven tint cuts")
    return {"source_rows": source, "cut_indexes": cuts, "output_rows": active}
