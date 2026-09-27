"""The rewrite passes are System 3 rolls ([s3-rewrite]): TINT per turn,
REPAIR and ROOM per round.

Operator, 2026-09-27, asked what should happen to the passes that rewrite
a round after System 3 plans it (the crystal tint's rhyme pass, the
Writers' Room, the quality gates' rewrite): "Make each a System 3 roll -
e.g. 'rhyme this line' becomes a family with odds you control, rolled per
turn and shown in the Rolodex."

Measured before this (docs, 2026-09-27 survey): the tint selected "the
first N eligible turns" for its coverage, deterministically; the richness
rewrite and System 3's own repair were cancelled by a review gate that,
with the content gates off, accepts every valid draft; the Writers' Room's
two tickets (add turns / rewrite whole) chose rounds by their quality debt
alone. None of it was in the Rolodex.

Now, on every round System 3 plans (opt-in `rewrite_rolls`, which the
runtime sets, so older plans and the golden trajectory are unchanged):

  TINT    per turn, stream seed|tint, control `tint` (0.5 -> 50% of turns):
          "rhyme this line" - the turns the crystal tint may touch. When the
          station's tint pass is off, one round event says so instead.
  REPAIR  per round, stream seed|round:REPAIR, control `repair`: whether a
          round that misses its target is sent back to the writer.
  ROOM    per round, stream seed|round:ROOM, control `room`: whether the
          Writers' Room may add to or rewrite this round later.

The runtime hands the station what it needs (tools/rewrite_gates_patch.py
reads them): system3_tint_turns(handle, script) -> the script indices whose
turn rolled a rhyme; system3_repair_roll(handle) -> True/False/None;
system3_room_allowed(entry) -> the ROOM roll bound onto the entry; and the
bind stamps entry["system3"]["tint_turns" / "repair" / "room"] for the
passes that run after binding.

Idempotent: --check exits 0 ready / 2 applied / 1 missing; --apply writes
system3.py and system3_runtime.py (LF). ON THE HOST.
"""
import sys
from pathlib import Path

