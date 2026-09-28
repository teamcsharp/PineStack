"""[s3-blocks] Every block System 3's table names is marked where its words
enter a writer prompt (tools/system3_blocks2_patch.py finishes what
system3_blocks_patch began: a block no site marks is sent but never decided,
recorded or switchable). A block marked inside another block's words - the
heat aside inside the angle, THE BATTLE inside the schedule - is decided on
its own: kept, the words sent are byte for byte the words built; stripped,
only its own words go."""
import importlib.util
import re
import unittest
from pathlib import Path
from typing import Any

import system3
import system3_tables

ROOT = Path(__file__).resolve().parents[1]

# radio_persona marks its slot by a computed name: persona / cohost / third
_PERSONA_MARK = '_pb({"cohost": "cohost", "third": "third"}.get(str(slot), "persona")'
_MARK = re.compile(r"""_pb(?:_within)?\(\s*['"]([a-z0-9_]+)['"]""")
# dj_banter registers the blocks riding inside its angle as (name, words)
# pairs, marked on the prompt's copy by _pb_within in one loop
_ANGLE_PARTS = re.compile(r"_angle_parts: list\[tuple\[str, str\]\] = \[.*?for _pb_name, _pb_part in _angle_parts:",
                          re.S)
_PART = re.compile(r"""\(\s*['"]([a-z0-9_]+)['"],""")


def _marked_names(text):
    names = set(_MARK.findall(text))
    for block in _ANGLE_PARTS.findall(text):
        names |= set(_PART.findall(block))
    return names


