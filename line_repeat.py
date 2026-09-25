"""Read-only repeat evidence. Publication is not proof of playback."""

from collections import Counter
import hashlib
import json
import math
import re

from line_blacklist import _key


def normalize(text):
    return _key(str(text or ""))


def fingerprint(text):
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def number(value):
    try:
        result = float(value or 0)
        return result if math.isfinite(result) else 0.0
    except (TypeError, ValueError):
        return 0.0


def script_contains(script, text):
    """Compare complete turns, never prefixes or substrings of another line."""
    wanted = normalize(text)
    if not wanted:
        return False
    for turn in str(script or "").splitlines():
        turn = re.sub(r"^\s*(?:[A-E]|HOST|COHOST|CO-HOST|DJ|CALLER\d*|GUEST|THIRD)\s*:\s*",
                      "", turn, flags=re.I)
        if normalize(turn) == wanted:
            return True
    return normalize(script) == wanted


def read_calls(path, since, max_bytes=32 * 1024 * 1024):
    """Bound inspection I/O independently of the live telemetry ledger."""
    rows = []
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            clipped = size > max_bytes
            handle.seek(max(0, size - max_bytes))
            if clipped:
                handle.readline()
            for line in handle:
                try:
                    row = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    continue
                if isinstance(row, dict) and number(row.get("at")) >= since:
                    rows.append(row)
    except FileNotFoundError:
        return [], False
    return rows, clipped


def analyze(text, rows, calls, now):
    """Fold line updates by identity; separate receipts from queued occurrences."""
    key = fingerprint(text)
    found = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("repeat_text_key", fingerprint(row.get("text", ""))) != key:
            continue
        identity = str(row.get("id") or "")
        if not identity:
            continue  # No identity means we cannot deduplicate a receipt safely.
        previous = found.get(identity, {})
        merged = {**previous, **row}
        # A stale snapshot must not erase a durable hearing stamp.
        merged["heard_ack_at"] = max(number(previous.get("heard_ack_at")),
                                     number(row.get("heard_ack_at")))
        found[identity] = merged
    matches = sorted(found.values(), key=lambda r: number(
        r.get("heard_ack_at") or r.get("air_at") or r.get("ts")), reverse=True)
    since = now - 86400
    played = [r for r in matches if since <= number(r.get("heard_ack_at")) <= now
              and r.get("heard_ack_by") != "set"]
    recent = [r for r in matches if since <= number(r.get("air_at") or r.get("ts")) <= now]
    unconfirmed = [r for r in recent if not number(r.get("heard_ack_at"))
                   and r.get("aired") in ("published", "stream", "both", "box", "page", "airing")]
    prompts = {}
    for call in calls:
        if not isinstance(call, dict) or not script_contains(call.get("script"), text):
            continue
        at = number(call.get("at"))
        if not now - 172800 <= at <= now:
            continue
        prompt = str(call.get("prompt") or "")
        identity = (at, str(call.get("model") or ""), str(call.get("kind") or ""))
        if identity in prompts and len(prompts[identity]["prompt"]) >= len(prompt):
            continue
        prompts[identity] = {
            "at": at, "kind": str(call.get("kind") or ""),
            "model": str(call.get("model") or ""), "prompt": prompt,
            "prompt_hash": fingerprint(prompt) if prompt else "",
            "temp": call.get("temp"), "seed": call.get("seed"),
            "alternative": call.get("segprompt"),
            "truncated": bool(call.get("repeat_truncated")),
            "evidence": "Complete dialogue text found in this model response; not an ID-bound causal link.",
        }
    iterations = sorted(prompts.values(), key=lambda r: r["at"], reverse=True)
    media = Counter(str(r.get("clip_media") or r.get("media")) for r in played
                    if r.get("clip_media") or r.get("media"))
    hashes = Counter(r["prompt_hash"] for r in iterations if r["prompt_hash"])
    causes = []
    if media and max(media.values()) > 1:
        causes.append("The same recording has confirmed playback under multiple line IDs. Prepared audio is being reused.")
    if len(iterations) > 1:
        causes.append("Multiple recorded model responses contain this complete line; repetition also occurs during writing.")
    if hashes and max(hashes.values()) > 1:
        causes.append("Repeated writing attempts share an unchanged normalized prompt. Check the prompt and its material selection.")
    if not causes:
        causes.append("The retained evidence does not establish a repeat mechanism for this line.")
    return {
        "played_24h": len(played), "occurrences_24h": len(recent),
        "published_unconfirmed_24h": len(unconfirmed),
        "retained_occurrences": len(matches), "writing_iterations": len(iterations),
        "causes": causes, "iterations": iterations[:30],
        "omitted_iterations": max(0, len(iterations) - 30),
        "history": [{k: r.get(k) for k in (
            "id", "sid", "ts", "air_at", "heard_ack_at", "heard_ack_by",
            "aired", "kind", "round", "source", "media", "clip_media")}
                    for r in matches[:200]],
        "omitted_history": max(0, len(matches) - 200),
        "coverage": "Retained 48-hour ledger plus live records. Plays count distinct line IDs with audible-progress receipts, not publication, listeners, or scheduled rows. Legacy missing receipts and same-ID manual replays cannot be counted. Older prompts and long truncated lines may be unavailable.",
    }