ENGINE = [
    ('FAMILIES = ("CTS", "ES", "RS", "IRS", "FL", "SPEAKERBOX", "SFX", "TOPIC", "SFXGUY", "LINE", "LENGTH",\n'
     '            "TEMPER", "SHOCK", "INTERJECT", "MENTION", "CARRY")          # [s3-rounds] [s3-carry]\n',
     'FAMILIES = ("CTS", "ES", "RS", "IRS", "FL", "SPEAKERBOX", "SFX", "TOPIC", "SFXGUY", "LINE", "LENGTH",\n'
     '            "TEMPER", "SHOCK", "INTERJECT", "MENTION", "CARRY",          # [s3-rounds] [s3-carry]\n'
     '            "TINT", "REPAIR", "ROOM")                                    # [s3-rewrite]\n'),
    ('    "shock_beat": 0.5,\n'
     '    "interjections": 0.5,\n'
     '    "mention": 0.5,\n',
     '    "shock_beat": 0.5,\n'
     '    "interjections": 0.5,\n'
     '    "mention": 0.5,\n'
     '    # [s3-rewrite] the passes after the write, as odds: which lines the\n'
     '    # crystal tint may rhyme, whether a round that missed its target is\n'
     '    # sent back, whether the Writers\' Room may touch it later\n'
     '    "tint": 0.5,\n'
     '    "repair": 0.5,\n'
     '    "room": 0.5,\n'),
    ('MENTION_RATE_AT_FULL = 0.6\n',
     'MENTION_RATE_AT_FULL = 0.6\n'
     'TINT_RATE_AT_FULL = 1.0          # [s3-rewrite] control 1.0 = every turn may be rhymed\n'
     'REPAIR_RATE_AT_FULL = 1.0\n'
     'ROOM_RATE_AT_FULL = 1.0\n'),
    # the per-turn roll, beside the SFX Guy's node
    ('    turn["sfxguy"] = _sfxguy_decision(conv, config, ctx, turn, inputs)      # [s3-roads]\n',
     '    turn["sfxguy"] = _sfxguy_decision(conv, config, ctx, turn, inputs)      # [s3-roads]\n'
     '    turn["tint"] = _tint_decision(conv, settings, ctx, turn, inputs)         # [s3-rewrite]\n'),
    ('def _sfxguy_decision(conv, config, ctx, turn, inputs):\n',
     'def _tint_decision(conv, settings, ctx, turn, inputs):\n'
     '    """[s3-rewrite] "Rhyme this line": whether the crystal tint may touch\n'
     '    this turn. Its own stream (seed|tint), so the round\'s other draws are\n'
     '    what they were. Nothing is rolled unless the round opted in\n'
     '    (rewrite_rolls); when the station\'s tint pass is off, one event on the\n'
     '    round says so and no turn rolls."""\n'
     '    if not inputs.get("rewrite_rolls"):\n'
     '        return None\n'
     '    tint = inputs.get("tint") if isinstance(inputs.get("tint"), dict) else {}\n'
     '    if not tint.get("wanted"):\n'
     '        if not conv.get("tint_off_noted"):\n'
     '            conv["tint_off_noted"] = True\n'
     '            before = _snapshot(conv, turn["speaker"])\n'
     '            ev = _event(conv, {"turn_id": "", "turn_index": -1}, "TINT", [],\n'
     '                        {"id": "OFF", "label": "the crystal tint pass is off on the station"}, before,\n'
     '                        meta={"applies": False, "why": str(tint.get("why") or "the station\'s crystal tint pass is off "\n'
     '                              "(crystal_tint_pass, a crystal switched on, and the tint gate are all needed)")})\n'
     '            ev["state_after"] = before\n'
     '        return None\n'
     '    controls = settings.get("controls") or {}\n'
     '    control = clamp(controls.get("tint", DEFAULT_CONTROLS["tint"]))\n'
     '    rate = round(clamp(TINT_RATE_AT_FULL * control), 4)\n'
     '    own = DrawStream(str(conv["seed"]) + "|tint", int(conv.get("tint_draws") or 0))\n'
     '    before = _snapshot(conv, turn["speaker"])\n'
     '    d = own.next("TINT:rhyme")\n'
     '    st, hit = _dice_stage("RHYME", "the crystal tint may rhyme this line", rate, d,\n'
     '                          "tint control %.2f x %.1f" % (control, TINT_RATE_AT_FULL))\n'
     '    conv["tint_draws"] = own.n\n'
     '    ev = _event(conv, dict(ctx, turn_id=turn["turn_id"], turn_index=turn["index"]), "TINT", [st],\n'
     '                {"id": "RHYME" if hit else "PLAIN", "label": "the tint may rhyme this line" if hit else "read plain, as written"},\n'
     '                before, meta={"rate": rate, "control": round(control, 3),\n'
     '                              "coverage_target": tint.get("coverage"),\n'
     '                              "why": "the station\'s own selection took the first N eligible lines for its coverage; "\n'
     '                                     "under System 3 the dice choose the lines"}, rng=d)\n'
     '    ev["state_after"] = before\n'
     '    turn["decisions"].append({"family": "TINT", "event_id": ev["event_id"], "item": "RHYME" if hit else "PLAIN",\n'
     '                              "label": ev["selected"]["label"], "u": d["u"]})\n'
     '    return {"rhyme": bool(hit), "event_id": ev["event_id"]}\n'
     '\n'
     '\n'
     'def _rewrite_rolls(conv, config, settings, inputs):\n'
     '    """[s3-rewrite] The round\'s two rolls about what may happen to it after\n'
     '    the write: REPAIR (a round that misses its target goes back to the\n'
     '    writer, or stands as written) and ROOM (the Writers\' Room may add to or\n'
     '    rewrite it later, or may not). Each on its own stream, recorded once,\n'
     '    opt-in like the round rolls."""\n'
     '    if not inputs.get("rewrite_rolls") or conv.get("repair_roll") is not None:\n'
     '        return\n'
     '    controls = settings.get("controls") or {}\n'
     '    ctx0 = {"turn_id": "", "turn_index": -1}\n'
     '    for family, key, at_full, yes, no, why in (\n'
     '            ("REPAIR", "repair", REPAIR_RATE_AT_FULL, "a round that misses its target goes back to the writer",\n'
     '             "it stands as written, whatever the checks say",\n'
     '             "the richness rewrite and System 3\'s own repair used to run - or be cancelled by a review gate - "\n'
     '             "on their own; this roll decides, and the gates do not"),\n'
     '            ("ROOM", "room", ROOM_RATE_AT_FULL, "the Writers\' Room may add to or rewrite this round later",\n'
     '             "the Writers\' Room leaves this round alone",\n'
     '             "the Room\'s two tickets (add turns / rewrite whole) chose bound rounds by their quality debt; "\n'
     '             "this roll is asked first")):\n'
     '        control = clamp(controls.get(key, DEFAULT_CONTROLS[key]))\n'
     '        rate = round(clamp(at_full * control), 4)\n'
     '        stream = DrawStream(str(conv["seed"]) + "|round:" + family)\n'
     '        d = stream.next(family + ":dice")\n'
     '        st, hit = _dice_stage(family, yes, rate, d, "%s control %.2f x %.1f" % (key, control, at_full))\n'
     '        st["candidates"][1]["label"] = no\n'
     '        before = _snapshot(conv, conv["cursor"].get("initiator"))\n'
     '        ev = _event(conv, ctx0, family, [st], {"id": family if hit else "NONE", "label": yes if hit else no},\n'
     '                    before, meta={"rate": rate, "control": round(control, 3), "why": why}, rng=d)\n'
     '        ev["state_after"] = before\n'
     '        conv[key + "_roll"] = {key: bool(hit), "event_id": ev["event_id"], "rate": rate}\n'
     '\n'
     '\n'
     'def _sfxguy_decision(conv, config, ctx, turn, inputs):\n'),
    # rolled with the round's own rolls, before their opt-in gate
    ('    if not inputs.get("round_rolls"):\n'
     '        # a caller\'s protocol, a test plan, a conversation stored before these\n'
     '        # rolls existed: nothing is drawn and the trajectory is the old one\n'
     '        return\n',
     '    _rewrite_rolls(conv, config, settings, inputs)                         # [s3-rewrite]\n'
     '    if not inputs.get("round_rolls"):\n'
     '        # a caller\'s protocol, a test plan, a conversation stored before these\n'
     '        # rolls existed: nothing is drawn and the trajectory is the old one\n'
     '        return\n'),
    # the stamp the air carries
    ('            "sfxguy": {k: (t.get("sfxguy") or {}).get(k) for k in ("speak", "kind", "order", "event_id")},\n'
     '            # [s3-rounds] what the round\'s own rolls put on this turn\n',
     '            "sfxguy": {k: (t.get("sfxguy") or {}).get(k) for k in ("speak", "kind", "order", "event_id")},\n'
     '            # [s3-rewrite] whether the crystal tint may rhyme this line\n'
     '            "tint": {k: (t.get("tint") or {}).get(k) for k in ("rhyme", "event_id")},\n'
     '            # [s3-rounds] what the round\'s own rolls put on this turn\n'),
]

