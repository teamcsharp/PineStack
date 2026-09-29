"""[es-roads] The emotion engine reaches every seat's take, and the air record
names the ES row that shaped it (tools/es_roads_patch.py).

- the runtime answers "what does the turn this stamp name feel like": dims and
  the ES row's voice with its row, from memory, from the store once it has
  aged out, and for a split part from the turn it was cut from;
- a turn stamp (the round road) and a line handle carry the row too;
- performance_vector carries the row out as vec["es_row"]; es_air_stamp and
  screenplay_line_row put it on the air record, or "none" with the road;
- every performance_vector call in app.py hands it the ES, or is one of the
  named few that cannot know it.

app.py is read, never imported. Nothing renders, no data dir is touched."""
import re
import unittest
from pathlib import Path
from typing import Any

import es_voice
import system3

import test_system3_runtime as _rt
from test_system3_runtime import ctx, settle

ROOT = Path(__file__).resolve().parents[1]


def _app_text():
    return (ROOT / "app.py").read_text(encoding="utf-8")


def _top_level(text, head):
    i = text.find("\n" + head) + 1
    if not i:
        raise AssertionError("app.py has no top-level %r (is es_roads_patch applied?)" % head)
    out = [text[i:text.index("\n", i) + 1]]
    j = i + len(out[0])
    while j < len(text):
        k = text.index("\n", j) + 1
        line = text[j:k]
        if line.strip() and not line[0].isspace() and not line.startswith((")", "}", "]")):
            break
        out.append(line)
        j = k
    return "".join(out)


def _app(*heads, **ns):
    text = _app_text()
    space: dict[str, Any] = {"Any": Any, "_es_voice": es_voice, "re": re, **ns}
    exec(compile("".join(_top_level(text, h) for h in heads), "app.py[es-roads]", "exec"), space)
    return space


class StampPerfTests(unittest.TestCase):
    boot = _rt.RuntimeTests.boot          # the stand-in station, not its tests
    run_ = _rt.RuntimeTests.run_

    def _voiced(self):
        rt = self.boot()
        h = self.run_(self.station["system3_direct_banter"](**ctx()))
        voiced = [t for t in h.conv["turns"] if isinstance((t.get("performance") or {}).get("voice"), dict)]
        self.assertTrue(voiced, "the default ES tables carry voices")
        return rt, h, voiced[0]

    def test_a_stamp_names_its_turns_feeling_and_row(self):
        rt, h, t = self._voiced()
        stamp = {"conversation_id": h.id, "mode": "active", "turn_id": t["turn_id"]}
        got = self.station["system3_perf_of_stamp"](stamp, "dj")
        self.assertEqual(got["dims"], {d: float(t["performance"]["dims"].get(d) or 0) for d in system3.EMOTION_DIMS})
        row = got["voice"].pop("row")
        self.assertEqual(got["voice"], t["performance"]["voice"])
        es = [d for d in t["decisions"] if d.get("family") == "ES" and d.get("item")][-1]
        self.assertEqual(row["category"], es["category"])
        self.assertEqual(row["item"], es["item"])
        self.assertEqual(row["intensity"], es["intensity"])
        self.assertEqual(es_voice.clean(dict(got["voice"], row=row)), es_voice.clean(got["voice"]),
                         "the row rides beside the voice block, never into the engines' numbers")

    def test_an_aged_out_conversation_is_read_from_the_store(self):
        rt, h, t = self._voiced()
        stamp = {"conversation_id": h.id, "mode": "active", "turn_id": t["turn_id"]}
        want = rt.perf_of_stamp(stamp)
        settle()
        rt.recent.pop(h.id)
        self.assertIsNone(rt.perf_of_stamp(stamp), "memory only unless asked")
        self.assertEqual(rt.perf_of_stamp(stamp, disk=True), want)

    def test_a_split_part_inherits_the_turn_it_was_cut_from(self):
        rt, h, t = self._voiced()
        stamp = {"conversation_id": h.id, "mode": "active", "turn_id": h.id + ":t99",
                 "split": {"part": 2, "of": 2, "of_turn": t["turn_id"]}}
        got = rt.perf_of_stamp(stamp)
        self.assertEqual(got["voice"]["row"], system3.es_row(t))

    def test_no_turn_no_feeling(self):
        rt, h, _t = self._voiced()
        self.assertIsNone(rt.perf_of_stamp({"conversation_id": "nope", "mode": "active", "turn_id": "x"}))
        self.assertIsNone(rt.perf_of_stamp({"conversation_id": h.id, "mode": "active", "turn_id": "x"}))
        self.assertIsNone(rt.perf_of_stamp(None))

    def test_the_round_road_and_the_line_handle_carry_the_row(self):
        rt, h, t = self._voiced()
        stamp = system3.turn_stamp(h.conv, t)
        self.assertEqual(stamp["perf"]["row"], system3.es_row(t))
        line = self.run_(self.station["system3_direct_line"](road="interject", who="dj", dj=ctx()["dj"],
                                                             context="the van", text="The van is back."))
        if isinstance(line.voice, dict):
            self.assertEqual(line.voice["row"], system3.es_row(line.conv["turns"][0]) or {})


