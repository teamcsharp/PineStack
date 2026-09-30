"""[es-every-turn] every System 3 turn is heard in a feeling.

"is the emotion engine active and modulating the audio yet?" Measured
2026-09-30: 12 of the last 21 voiced lines carried an ES voice block and were
shaped; the coalesced road's airings said "the round's turn carried no ES voice"
for 7 of its 9 stamped rows. Every speaking step of the structure DOES draw ES -
the misses are chunks perf_voice could not match back to a planned turn (reworded
on the way past the loose match: the tint, a Speakerbox swap) or a turn stamp from
before voice blocks rode it. Those lines aired flat.

Now, when a chunk of an active round has no voice of its own, it is spoken in the
SEAT'S CURRENT FEELING - the category/item/intensity System 3 itself holds for that
participant (participant(conv, seat)["emotion"], the same state the next roll
persists or reacts from) - through the same ES table voice block and
voice_intent. Nothing new is drawn and nothing is invented: it is System 3's own
state. perf_state does the same for the dims. Each miss is counted by why
(metrics voice_miss_noturn / voice_miss_novoice / voice_seat).

Usage (ON THE HOST): python3 tools/es_every_turn_patch.py --check|--apply
"""
import ast
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARK = "[es-every-turn]"

EDITS = [
    ('''    def perf_voice(self, entry, turns, text, who=""):
''', '''    def _seat_feel(self, cid, who):
        """[es-every-turn] the seat's current feeling as System 3 holds it:
        {"voice", "dims", "row"} or None. Nothing is drawn."""
        seat = _SEAT_OF.get(str(who or ""), "")
        if not cid or not seat:
            return None
        conv = self.recent.get(str(cid))
        if conv is None:
            try:
                conv = self.store.conversation(str(cid))
            except Exception:  # noqa: BLE001
                conv = None
        if not isinstance(conv, dict) or not isinstance(conv.get("participants"), list):
            return None
        p = system3.participant(conv, seat) or {}
        emo = p.get("emotion") if isinstance(p.get("emotion"), dict) else {}
        if not emo.get("table") or not emo.get("category"):
            return None
        spec = {"table": emo["table"], "category": emo["category"], "id": emo.get("id"),
                "label": emo.get("label")}
        block = system3.es_voice(self.config, spec)
        intensity = float(emo.get("intensity") or 0.5)
        return {"voice": system3.voice_intent(block, intensity) if block else None,
                "dims": emo.get("dims") if isinstance(emo.get("dims"), dict) else {},
                "row": {"table": emo["table"], "category": emo["category"], "item": emo.get("id"),
                        "label": emo.get("label"), "intensity": round(intensity, 3),
                        "source": "the seat's current feeling"}}

    def _voice_miss(self, why):
        with self.lock:
            self.metrics[why] = int(self.metrics.get(why) or 0) + 1

    def perf_voice(self, entry, turns, text, who=""):
''', 1),
    # perf_voice: the two misses fall back to the seat's feeling
    ('''            _cid, i = self._turn_of(entry, text, who)
            if i is None:
                i = self._turn_of_loose(entry, text, who)                     # [s3-direction] its voice too
            if i is None:
                return None
            stamp = (((entry.get("turn_dice") or {}).get(str(i)) or {}).get("s3") or {})
            got = (stamp.get("perf") or {}).get("voice")
            if not isinstance(got, dict):
                return None
''', '''            _cid, i = self._turn_of(entry, text, who)
            if i is None:
                i = self._turn_of_loose(entry, text, who)                     # [s3-direction] its voice too
            got = None
            stamp = {}
            if i is not None:
                stamp = (((entry.get("turn_dice") or {}).get(str(i)) or {}).get("s3") or {})
                got = (stamp.get("perf") or {}).get("voice")
            if not isinstance(got, dict):
                # [es-every-turn] no voice of its own: the seat's current feeling
                self._voice_miss("voice_miss_noturn" if i is None else "voice_miss_novoice")
                if _cid is None:
                    _cid = ((entry or {}).get("system3") or {}).get("conversation_id")
                feel = self._seat_feel(_cid, who)
                if not feel or not isinstance(feel.get("voice"), dict):
                    return None
                self._voice_miss("voice_seat")
                return dict(feel["voice"], row=dict(feel["row"]))
''', 1),
    # perf_state: the same, for the dims
    ('''            _cid, i = self._turn_of(entry, text, who)
            if i is None:
                i = self._turn_of_loose(entry, text, who)                     # [s3-direction] reworded on the way
            if i is None:
                return None
            stamp = (((entry.get("turn_dice") or {}).get(str(i)) or {}).get("s3") or {})
            dims = (stamp.get("perf") or {}).get("dims")
            if not isinstance(dims, dict) or not dims:
                return None
''', '''            _cid, i = self._turn_of(entry, text, who)
            if i is None:
                i = self._turn_of_loose(entry, text, who)                     # [s3-direction] reworded on the way
            dims = None
            if i is not None:
                stamp = (((entry.get("turn_dice") or {}).get(str(i)) or {}).get("s3") or {})
                dims = (stamp.get("perf") or {}).get("dims")
            if not isinstance(dims, dict) or not dims:
                # [es-every-turn] the seat's current feeling, as perf_voice does
                if _cid is None:
                    _cid = ((entry or {}).get("system3") or {}).get("conversation_id")
                feel = self._seat_feel(_cid, who)
                dims = (feel or {}).get("dims")
                if not isinstance(dims, dict) or not dims:
                    return None
''', 1),
]

if __name__ == "__main__":
    mode = sys.argv[1]
    path = ROOT + "/system3_runtime.py"
    src = open(path, encoding="utf-8").read()
    if MARK in src:
        print(path + ": APPLIED")
        sys.exit(0)
    out = src
    for old, new, n in EDITS:
        got = out.count(old)
        assert got == n, "%r found %d, want %d" % (old[:60], got, n)
        out = out.replace(old, new)
    ast.parse(out)
    if mode == "--check":
        print(path + ": ready")
        sys.exit(0)
    shutil.copy(path, "/tmp/system3_runtime.py.bak-es-every-turn")
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")