RUNTIME = [
    ('            "round_rolls": True,\n',
     '            "round_rolls": True,\n'
     '            # [s3-rewrite] TINT per turn, REPAIR and ROOM per round\n'
     '            "rewrite_rolls": True,\n'
     '            "tint": self._tint_state(),\n'),
    ('    # --- planning --------------------------------------------------------------\n'
     '    async def direct(self, ctx):\n',
     '    def _tint_state(self):\n'
     '        """[s3-rewrite] Is the station\'s crystal tint pass on (dialogue_tint_wanted),\n'
     '        and at what coverage - the TINT roll only rolls when it is."""\n'
     '        wanted, coverage, why = False, None, ""\n'
     '        try:\n'
     '            fn = getattr(self.host, "dialogue_tint_wanted", None)\n'
     '            wanted = bool(fn()) if callable(fn) else False\n'
     '        except Exception as exc:  # noqa: BLE001\n'
     '            why = "%s: %s" % (type(exc).__name__, str(exc)[:80])\n'
     '        try:\n'
     '            fn = getattr(self.host, "crystal_coverage_target", None)\n'
     '            coverage = int(fn()) if callable(fn) else None\n'
     '        except Exception:  # noqa: BLE001\n'
     '            coverage = None\n'
     '        return {"wanted": wanted, "coverage": coverage, "why": why}\n'
     '\n'
     '    # --- the rewrite rolls, for the station ------------------------------------\n'
     '    def tint_turns(self, handle, script):\n'
     '        """[s3-rewrite] The script indices whose turn rolled a rhyme - the\n'
     '        lines the crystal tint may touch. None when the round is not System\n'
     '        3\'s or nothing was rolled (the station keeps its own selection)."""\n'
     '        if not handle or not handle.active:\n'
     '            return None\n'
     '        conv = handle.conv\n'
     '        if not any(t.get("tint") for t in conv.get("turns") or []):\n'
     '            return None\n'
     '        try:\n'
     '            turns = self.host.banter_turns(str(script or ""))\n'
     '            mapping = system3.align(conv, turns)\n'
     '        except Exception as exc:  # noqa: BLE001\n'
     '            self.fail("tint alignment", exc)\n'
     '            return None\n'
     '        out = set()\n'
     '        for t in conv["turns"]:\n'
     '            if (t.get("tint") or {}).get("rhyme") and mapping.get(t["index"]) is not None:\n'
     '                out.add(int(mapping[t["index"]]))\n'
     '        return out\n'
     '\n'
     '    def repair_roll(self, handle):\n'
     '        """[s3-rewrite] True: a round that misses its target goes back; False:\n'
     '        it stands as written; None: nothing was rolled (the old rules)."""\n'
     '        if not handle or not handle.active:\n'
     '            return None\n'
     '        got = handle.conv.get("repair_roll")\n'
     '        return bool(got.get("repair")) if isinstance(got, dict) else None\n'
     '\n'
     '    @staticmethod\n'
     '    def room_allowed(entry):\n'
     '        """[s3-rewrite] May the Writers\' Room touch this stored round? False only\n'
     '        when System 3 bound a ROOM roll that said no."""\n'
     '        s3 = entry.get("system3") if isinstance(entry, dict) else None\n'
     '        return not (isinstance(s3, dict) and s3.get("room") is False)\n'
     '\n'
     '    @staticmethod\n'
     '    def tint_turns_entry(entry):\n'
     '        """[s3-rewrite] The tint selection bound onto a stored entry, for the\n'
     '        passes that run after binding (larder, retint, recovery)."""\n'
     '        s3 = entry.get("system3") if isinstance(entry, dict) else None\n'
     '        got = s3.get("tint_turns") if isinstance(s3, dict) else None\n'
     '        return set(int(i) for i in got) if isinstance(got, list) else None\n'
     '\n'
     '    # --- planning --------------------------------------------------------------\n'
     '    async def direct(self, ctx):\n'),
    ('                                "turns": {str(i): t["turn_id"] for t in conv["turns"]\n'
     '                                          for i in [mapping.get(t["index"])] if i is not None}}\n'
     '            self.remember(conv)\n'
     '            self.persist(conv)\n',
     '                                "turns": {str(i): t["turn_id"] for t in conv["turns"]\n'
     '                                          for i in [mapping.get(t["index"])] if i is not None}}\n'
     '            # [s3-rewrite] the rolls the passes after the bind read (the\n'
     '            # larder / retint tint, the Writers\' Room), on the same record\n'
     '            if handle.active and isinstance(entry.get("system3"), dict):\n'
     '                if any(t.get("tint") for t in conv["turns"]):\n'
     '                    entry["system3"]["tint_turns"] = sorted(\n'
     '                        int(mapping[t["index"]]) for t in conv["turns"]\n'
     '                        if (t.get("tint") or {}).get("rhyme") and mapping.get(t["index"]) is not None)\n'
     '                for key in ("repair", "room"):\n'
     '                    got = conv.get(key + "_roll")\n'
     '                    if isinstance(got, dict):\n'
     '                        entry["system3"][key] = bool(got.get(key))\n'
     '            self.remember(conv)\n'
     '            self.persist(conv)\n'),
    ('            handle.conv["pre_repair"] = {k: val[k] for k in ("score", "verdict", "seat_order", "turn_ratio")}\n'
     '            if val["repair_wanted"]:\n',
     '            handle.conv["pre_repair"] = {k: val[k] for k in ("score", "verdict", "seat_order", "turn_ratio")}\n'
     '            # [s3-rewrite] the REPAIR roll decides: a round that rolled "stands"\n'
     '            # is not sent back, whatever the checks say - and says so\n'
     '            roll = handle.conv.get("repair_roll")\n'
     '            if val["repair_wanted"] and isinstance(roll, dict) and roll.get("repair") is False:\n'
     '                self.observe_later(handle.id, "REPAIR", {"why": "missed: seat order %.2f, turns %.2f - but the REPAIR "\n'
     '                                                        "roll said it stands as written" % (val["seat_order"], val["turn_ratio"]),\n'
     '                                                        "validation": handle.conv["pre_repair"], "rolled": False})\n'
     '                return False\n'
     '            if val["repair_wanted"]:\n'),
    ('    namespace["system3_repair_wanted"] = rt.repair_wanted\n',
     '    namespace["system3_repair_wanted"] = rt.repair_wanted\n'
     '    namespace["system3_tint_turns"] = rt.tint_turns              # [s3-rewrite]\n'
     '    namespace["system3_tint_turns_entry"] = rt.tint_turns_entry\n'
     '    namespace["system3_repair_roll"] = rt.repair_roll\n'
     '    namespace["system3_room_allowed"] = rt.room_allowed\n'),
]


def patch(path, edits):
    text = Path(path).read_bytes().decode("utf-8")
    assert "\r\n" not in text[:50000], path + " is CRLF - stop"
    todo = 0
    for old, new in edits:
        if new in text:
            continue
        if text.count(old) != 1:
            print("MISSING (%d) in %s: %r" % (text.count(old), path, old[:90]))
            return None
        text = text.replace(old, new)
        todo += 1
    return text, todo


def main(argv):
    apply = "--apply" in argv
    out = {}
    for path, edits in (("system3.py", ENGINE), ("system3_runtime.py", RUNTIME)):
        got = patch(path, edits)
        if got is None:
            return 1
        out[path] = got
    todo = sum(n for _, n in out.values())
    if not todo:
        print("already applied")
        return 2
    if not apply:
        print("can apply: %d edit(s)" % todo)
        return 0
    for path, (text, n) in out.items():
        if n:
            Path(path).write_bytes(text.encode("utf-8"))
    print("applied: %d edit(s)" % todo)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
