"""Dialogue recovery decisions without station imports, I/O, or a clock.

State is JSON-compatible and belongs to one dialogue choice. Callers supply time,
own the state lock, and finish every allowed attempt with ``note_failure`` or
``note_success``. No mutable scheduler or random generator is shared globally.
"""
from __future__ import annotations

import math
import hashlib
import json
import random
import re


OPERATIONS = ("repair", "rewrite", "reroll", "rebuild")
DEFAULT_RECOVERY = {
    "enabled": True,
    "attempts_per_pass": 3,
    "repeat_stuck": 2,
    "cooldown_seconds": 60.0,
    "max_attempt_seconds": 300.0,
    "priority_boost_cap": 6.0,
    "failure_priority_boost": 2.0,
    "aging_seconds": 300.0,
    "trace_limit": 32,
}
_RELAXATIONS = ("rhyme", "length", "style")
_TOPIC_MASK = 0x9E3779B97F4A7C15


def failure_feedback(reason):
    """Map validator failures to specific repairs; unknowns stay explicit.

    This classifies observed wording, not the creative intent of a node.
    It never changes source ownership, admits invalid copy, or invents facts.
    """
    text = " ".join(str(reason or "").casefold().split())
    if not text:
        category, action, instruction = "none", "write", "Follow the current plan and all source requirements."
    elif "protected turn has no identified exact wording" in text:
        category, action, instruction = "source_missing", "restore_source", "Restore the required exact wording from identified source evidence before writing. Random wording cannot replace it."
    elif any(p in text for p in ("source identities", "different speaker", "different planned speaker", "matching planned identity", "immutable recovery identity", "approved turn identities", "exact copy-gate source receipt", "invalid source indexes", "active tint receipt", "active tint cut receipt", "proven tinted survivors", "immutable identified turn")):
        category, action, instruction = "source_identity", "repair_identity_evidence", "Validate the original source-to-turn identities and receipt revision before writing. Do not guess ownership from repeated speaker labels or transfer exact wording to a different turn."
    elif "closing" in text:
        category, action, instruction = "closing", "complete_closing", "Complete the assigned final closing and its required conclusion. Give it an audible ending such as 'leave it there', 'back to', or 'thanks' only when appropriate to the assigned node. Keep required facts and the planned closing speaker; do not open another topic at the end."
    elif any(p in text for p in ("output budget", "length budget", "over budget", "over-budget", "exceeds", "too long", "hard_chars")):
        category, action, instruction = "budget", "shorten_mutable_copy", "Shorten only mutable wording into complete, concise thoughts within the supplied per-turn limits. Retain every required turn, fact, conclusion and exact source passage."
    elif any(p in text for p in ("rows must align", "copy review needs every planned turn", "unlabelled", "unplanned dialogue", "required turn keys", "repeats a turn key", "another speaker label", "empty or not spoken text", "cleaning removed", "labelled dialogue script", "handoff rows must be nonempty")):
        category, action, instruction = "turn_structure", "enforce_turn_contract", "Return exactly the mutable turn keys in the output schema, once each, with nonempty spoken words and no embedded speaker labels. The system supplies protected rows and the final planned speaker order. Never omit a required leg."
    elif any(p in text for p in ("timeout", "timed out", "lease expired", "connection", "unavailable", "admission", "service")):
        category, action, instruction = "service", "recover_service", "Check the failed writer, voice or delivery dependency. A new creative prompt does not repair a service failure."
    elif any(p in text for p in ("copy gate", "direction aloud", "direction echo", "running-order direction", "reanchor", "duplicate dialogue", "off brief", "off-brief", "topic continuity", "fact", "character", "coherence")):
        category, action, instruction = "coherence", "rewrite_grounded_copy", "Write spoken dialogue that answers the actual preceding turn and fulfills the assigned purpose. Use only grounded facts; do not say production instructions aloud or repeat earlier lines. Optional style may yield to clarity."
    else:
        category, action, instruction = "other", "inspect_and_rewrite", "Address the specific previous rejection while retaining all required turns, identities and source facts. The failure has not yet been classified; do not treat it as a proven roulette problem."
    return {"category": category, "action": action, "instruction": instruction,
            "creative_retry": category in ("closing", "budget", "turn_structure", "coherence", "other")}


def _time(now):
    now = float(now)
    if not math.isfinite(now):
        raise ValueError("recovery time must be finite")
    return now


