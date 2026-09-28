"""[s3-banks-roll] THE RE-AIR GATE: which banked rounds may ever go out again.

A banked round that has already aired goes out again only on the roulette
(bank.reair, then bank.reair_pick among the rested ones). This gate is asked
FIRST, before any roll is made: a broken round never goes out again, whatever
the dice would say. Measured 2026-09-28: banter round ef39853f9fa54974 - 26
turns, seven replans, verdict "partial" 0.695, turns that copy each other
(t07 == t09, t16 ~ t18 ~ t20) and one with a slur - aired seven times in 17
hours off the larder's serve, and the census found a dozen more like it.

A round is never eligible to go out again when it has any of:

  a mark         data/reair_ineligible.json - written by tools/reair_sweep.py
                 --apply (the one-time sweep), read here by the round's
                 conversation, by its words, or (a finished call) by its id;
  non_compliant  System 3's verdict on the conversation, as the round's stamp
                 carries it;
  turnchain flags turns the copy gate at the turn - the turnchain gate,
                 [s3-turnchain], LIVE since 2026-09-28 - caught, dropped,
                 trimmed or held: the round's stamp carries its counts
                 (system3.gate_counts, the stamp's "gate"; a conversation's
                 own record is "turn_gate"; its observations are events of
                 family GATE, which the sweep reads too), and any older
                 speculative flag list is still honoured;
  an echo loop   System 3's own validation rule (system3._echoes): three or
                 more turns, and a quarter of the round, that parrot one of the
                 four turns before them;
  copied turns   a turn more than 90% like an EARLIER turn of the same round -
                 compared after the trailing row number and the punctuation go
                 (the census's rule: turns of 12 characters or more).

Pure functions over a stored row: the station (app.py), System2's dispatcher
(through app.py), the sweep and the tests all ask the same ones. A FIRST
airing is not this gate's question - the copy gate at the turn guards that.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import threading
import time
from typing import Any

COPY_RATIO = 0.9            # "more than 0.9 similar to an earlier turn"
COPY_MIN_CHARS = 12         # shorter turns ("Yeah.", "Go on.") are not copies
MARKS_VERSION = 1
MEMO_MOST = 4000

_MARKER = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 .'_-]{0,39}?)\s*:\s+(.*\S)\s*$")
_TRAILING_NUMBER = re.compile(r"\s+\d+\s*$")
_NON_WORD = re.compile(r"[^a-z0-9 ]+")
_MEMO: dict[Any, str] = {}
_MEMO_LOCK = threading.Lock()


def norm(text: Any) -> str:
    """A turn's words as the comparison reads them: lower case, no trailing
    row number (a writer's "... 11"), no punctuation, single spaces."""
    s = _TRAILING_NUMBER.sub("", str(text or "").lower())
    return " ".join(_NON_WORD.sub(" ", s).split())


def entry_of(row: Any) -> dict[str, Any]:
    """The round's own record: a shelf row's `entry`, else the row itself
    (a larder entry, a call-log row)."""
    if not isinstance(row, dict):
        return {}
    got = row.get("entry")
    return got if isinstance(got, dict) else row


def stamp_of(row: Any) -> dict[str, Any]:
    """The System 3 stamp the round carries ({} for none)."""
    for holder in (entry_of(row), row if isinstance(row, dict) else {}):
        got = holder.get("system3") if isinstance(holder, dict) else None
        if isinstance(got, dict):
            return got
    return {}


def script_turns(script: Any) -> list[tuple[str, str]]:
    """(speaker, words) per turn of a script written "A: ..." a line (a
    marker or a caller's name before the colon); a line with no speaker
    carries on the turn above it."""
    out: list[tuple[str, str]] = []
    for line in str(script or "").splitlines():
        if not line.strip():
            continue
        m = _MARKER.match(line)
        if m:
            out.append((m.group(1).strip(), m.group(2).strip()))
        elif out:
            who, said = out[-1]
            out[-1] = (who, (said + " " + line.strip()).strip())
    return out


def turns_of(row: Any) -> list[tuple[str, str]]:
    """The turns the round would say: its script's turns; a finished call's
    transcript; else its recorded takes in order; else its one line."""
    entry = entry_of(row)
    turns = script_turns(entry.get("script") or entry.get("script_plain") or "")
    if turns:
        return turns
    transcript = (row or {}).get("transcript") if isinstance(row, dict) else None
    if isinstance(transcript, list) and transcript:
        return [(str(t.get("who") or t.get("name") or ""), str(t.get("text") or ""))
                for t in transcript if isinstance(t, dict) and str(t.get("text") or "").strip()]
    takes = [t for t in (entry.get("takes") or []) if isinstance(t, dict) and str(t.get("text") or "").strip()]
    if takes:
        takes.sort(key=lambda t: int(t.get("i") or 0) if str(t.get("i") or "0").lstrip("-").isdigit() else 0)
        return [(str(t.get("who") or ""), str(t.get("text") or "")) for t in takes]
    text = str(entry.get("text") or "").strip()
    return [(str(entry.get("who") or ""), text)] if text else []


def _similar(a: str, b: str) -> bool:
    if a == b:
        return True
    la, lb = len(a), len(b)
    # ratio = 2M / (la + lb) and M <= min(la, lb): past this length gap no
    # pair can reach the threshold, so it is never measured
    if 2.0 * min(la, lb) / float(la + lb) <= COPY_RATIO:
        return False
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return (sm.real_quick_ratio() > COPY_RATIO and sm.quick_ratio() > COPY_RATIO
            and sm.ratio() > COPY_RATIO)


def copied_turns(turns: list[tuple[str, str]]) -> list[tuple[int, int]]:
    """(turn, the earlier turn it copies) for every turn more than 90% like
    an earlier turn of the same round."""
    texts = [norm(t) for _w, t in turns]
    out: list[tuple[int, int]] = []
    for i, s in enumerate(texts):
        if len(s) < COPY_MIN_CHARS:
            continue
        for j in range(i):
            p = texts[j]
            if len(p) >= COPY_MIN_CHARS and _similar(s, p):
                out.append((i, j))
                break
    return out


def _echoes_local(final_turns: list[tuple[str, str]]) -> list[int]:
    """system3._echoes, for a process that cannot import the engine: the
    same rule, word for word."""
    seen: list[tuple[set, str]] = []
    out: list[int] = []
    for i, (_who, text) in enumerate(final_turns):
        words = re.findall(r"[a-z0-9']+", str(text or "").lower())
        here = set(words)
        key = " ".join(words)
        if words:
            for prev, prev_key in seen[-4:]:
                if not prev:
                    continue
                small = min(len(here), len(prev))
                if key == prev_key or (small <= 8 and len(here & prev) >= 0.8 * small):
                    out.append(i)
                    break
        seen.append((here, key))
    return out


def echo_loop(turns: list[tuple[str, str]]) -> tuple[list[int], bool]:
    """System 3's own echo rule over the round's turns: (echoing turns,
    loop). A loop is three or more echoes and a quarter of the round."""
    try:
        import system3                                  # the engine's one definition
        echo = list(system3._echoes(turns))
    except Exception:  # noqa: BLE001 - the same rule, carried here
        echo = _echoes_local(turns)
    return echo, (len(echo) >= 3 and len(echo) >= 0.25 * max(1, len(turns)))


def copy_gate_flags(row: Any) -> list[Any]:
    """Turns the copy gate at the turn flagged on this round, if the round
    carries them (read, never required): a list under one of the names a
    flagging road would use, on the stamp or on the round."""
    found: list[Any] = []
    for holder in (stamp_of(row), entry_of(row)):
        if not isinstance(holder, dict):
            continue
        for key in ("copy_gate", "copy_flags", "copied_turns", "turn_copies", "copies"):
            got = holder.get(key)
            if isinstance(got, dict):
                got = got.get("turns") or got.get("flagged") or got.get("copied") or []
            if isinstance(got, list):
                found.extend(x for x in got if x not in (None, "", False))
    return found


def turnchain_record(row: Any) -> dict[str, Any]:
    """The turnchain gate's record on this round ([s3-turnchain]): the counts
    the stamp carries ("gate", system3.gate_counts - caught / rewritten /
    dropped / trimmed / visits / held / in_chain), else the conversation's own
    "turn_gate" record when the row holds the conversation. {} for none."""
    for holder in (stamp_of(row), entry_of(row), row if isinstance(row, dict) else {}):
        if not isinstance(holder, dict):
            continue
        for key in ("gate", "turn_gate"):
            got = holder.get(key)
            if isinstance(got, dict) and got:
                return got
    return {}


def turnchain_refusal(record: Any) -> str:
    """Why the turnchain gate's record retires a round, or "": it held the
    round, or it flagged turns (caught, dropped, trimmed - in the walk at the
    bind or in the beat chain). A record of zeros is a clean walk."""
    if not isinstance(record, dict) or not record:
        return ""
    held = str(record.get("held") or "")
    if held:
        return "the turnchain gate held the round: %s" % held[:120]
    counts: list[tuple[str, int]] = []
    for key in ("caught", "dropped", "trimmed"):
        try:
            n = int(record.get(key) or 0)
        except (TypeError, ValueError):
            n = 0
        if n > 0:
            counts.append((key, n))
    chain = record.get("in_chain")
    if isinstance(chain, dict):
        chain = chain.get("caught", 0)
    try:
        chain = int(chain or 0)
    except (TypeError, ValueError):
        chain = 0
    if chain > 0:
        counts.append(("in the beat chain", chain))
    if counts:
        return "the turnchain gate flagged its turns (%s)" % ", ".join(
            "%s %d" % (k, n) for k, n in counts)
    return ""


def _words_key(row: Any) -> tuple:
    """A cheap identity for the round's words: its script string's own
    (cached) hash and length - no parse - or, for a round with no script,
    a digest of the turns it would say."""
    entry = entry_of(row)
    script = entry.get("script") or entry.get("script_plain") or ""
    if isinstance(script, str) and script:
        return ("s", hash(script), len(script))
    said = json.dumps(turns_of(row), default=str)
    return ("t", hashlib.sha1(said.encode("utf-8")).hexdigest())


def script_sha(row: Any) -> str:
    """The round's words, hashed the way a mark names a round that has no
    System 3 stamp (memoised by the words' cheap identity)."""
    key = ("sha",) + _words_key(row)
    with _MEMO_LOCK:
        if key in _MEMO:
            return _MEMO[key]
    said = "\n".join(norm(t) for _w, t in turns_of(row))
    got = hashlib.sha1(said.encode("utf-8")).hexdigest()[:16] if said else ""
    with _MEMO_LOCK:
        _MEMO[key] = got
    return got


def mark_keys(row: Any, cid: str = "") -> list[str]:
    """Every name a mark may have been written under for this round."""
    keys = []
    conv = str(cid or stamp_of(row).get("conversation_id") or "")
    if conv:
        keys.append("cid:" + conv)
    if isinstance(row, dict) and row.get("transcript") is not None and row.get("id"):
        keys.append("call:" + str(row.get("id")))
    sha = script_sha(row)
    if sha:
        keys.append("sha:" + sha)
    return keys


def _memo_key(row: Any) -> tuple:
    stamp = stamp_of(row)
    return ("why", str(stamp.get("conversation_id") or ""), str(stamp.get("verdict") or ""),
            repr(copy_gate_flags(row)), repr(sorted(turnchain_record(row).items(), key=repr))
            ) + _words_key(row)


def content_refusal(row: Any) -> str:
    """Why this round may never go out again by what it IS - its verdict,
    the turnchain gate's flags, its echoes, its copied turns - or "" (memoised by
    its words and stamp, so a shelf walk asks it for the price of a hash)."""
    key = _memo_key(row)
    with _MEMO_LOCK:
        if key in _MEMO:
            return _MEMO[key]
    why = ""
    stamp = stamp_of(row)
    turns = turns_of(row)
    if str(stamp.get("verdict") or "") == "non_compliant":
        why = "System 3's verdict on it is non_compliant"
    if not why:
        flags = copy_gate_flags(row)
        if flags:
            why = "the copy gate flagged %d of its turns (%s)" % (
                len(flags), ", ".join(str(f)[:24] for f in flags[:4]))
    if not why:
        why = turnchain_refusal(turnchain_record(row))
    if not why and len(turns) >= 2:
        echo, loop = echo_loop(turns)
        if loop:
            why = "an echo loop - %d of its %d turns parrot one of the four before them" % (
                len(echo), len(turns))
    if not why and len(turns) >= 2:
        copies = copied_turns(turns)
        if copies:
            why = "copied turns - %d of its %d turns copy an earlier turn (%s)" % (
                len(copies), len(turns),
                ", ".join("turn %d = turn %d" % (i + 1, j + 1) for i, j in copies[:4]))
    with _MEMO_LOCK:
        _MEMO[key] = why
        while len(_MEMO) > MEMO_MOST:
            _MEMO.pop(next(iter(_MEMO)))
    return why


def mark_of(row: Any, marks: dict[str, Any] | None, cid: str = "") -> Any:
    """The sweep's mark on this round, if any - by its conversation, its
    finished call's id, then (only when the marks hold any) its words."""
    if not marks:
        return None
    conv = str(cid or stamp_of(row).get("conversation_id") or "")
    got = marks.get("cid:" + conv) if conv else None
    if not got and isinstance(row, dict) and row.get("transcript") is not None and row.get("id"):
        got = marks.get("call:" + str(row.get("id")))
    if not got and any(str(k).startswith("sha:") for k in marks):
        sha = script_sha(row)
        got = marks.get("sha:" + sha) if sha else None
    return got


def refusal(row: Any, marks: dict[str, Any] | None = None, cid: str = "") -> str:
    """Why this stored round may never go out again, or "" when it may (the
    roulette still decides whether it does)."""
    got = mark_of(row, marks, cid)
    if got:
        why = got.get("why") if isinstance(got, dict) else got
        return "marked ineligible by the sweep%s" % (": " + str(why) if why else "")
    return content_refusal(row)


# --- the marks file (tools/reair_sweep.py writes it; the station reads it) -------------
def load_marks(path: Any) -> dict[str, Any]:
    """{mark key: {why, ...}} - {} for a file that is missing or unreadable."""
    try:
        with open(path, encoding="utf-8") as fh:
            got = json.load(fh)
    except Exception:  # noqa: BLE001
        return {}
    rounds = got.get("rounds") if isinstance(got, dict) else None
    return {str(k): v for k, v in rounds.items()} if isinstance(rounds, dict) else {}


def save_marks(path: Any, marks: dict[str, Any], by: str = "tools/reair_sweep.py") -> None:
    """Atomically (a temp file, then a rename), LF, beside the file."""
    body = {"version": MARKS_VERSION, "written_at": round(time.time(), 3), "by": by,
            "rule": "a round marked here never goes out again (the re-air gate, reair_gate.py)",
            "rounds": marks}
    path = str(path)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(body, fh, indent=1, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)
