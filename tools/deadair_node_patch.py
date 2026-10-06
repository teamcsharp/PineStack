#!/usr/bin/env python3
"""[s3-deadair] The dead-air node. 2026-10-05, request #1571.

The operator: "We need to create and have priority nodes that fix and resolve
any dead air ... dead air nodes that roll a roulette for someone to insert a
quote, sfx clip, discussion topic, conversation redirect, response, banked
response, that doesnt decrement the roll or allowed increments that is simply
there for filling dead air."

What this adds to app.py:
  - s3_dead_air_node(): when the silence rescue finds the pair quiet and the
    cupboard has nothing to hand over, System 3 rolls (deadair.node, odds 1.0)
    whether a node steps in, WHO in the studio (deadair.who) and WHAT
    (deadair.kind - a desk category whose six rows can be weighted or switched
    off): a banked response, a quote off the Speaker Box, a response to the
    last line, a discussion topic or a conversation redirect off the topics
    board - or the SFX clip, which the gap filler beside it already plays.
  - The insert is a line of its own on the aside road, under its own System 3
    node, with the rolls that chose it on its stamp. It belongs to no
    conversation, so it spends none of a conversation's turns, expansions or
    odds, and it does not count toward the SFX cadence.
  - It never waits on the watchdog: the write and the render run on their own
    task while the gap filler's clip covers them; one node at a time, and a
    rest between nodes (DEADAIR_REST).
  - GET /api/flow-ledger carries the node's tally.

Usage:  deadair_node_patch.py --check [ROOT]   0 ready, 2 already applied, 1 anchors missing
        deadair_node_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

NODE_OLD = r'''async def dead_air_watch() -> None:
    """The silence ceiling (#338, #340). Nothing playing and nobody
'''
NODE_NEW = r'''# --- [s3-deadair] THE DEAD-AIR NODE ----------------------------------------------
# "priority nodes that fix and resolve any dead air ... roll a roulette for
# someone to insert a quote, sfx clip, discussion topic, conversation redirect,
# response, banked response, that doesnt decrement the roll or allowed
# increments that is simply there for filling dead air" (the operator, #1571,
# 2026-10-05). The silence rescue below already hands over a banked round when
# the cupboard has one and plays a clip when it has not; this is the voice in
# the room when neither is a conversation. System 3 rolls whether a node steps
# in (STATION1 deadair.node), who (deadair.who) and what (POOLS1 deadair.kind,
# six rows the desk can weight or switch off). The insert is one line on the
# aside road with a node of its own: it belongs to no conversation, so it
# spends none of a conversation's turns, expansions or odds.
DEADAIR_KINDS = ("banked response", "quote", "response", "discussion topic",
                 "conversation redirect", "sfx clip")
DEADAIR_REST = float(os.getenv("DEADAIR_REST", "40"))      # seconds between nodes
_DEADAIR_STATE: dict[str, Any] = {"asked": 0, "fired": 0, "by_kind": {}, "last": {}, "task": None,
                                  "last_at": 0.0}


def _deadair_last_line() -> dict[str, Any]:
    """The last thing a person said on the air (not a record, a clip or a card)."""
    try:
        for row in reversed(_RADIO.get("chat") or []):
            if (isinstance(row, dict) and str(row.get("text") or "").strip()
                    and str(row.get("who") or "") in ("dj", "cohost", "third", "caller", "drop")
                    and not row.get("music") and not row.get("sfx") and not row.get("video")
                    and str(row.get("kind") or "") not in ("marker", "sfx", "image_analysis", "song_analysis")):
                return row
    except Exception:  # noqa: BLE001
        pass
    return {}


async def _deadair_run(why: str) -> str:
    """One node: the rolls and the line, on this task, so the rolls ride the line's stamp."""
    dj = dj_settings()
    away = seat_away_who()
    seats = [w for w in ("dj", "cohost") if w != away]
    if str(dj.get("third_name") or "").strip() and away != "third":
        seats.append("third")
    if not seats:
        return ""
    last = _deadair_last_line()
    others = [w for w in seats if w != str(last.get("who") or "")] or seats
    who = str(s3_choice("deadair.who", others, "who steps into the dead air", tabled=False))
    kind = str(s3_choice("deadair.kind", list(DEADAIR_KINDS), "what a dead-air node puts into the silence"))
    last_text = " ".join(str(last.get("text") or "").split())[:300]
    last_name = str(last.get("name") or "") or "the last voice"
    situation = ("\nThe room has gone quiet and you are the one who breaks the silence. "
                 "One or two spoken sentences, in character, no stage directions.")
    said, topic = "", ""
    try:
        if kind in ("discussion topic", "conversation redirect"):
            board = _sfx_topic_rows()
            topic = str(s3_choice("deadair.topic", board, "the board topic a dead-air node raises",
                                  tabled=False)) if board else ""
        if kind == "banked response":
            voice = str((await session_voices()).get(who) or "")
            engine = voice_engine_for(voice) if voice else ""
            ready = await asyncio.to_thread(_RESPONSES.ready, voice, engine) if voice else []
            fresh = [str(r.get("text") or "") for r in ready
                     if str(r.get("text") or "").strip() and not norepeat_text_used(r.get("text"))]
            if fresh:
                pick = str(s3_choice("deadair.banked", fresh[:60], "which banked response fills the dead air",
                                     tabled=False))
                said = await dj_speak("aside", None, line=pick, who=who, sting=False)
        elif kind == "quote":
            quote = await speakbox_quote()
            lines = [str(x).strip() for x in (quote.get("lines") or []) if str(x).strip()]
            line = " ".join(lines[:2]) or str(quote.get("text") or "").strip()
            if line:
                said = await dj_speak("aside", None, line=line, who=who, sting=False,
                                      source=str(quote.get("file") or ""))
        elif kind == "response" and last_text:
            said = await dj_speak("aside", None, who=who, sting=False, note=situation,
                                  extra=('answer what %s just said on air: "%s". Respond to it directly; '
                                         'do not change the subject' % (last_name, last_text)))
        elif kind == "discussion topic" and topic:
            said = await dj_speak("aside", None, who=who, sting=False, note=situation,
                                  extra="raise this for the room, as a thought you just had: %s" % topic)
        elif kind == "conversation redirect" and topic:
            said = await dj_speak("aside", None, who=who, sting=False, note=situation,
                                  extra=("turn the conversation somewhere new%s, toward this: %s"
                                         % ((' - pick up from "%s"' % last_text) if last_text else "", topic)))
    except Exception as exc:  # noqa: BLE001 - a node that fails leaves the clip, never a fault
        pipeline_log("air", "[s3-deadair] the node's %s did not go out" % kind,
                     extra=("%s: %s" % (type(exc).__name__, exc))[:200])
    row = {"at": time.time(), "kind": kind, "who": who, "said": " ".join(str(said or "").split())[:200],
           "why": str(why)[:120], "topic": topic[:120]}
    _DEADAIR_STATE["last"] = row
    book = _DEADAIR_STATE.setdefault("by_kind", {})
    slot = book.setdefault(kind, {"asked": 0, "said": 0})
    slot["asked"] += 1
    if said:
        slot["said"] += 1
        _DEADAIR_STATE["fired"] = int(_DEADAIR_STATE.get("fired") or 0) + 1
    pipeline_log("air", ("[s3-deadair] %s: %s rolled a %s - %s"
                         % (why, booth_actor_name(who, "") or who, kind,
                            "said" if said else ("the gap filler's clip answers" if kind == "sfx clip"
                                                 else "nothing to give; the clip answers")))[:200],
                 extra=str(said or topic or "")[:200])
    return str(said or "")


def s3_dead_air_node(why: str = "") -> bool:
    """Ask for a dead-air node. Never blocks: the rolls, the write and the
    render run on their own task while the gap filler's clip covers them.
    False when no node starts (one is still working, the rest has not passed,
    the station is paused, or the desk's deadair.node odds said no)."""
    try:
        if radio_paused() or not _RADIO.get("on") or _SPEAKING[0]:
            return False
        task = _DEADAIR_STATE.get("task")
        if task is not None and not task.done():
            return False
        if time.time() - float(_DEADAIR_STATE.get("last_at") or 0) < DEADAIR_REST:
            return False
        _DEADAIR_STATE["asked"] = int(_DEADAIR_STATE.get("asked") or 0) + 1
        if not s3_chance("deadair.node", 1.0, "a dead-air node steps in when the pair go quiet"):
            return False
        _DEADAIR_STATE["last_at"] = time.time()
        _DEADAIR_STATE["task"] = asyncio.create_task(_deadair_run(str(why or "dead air")),
                                                     name="radio:deadair-node")
        return True
    except Exception as exc:  # noqa: BLE001
        pipeline_log("air", "[s3-deadair] the node could not start",
                     extra=("%s: %s" % (type(exc).__name__, exc))[:200])
        return False


async def dead_air_watch() -> None:
    """The silence ceiling (#338, #340). Nothing playing and nobody
'''

HOOK_OLD = r'''                    _went = await _silence_cupboard_handoff()
                    if not _went:
                        _dead_air_pass("the gap filler")
'''
HOOK_NEW = r'''                    _went = await _silence_cupboard_handoff()
                    if not _went:
                        # [s3-deadair] a voice for the silence, on its own task; the
                        # gap filler below covers its write and its render
                        s3_dead_air_node("the pair quiet %.0fs" % float(talk_quiet_for() or 0))
                        _dead_air_pass("the gap filler")
'''

LEDGER_OLD = r'''            "recovery_queue": len(queue) if isinstance(queue, list) else 0}
'''
LEDGER_NEW = r'''            "recovery_queue": len(queue) if isinstance(queue, list) else 0,
            "deadair": {k: v for k, v in (globals().get("_DEADAIR_STATE") or {}).items() if k != "task"}}   # [s3-deadair]
'''

# --- system2_media.py: [s3-produced] the produced spot is System 3's line too ---------
# The orchestrator filed it four times (#1474, #1492, #1554, #1563): "N line(s) on
# ad were put on the air by _deliver_produced, outside System 3". This door
# published a finished spot with no node, so the origin ledger settled each one
# as rogue. Fixed at the producer, as the finding asks: the spot's road node is
# opened before it is published and rides the row.
SPOT_DEF_OLD = r'''    async def _deliver_produced(self, resolved, entry, on_handoff, allowed):
        h = self.host
'''
SPOT_DEF_NEW = r'''    async def _s3_spot_stamp(self, take):
        """[s3-produced] The produced spot's own System 3 node, or None.

        The same call the booth's single lines make at the microphone
        (road ad_spot), bound to the spot's words. A planner that cannot
        answer does not hold the spot: it airs, and the ledger says rogue
        exactly as it did before."""
        h = self.host
        direct = getattr(h, "system3_direct_line", None)
        text = str((take or {}).get("text") or "")
        if not callable(direct) or not text.strip():
            return None
        try:
            handle = await direct(road="ad_spot", who="dj", dj=h.dj_settings(),
                                  context="a produced spot", text=text[:600], bank=True)
            if handle is None or not getattr(handle, "active", False):
                return None
            bind = getattr(h, "system3_bind_line", None)
            if callable(bind):
                bind(handle, text)
            stamp = getattr(handle, "stamp", None)
            return dict(stamp) if isinstance(stamp, dict) and stamp.get("conversation_id") else None
        except Exception:  # noqa: BLE001
            return None

    async def _deliver_produced(self, resolved, entry, on_handoff, allowed):
        h = self.host
'''

SPOT_ASK_OLD = r'''            take = current["takes"][0]
            now = time.time()
            route = str(h._RADIO.get("voice_to") or "box")
'''
SPOT_ASK_NEW = r'''            take = current["takes"][0]
            stamp = await self._s3_spot_stamp(take)      # [s3-produced] before the clock is read
            now = time.time()
            route = str(h._RADIO.get("voice_to") or "box")
'''

SPOT_ROW_OLD = r'''                   "from": 0.0, "until": take["seconds"], "aired": "held"}
            clip = {"url": take["url"], "text": take["text"], "voice": take["voice"],
'''
SPOT_ROW_NEW = r'''                   "from": 0.0, "until": take["seconds"], "aired": "held"}
            if stamp:                                    # [s3-produced] the row names its node
                row["system3"] = stamp
                remember = getattr(h, "_s3_line_remember", None)
                if callable(remember):
                    remember(rid, stamp, "dj", str(take["text"] or ""))
            clip = {"url": take["url"], "text": take["text"], "voice": take["voice"],
'''

EDITS: dict[str, list[tuple[str, str, str, str, int]]] = {
    "app.py": [
        ("the node", NODE_OLD, NODE_NEW, "def s3_dead_air_node(", 1),
        ("the silence rescue asks", HOOK_OLD, HOOK_NEW, "# [s3-deadair] a voice for the silence", 1),
        ("the ledger carries the tally", LEDGER_OLD, LEDGER_NEW, "}   # [s3-deadair]", 1),
    ],
    "system2_media.py": [
        ("the spot's node", SPOT_DEF_OLD, SPOT_DEF_NEW, "    async def _s3_spot_stamp(self, take):", 1),
        ("asked before publishing", SPOT_ASK_OLD, SPOT_ASK_NEW, "# [s3-produced] before the clock is read", 1),
        ("the row names its node", SPOT_ROW_OLD, SPOT_ROW_NEW, "# [s3-produced] the row names its node", 1),
    ],
}


def _read(path: Path) -> tuple[str, bool]:
    text = path.read_bytes().decode("utf-8")
    crlf = "\r\n" in text
    if crlf:
        if text.count("\r\n") != text.count("\n"):
            raise SystemExit("%s has mixed line endings; refusing to guess" % path)
        text = text.replace("\r\n", "\n")
    if "\r" in text:
        raise SystemExit("%s has bare carriage returns; refusing to guess" % path)
    return text, crlf


def _state(text: str, edit: tuple[str, str, str, str, int]) -> str:
    _name, old, _new, probe, count = edit
    have = text.count(probe)
    if have == count:
        return "applied"
    if have:
        return "partial (%d of %d probes)" % (have, count)
    found = text.count(old)
    return "ready" if found == count else "missing (anchor found %d, expected %d)" % (found, count)


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    root = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parent.parent
    apply = argv[1] == "--apply"
    any_ready, any_missing = False, False
    plans = []
    for name, edits in EDITS.items():
        path = root / name
        text, crlf = _read(path)
        todo = []
        for edit in edits:
            state = _state(text, edit)
            print("%-10s %-32s %s" % (name, edit[0], state))
            if state == "ready":
                todo.append(edit)
                any_ready = True
            elif state != "applied":
                any_missing = True
        plans.append((path, text, crlf, todo))
    if any_missing:
        print("ANCHORS MISSING - nothing written")
        return 1
    if not any_ready:
        print("already applied")
        return 2
    if not apply:
        print("ready")
        return 0
    for path, text, crlf, todo in plans:
        if not todo:
            continue
        for _name, old, new, probe, count in todo:
            assert text.count(old) == count, (path.name, _name)
            text = text.replace(old, new)
            assert text.count(probe) == count, (path.name, _name, "probe")
        out = text.replace("\n", "\r\n") if crlf else text
        tmp = path.with_name(path.name + ".deadair.tmp")
        tmp.write_bytes(out.encode("utf-8"))
        os.replace(tmp, path)
        print("wrote %s (%d edit(s), %s)" % (path.name, len(todo), "CRLF" if crlf else "LF"))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