def _policy(changes=None):
    policy = {**DEFAULT_RECOVERY, **(changes or {})}
    for key in ("attempts_per_pass", "repeat_stuck", "trace_limit"):
        value = int(policy[key])
        if value < 1 or value != policy[key]:
            raise ValueError("%s must be a positive integer" % key)
        policy[key] = value
    if policy["attempts_per_pass"] > len(OPERATIONS):
        raise ValueError("a recovery pass cannot repeat operations")
    for key in ("cooldown_seconds", "max_attempt_seconds", "priority_boost_cap",
                "failure_priority_boost", "aging_seconds"):
        value = float(policy[key])
        if not math.isfinite(value) or value < 0:
            raise ValueError("%s must be finite and nonnegative" % key)
        policy[key] = value
    if not policy["aging_seconds"]:
        raise ValueError("aging_seconds must be positive")
    if not policy["max_attempt_seconds"]:
        raise ValueError("max_attempt_seconds must be positive")
    policy["enabled"] = bool(policy["enabled"])
    return policy


def _defaults(policy=None):
    return {
        "version": 1,
        "policy": _policy(policy),
        "active": False,
        "in_flight": False,
        "pass": 1,
        "attempt": 0,
        "total_attempts": 0,
        "next_operation": 0,
        "operations_in_pass": [],
        "failures": 0,
        "style_failures": 0,
        "failure_counts": {},
        "last_reason": "",
        "last_reason_key": "",
        "same_reason_count": 0,
        "stuck": False,
        "style_level": 0,
        "first_failure_at": None,
        "last_failure_at": None,
        "last_success_at": None,
        "cooldown_until": 0.0,
        "current_attempt": None,
        "started_at": None,
        "trace": [],
        "source_fingerprint": "",
        "source_fingerprints": {},
        "source_hold": False,
    }


def recovery_state(container, policy=None):
    """Return the choice's persisted recovery state, filling missing defaults.

    ``policy`` overrides existing policy values; omitted values are preserved.
    It must cap attempts at four so a pass always uses different operations.
    """
    evidence = {key: container.get(key) for key in ("script", "source_turn_ids", "protected", "turns") if key in container}
    fingerprint = hashlib.sha256(json.dumps(evidence, sort_keys=True, default=str).encode()).hexdigest()
    scope = "conversation" if "turns" in container else "entry"
    state = container.get("dialogue_recovery")
    if not isinstance(state, dict):
        state = _defaults(policy)
        container["dialogue_recovery"] = state
        state["source_fingerprint"] = fingerprint
        state["source_fingerprints"][scope] = fingerprint
        return state
    for key, value in _defaults().items():
        state.setdefault(key, value)
    state["policy"] = _policy({**state["policy"], **(policy or {})})
    previous = state["source_fingerprints"].get(scope)
    if previous and previous != fingerprint and needs_source(state):
        state.update(source_hold=False, last_reason="", last_reason_key="", same_reason_count=0, cooldown_until=0)
    state["source_fingerprint"] = fingerprint
    state["source_fingerprints"][scope] = fingerprint
    return state


def needs_source(state):
    """Randomness cannot invent missing mandatory exact source wording."""
    return bool(state.get("source_hold") or "protected turn has no identified exact wording" in str(state.get("last_reason") or "").lower())


def _trace(state, event):
    trace = state.setdefault("trace", [])
    trace.append(event)
    del trace[:-state["policy"]["trace_limit"]]


def _random(state, now, rng):
    # Explicit time/counter seeding gives a standalone fallback without reading
    # a clock or OS entropy. A supplied RNG allows reproducible tests or a
    # station-owned random source.
    return rng if rng is not None else random.Random(
        "%s:%s:%s" % (now, state.get("total_attempts", 0), state.get("pass", 1)))


def _decision(state, *, allow, reason="", **changes):
    return {
        "allow": allow,
        "reason": reason,
        "failure_feedback": failure_feedback(reason or state.get("last_reason")),
        "operation": "",
        "variation_id": "",
        "seed": None,
        "topic_seed": None,
        "stuck": bool(state["stuck"]),
        "pass": state["pass"],
        "attempt": state["attempt"],
        "style_level": state["style_level"],
        "relax": list(_RELAXATIONS[:state["style_level"]]),
        "preserve_speakers": True,
        "preserve_character": True,
        "preserve_coherence": True,
        "cooldown_until": state["cooldown_until"],
        "started_at": state["started_at"],
        **changes,
    }