class AppSideTests(unittest.TestCase):
    def test_the_vector_carries_its_row_out(self):
        text = _app_text()
        heads = ("EMOTION_DIMS =", "MACRO_STATES:", "_MACRO_MULT =", "_PERF_IDENTITY =",
                 "def performance_vector(", "ES_ROW_KEYS =")
        ns = _app(*heads, dj_settings=lambda: {"voice_speed": 1.0, "perf": True, "perf_strength": 1.0,
                                               "disfluency_rate": 0.3},
                  _RADIO={}, voice_signature=lambda v: None, speaker_state=None)
        self.assertIn("ES_ROW_KEYS", text)
        row = {"table": "ES1_V2", "category": "anger", "item": "fury", "label": "fury", "intensity": 0.8}
        block = dict(system3.voice_intent({"tempo": 1.1, "pitch": 1.0, "energy": 0.4}, 0.8), row=row)
        vec = ns["performance_vector"]("dj", "", state={d: 0.0 for d in ns["EMOTION_DIMS"]}, es=block)
        self.assertEqual(vec["es_row"], row)
        self.assertEqual(set(vec["es"]), {"tempo", "pitch", "energy"})
        plain = ns["performance_vector"]("dj", "", state={d: 0.0 for d in ns["EMOTION_DIMS"]})
        self.assertNotIn("es_row", plain or {})

    def test_the_air_record_names_the_row_or_says_none(self):
        ns = _app("ES_ROW_KEYS =", "def es_air_stamp(", "def screenplay_line_row(",
                  SCREENPLAY_PROMPT_CAP=600, SCREENPLAY_SCRIPT_CAP=600)
        vec = {"pace": 1.05, "es": {"tempo": 1.05, "pitch": 0.6, "temp": 0.03},
               "es_row": {"category": "joy", "item": "delight", "intensity": 0.55}}
        st = ns["es_air_stamp"](vec, "speak_turns/turn", baked=True)
        self.assertEqual(st, {"road": "speak_turns/turn", "category": "joy", "item": "delight",
                              "intensity": 0.55, "voice": {"tempo": 1.05, "pitch": 0.6, "temp": 0.03},
                              "baked": True})
        none = ns["es_air_stamp"]({"pace": 1.0}, "dj_speak/stamp", why="its turn is not an active one")
        self.assertEqual(none, {"road": "dj_speak/stamp", "none": "its turn is not an active one"})
        row = ns["screenplay_line_row"]({"id": "x", "who": "dj", "perf": {"pace": 1.05}, "es": st})
        self.assertEqual(row["perf"]["es"], st)
        self.assertEqual(row["perf"]["pace"], 1.05)
        bare = ns["screenplay_line_row"]({"id": "y", "who": "dj", "es": none})
        self.assertEqual(bare["perf"], {"es": none})

    def test_every_performance_vector_call_hands_it_the_es_or_cannot_know_it(self):
        text = _app_text()
        # the few that cannot know it, and why
        cannot = {"_production_instructions": "the frozen revision's contract text, not a take",
                  "_round_chunks": "pantry-key planning (disfluencies), not a take; the lookahead renders with es=",
                  "_dj_speak_floorless": "the base vector, re-built with the line's ES below it"}
        seen = []
        for m in re.finditer(r"performance_vector\(", text):
            if text[m.start() - 4:m.start()] == "def ":
                continue
            depth, i = 0, m.end() - 1
            while True:
                c = text[i]
                depth += c == "("
                depth -= c == ")"
                i += 1
                if depth == 0:
                    break
            call = text[m.start():i]
            owner = re.findall(r"(?m)^(?:async )?def (\w+)\(", text[:m.start()])[-1]
            seen.append(owner)
            if "es=" in call:
                continue
            self.assertIn(owner, cannot, "%s builds a take's vector without the ES: %s" % (owner, call[:120]))
        for owner in ("_s3_split_render", "prep_render_line", "_speak_turns_floorless", "_dj_speak_floorless", "larder_prepare"):
            self.assertIn(owner, seen)
        self.assertIn('_s3_split_render(words, pwho, pvoice, stamp=p.get("stamp"))', text)
        self.assertIn('perf=item.get("vec") or None', text)


if __name__ == "__main__":
    unittest.main()