def _app_text():
    return (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")


def _tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _top_level(text, head):
    """The source of one top-level statement of app.py, from `head` to the
    next line that starts in column 0."""
    i = text.find("\n" + head) + 1
    if not i:
        raise AssertionError("app.py has no top-level %r (is system3_blocks2_patch applied?)" % head)
    out = [text[i:text.index("\n", i) + 1]]
    j = i + len(out[0])
    while j < len(text):
        k = text.index("\n", j) + 1
        line = text[j:k]
        if line.strip() and not line[0].isspace() and not line.startswith(")"):
            break
        out.append(line)
        j = k
    return "".join(out)


def _marker_kit(config):
    """app.py's own marker helpers and door resolver, run against System 3's
    real block engine with `config` - not a copy of them."""
    text = _app_text()
    src = "".join(_top_level(text, h) for h in (
        "_PB_OPEN, _PB_MID, _PB_CLOSE = ", "_PB_TOKEN = ", "_PB_NAME = ",
        "def _pb(", "def _pb_unmark(", "def prompt_blocks_resolve(", "def _pb_within("))
    ns: dict[str, Any] = {"re": re, "Any": Any,
                          "dialogue_tint_wanted": lambda: ns["_tint"], "_tint": False,
                          "dj_settings": lambda: {"personality": 0.7}}
    ns["system3_blocks"] = lambda names, mark, tint, dial: system3.decide_blocks(
        names, config, "t", tint_on=tint, dial=dial)
    exec(compile(src, "app.py[s3-blocks]", "exec"), ns)
    return ns


class EveryBlockIsMarkedTests(unittest.TestCase):
    def test_the_tool_is_applied(self):
        mod = _tool("system3_blocks2_patch")
        text = _app_text()
        applied, missing = mod.check(text)
        self.assertEqual(missing, [])
        self.assertEqual(applied, len(mod.plan(text)), "every block mark is present exactly once")

    def test_every_block_system3_names_has_a_marked_site(self):
        text = _app_text()
        self.assertTrue(_PERSONA_MARK in text, _PERSONA_MARK)
        marked = _marked_names(text) | {"persona", "cohost", "third"}
        self.assertEqual(sorted(n for n in system3_tables.DEFAULT_BLOCKS if n not in marked), [],
                         "a block the table names that no prompt marks is sent but never decided")
        _known = set(system3_tables.DEFAULT_BLOCKS) | set(system3_tables.EVENT_BLOCKS)   # [s3-live-event]
        self.assertEqual(sorted(n for n in marked if n not in _known), [],
                         "a block the station marks with no node is stripped as a wedge")

    def test_the_angle_itself_is_never_marked(self):
        # the round's angle also reaches System 3's director, the call gates
        # and the fallback call script: its inner blocks are marked on the
        # prompt's copy only
        text = _app_text()
        for bad in ("angle += _pb(", "angle = _pb(", "angle += _pb_within(", "angle = _pb_within("):
            self.assertFalse(bad in text, bad)
        for name, part in (("aside", "_angle_aside"), ("theme", "_theme_said"), ("heat", "_hot_said")):
            want = '("%s", %s)' % (name, part)
            self.assertTrue(want in text, want)


class NestedBlockTests(unittest.TestCase):
    def test_kept_is_byte_for_byte_and_stripped_takes_only_its_own_words(self):
        heat = (" BURIED, IN PASSING: somewhere mid-conversation one of you lets slip "
                "a reference to how hot the machine is running.")
        angle = "the gallery's new painting." + heat
        built = "PERSONA\n" + "This time: " + angle + ". Name it.\n" + "TAIL"
        on = _marker_kit(system3.default_config())
        marked = on["_pb_within"]("heat", "PERSONA\n" + "This time: " + on["_pb"]("angle", angle)
                                  + ". Name it.\n" + "TAIL", heat)
        sent, decided = on["prompt_blocks_resolve"](marked)
        self.assertEqual(sent, built)
        self.assertEqual([d["name"] for d in decided], ["angle", "heat"])
        self.assertTrue(all(d["keep"] for d in decided))
        off = _marker_kit(dict(system3.default_config(), blocks={"heat": {"kind": "off"}}))
        sent, decided = off["prompt_blocks_resolve"](marked)
        self.assertEqual(sent, "PERSONA\nThis time: the gallery's new painting.. Name it.\nTAIL")
        self.assertFalse([d for d in decided if d["name"] == "heat"][0]["keep"])
        self.assertIn("BURIED, IN PASSING", [d for d in decided if d["name"] == "heat"][0]["text"])

    def test_the_battle_rides_the_schedule_only_with_the_tint(self):
        kit = _marker_kit(system3.default_config())
        clause = kit["_pb"]("schedule", "SCHEDULE: the news entry.\n" + kit["_pb"]("battle", "THE BATTLE: bars."))
        kit["_tint"] = False
        self.assertEqual(kit["prompt_blocks_resolve"](clause)[0], "SCHEDULE: the news entry.\n")
        kit["_tint"] = True
        self.assertEqual(kit["prompt_blocks_resolve"](clause)[0], "SCHEDULE: the news entry.\nTHE BATTLE: bars.")

    def test_pb_within_leaves_what_it_cannot_find(self):
        kit = _marker_kit(system3.default_config())
        within = kit["_pb_within"]
        self.assertEqual(within("theme", "abc", ""), "abc")
        self.assertEqual(within("theme", "abc", "zz"), "abc")
        got = within("playing", "Now playing: X. RECENT: Now playing: X.", "Now playing: X",
                     after="ROOM: ")
        self.assertEqual(got, "Now playing: X. RECENT: Now playing: X.", "`after` must precede the part")
        got = within("playing", "ROOM: Now playing: X. RECENT: Now playing: X.", "Now playing: X",
                     after="ROOM: ")
        self.assertEqual(kit["_pb_unmark"](got), "ROOM: Now playing: X. RECENT: Now playing: X.")
        self.assertTrue(got.startswith("ROOM: " + kit["_PB_OPEN"] + "playing"))

    def test_every_new_block_is_an_obligation_but_the_battle(self):
        names = ["aside", "avoid_reruns", "battle", "context", "heat", "modifiers", "perf", "playing",
                 "review_guidance", "sheet", "system_prompt", "theme", "topic_contract", "turn_rules"]
        got = {d["name"]: d for d in system3.decide_blocks(names, system3.default_config(), "b2")}
        self.assertEqual(sorted(n for n in names if got[n]["kind"] == "wedge"), [])
        self.assertEqual(sorted(n for n in names if not got[n]["keep"]), ["battle"],
                         "every new block is sent by default; the battle only with the tint")


if __name__ == "__main__":
    unittest.main()