def begin_attempt(state, now, reason="", rng=None):
    """Reserve one fresh variation, or explain why it cannot run yet.

    Rejections belong in ``note_failure``; ``reason`` is only an instruction
    hint. Three failed operations trigger cooldown, with no lifetime retry cap.
    The operation cursor continues across passes instead of repeating the first
    three steps forever. An in-flight reservation prevents overlapping retries.
    """
    now = _time(now)
    policy = state["policy"]
    if needs_source(state):
        return _decision(state, allow=False, reason="required exact source wording is missing; waiting for corrected source evidence")
    if not policy["enabled"]:
        return _decision(state, allow=False, reason="recovery disabled")
    if state["in_flight"]:
        started_at = state.get("started_at")
        if started_at is not None and now - float(started_at) < policy["max_attempt_seconds"]:
            return _decision(state, allow=False, reason="recovery attempt in progress")
        # A persisted owner may have disappeared during a restart. The caller
        # can still guard its model job; this lease keeps stale metadata from
        # leaving the choice permanently locked. Optional variation IDs on
        # outcomes stop a late old worker from finishing the replacement.
        _trace(state, {"event": "lease_expired", "at": now})
        note_failure(state, "recovery attempt lease expired", now)
    if now < state["cooldown_until"]:
        return _decision(state, allow=False, reason="recovery cooldown")
    if state["attempt"] >= policy["attempts_per_pass"]:
        state["pass"] += 1
        state["attempt"] = 0
        state["operations_in_pass"] = []
        state["cooldown_until"] = 0.0

    operation_index = int(state["next_operation"]) % len(OPERATIONS)
    # This also handles a caller shortening its policy midway through a pass.
    while OPERATIONS[operation_index] in state["operations_in_pass"]:
        operation_index = (operation_index + 1) % len(OPERATIONS)
    operation = OPERATIONS[operation_index]
    state["next_operation"] = (operation_index + 1) % len(OPERATIONS)
    state["operations_in_pass"].append(operation)
    state["attempt"] += 1
    state["total_attempts"] += 1
    serial = state["total_attempts"]
    entropy = _random(state, now, rng).getrandbits(64)
    # The serial is outside the random portion: even identical RNG output
    # cannot repeat a seed, including after success or cooldown.
    seed = (serial << 64) | entropy
    result = _decision(state, allow=True, reason=str(reason or state["last_reason"]),
                       operation=operation,
                       variation_id="dj-%08x-%016x" % (serial, entropy),
                       seed=seed, topic_seed=seed ^ _TOPIC_MASK)
    state["active"] = True
    state["in_flight"] = True
    state["started_at"] = now
    result["started_at"] = now
    state["current_attempt"] = dict(result)
    _trace(state, {"event": "attempt", "at": now,
                   "operation": operation, "variation_id": result["variation_id"],
                   "pass": state["pass"], "attempt": state["attempt"]})
    return result


def rejection_key(reason):
    """Identify a logical rejection despite changing IDs and numeric details."""
    key = " ".join(str(reason or "").casefold().split())
    key = re.sub(r"\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b", "<id>", key)
    key = re.sub(r"\b(?:0x)?[0-9a-f]{16,}\b", "<id>", key)
    key = re.sub(
        r"\b(conversation|exchange|round|request|task|trace|turn|model|error)"
        r"(?:[_ -]?id)?\s*[:=#]\s*[a-z0-9_-]+\b", r"\1 <id>", key)
    key = re.sub(
        r"\b(conversation|exchange|round|request|task|trace|turn)"
        r"(?:[_ -]?id)?\s+(?=[a-z0-9_-]*\d)[a-z0-9_-]+\b", r"\1 <id>", key)
    return re.sub(r"\b\d+(?:\.\d+)?\b", "<n>", key)


def _matches_attempt(state, variation_id):
    return variation_id is None or variation_id == (
        state.get("current_attempt") or {}).get("variation_id")


def note_failure(state, reason, now, variation_id=None):
    """Record a rejection; identical consecutive reasons twice mean stuck.

    Whitespace/case changes do not count as a new reason. Empty unknown failures
    are recorded but cannot alone establish an identical-rejection streak.
    """
    now = _time(now)
    if not _matches_attempt(state, variation_id):
        return state
    reason = " ".join(str(reason or "").split())
    key = rejection_key(reason)
    old_key = state.get("last_reason_key") or rejection_key(state["last_reason"])
    same = bool(key and key == old_key)
    state["same_reason_count"] = state["same_reason_count"] + 1 if same else int(bool(reason))
    state["last_reason"] = reason
    state["last_reason_key"] = key
    state["source_hold"] = "protected turn has no identified exact wording" in reason.lower()
    feedback = failure_feedback(reason)
    category = feedback["category"]
    counts = state.setdefault("failure_counts", {})
    counts[category] = int(counts.get(category) or 0) + 1
    if category in ("coherence", "other"):
        state["style_failures"] = int(state.get("style_failures") or 0) + 1
    state["failures"] += 1
    state["stuck"] = state["same_reason_count"] >= state["policy"]["repeat_stuck"]
    state["style_level"] = min(len(_RELAXATIONS), max(int(state.get("style_failures") or 0), int(state.get("style_level") or 0) * 2) // 2)
    state["active"] = True
    state["in_flight"] = False
    state["started_at"] = None
    state["last_failure_at"] = now
    if state["first_failure_at"] is None:
        state["first_failure_at"] = now
    if state["attempt"] >= state["policy"]["attempts_per_pass"]:
        state["cooldown_until"] = now + state["policy"]["cooldown_seconds"]
    if state["same_reason_count"] >= 8 and state.get("current_attempt") and state["attempt"] >= state["policy"]["attempts_per_pass"]:
        state["cooldown_until"] = max(state["cooldown_until"], now + 300)
    attempt = state.get("current_attempt") or {}
    _trace(state, {"event": "failure", "at": now, "reason": reason,
                   "operation": attempt.get("operation", ""),
                   "category": category, "action": feedback["action"],
                   "variation_id": attempt.get("variation_id", ""),
                   "stuck": state["stuck"]})
    state["current_attempt"] = None
    return state


def note_success(state, now, variation_id=None):
    """Finish recovery and reset escalation, preserving seed serial and audit."""
    now = _time(now)
    if not _matches_attempt(state, variation_id):
        return state
    attempt = state.get("current_attempt") or {}
    _trace(state, {"event": "success", "at": now,
                   "operation": attempt.get("operation", ""),
                   "variation_id": attempt.get("variation_id", "")})
    keep = {"total_attempts": state["total_attempts"], "trace": state["trace"],
            "last_success_at": now, "failure_counts": state.get("failure_counts", {}).copy()}
    state.update(_defaults(state["policy"]))
    state.update(keep)
    return state


def note_deferred(state, now, variation_id=None):
    """Refund a reservation refused by admission before production began.

    This releases ownership without recording a rejection, consuming one of the
    three operations, advancing escalation, or reusing its variation seed.
    """
    now = _time(now)
    if not _matches_attempt(state, variation_id):
        return state
    attempt = state.get("current_attempt") or {}
    if not state["in_flight"] or not attempt:
        return state
    operation = attempt.get("operation")
    if operation in OPERATIONS:
        state["next_operation"] = OPERATIONS.index(operation)
    if state["operations_in_pass"] and state["operations_in_pass"][-1] == operation:
        state["operations_in_pass"].pop()
    state["attempt"] = max(0, state["attempt"] - 1)
    state["in_flight"] = False
    state["started_at"] = None
    state["current_attempt"] = None
    state["active"] = bool(state["failures"])
    _trace(state, {"event": "deferred", "at": now,
                   "operation": operation, "variation_id": attempt.get("variation_id", "")})
    return state


def _number(value, default=0.0):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def pick_recovery_candidate(candidates, last_was_recovery, now, rng=None):
    """Choose an eligible input candidate, alternating recovery with normal work.

    Candidates may provide ``runnable``, ``ready_at``, ``priority``, ``queued_at``
    and the persisted ``dialogue_recovery`` state. Failure and age raise recovery
    weight within a cap. Cooldown, disabled, and in-flight recovery is skipped;
    it never forces other runnable work to wait. Selection does not mutate input.
    """
    now = _time(now)
    recovering, normal = [], []
    for candidate in candidates:
        if candidate.get("runnable", True) is False:
            continue
        if _number(candidate.get("ready_at")) > now:
            continue
        state = candidate.get("dialogue_recovery") or {}
        if needs_source(state):
            continue
        recovery = bool(state.get("active") or state.get("failures", 0))
        policy = _policy(state.get("policy"))
        if recovery:
            started_at = state.get("started_at")
            live_attempt = state.get("in_flight") and started_at is not None and (
                now - _number(started_at) < policy["max_attempt_seconds"])
            if not policy["enabled"] or live_attempt or _number(state.get("cooldown_until")) > now:
                continue
        weight = max(1.0, _number(candidate.get("priority"), 1.0))
        if recovery:
            since = state.get("first_failure_at")
            if since is None:
                since = candidate.get("queued_at", now)
            age = max(0.0, now - _number(since, now)) / policy["aging_seconds"]
            failures = max(0.0, _number(state.get("failures")))
            weight += min(policy["priority_boost_cap"],
                          failures * policy["failure_priority_boost"] + age)
        (recovering if recovery else normal).append((candidate, weight))
    pool = normal if last_was_recovery and normal else recovering or normal
    if not pool:
        return None
    generator = rng if rng is not None else random.Random("pick:%s" % now)
    draw = generator.random() * sum(weight for _, weight in pool)
    for candidate, weight in pool:
        draw -= weight
        if draw < 0:
            return candidate
    return pool[-1][0]
