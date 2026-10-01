"""[unheard-air] lines going out that nobody hears are a fault, and the air goes back."""
import ast
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "app.py").read_text(encoding="utf-8")


def _ns(radio, owner="", paused=False):
    tree = ast.parse(SRC)
    keep = [n for n in tree.body
            if (isinstance(n, ast.FunctionDef) and n.name == "unheard_air_check")
            or (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in
                ("UNHEARD_AIR_S", "UNHEARD_WHO", "AIR_PUBLICATION_STATES") for t in n.targets))]
    ns = {"Any": Any, "time": __import__("time"), "_RADIO": radio,
          "radio_paused": lambda: paused, "audio_owner": lambda: owner}
    exec(compile(ast.Module(keep, []), "app.py", "exec"), ns)
    return ns


NOW = 10_000.0


def rows(n, heard=False, aired="published", who="dj", step=30.0):
    out = []
    for i in range(n):
        r = {"who": who, "aired": aired, "air_at": NOW - 200 + i * step}
        if heard:
            r["heard_ack_at"] = r["air_at"] + 1
        out.append(r)
    return out


class Check(unittest.TestCase):
    def test_published_and_unheard_is_a_fault(self):
        ns = _ns({"on": True, "voice_to": "here", "chat": rows(6)})
        got = ns["unheard_air_check"](NOW)
        self.assertIsNotNone(got)
        self.assertGreaterEqual(got["lines"], 3)

    def test_one_heard_line_is_a_show(self):
        chat = rows(6)
        chat[-1]["heard_ack_at"] = NOW - 30
        self.assertIsNone(_ns({"on": True, "voice_to": "here", "chat": chat})["unheard_air_check"](NOW))

    def test_the_box_hearing_it_counts(self):
        self.assertIsNone(_ns({"on": True, "voice_to": "both", "chat": rows(6, aired="box")})["unheard_air_check"](NOW))

    def test_off_air_paused_or_routed_to_the_box_only_says_nothing(self):
        self.assertIsNone(_ns({"on": False, "voice_to": "here", "chat": rows(6)})["unheard_air_check"](NOW))
        self.assertIsNone(_ns({"on": True, "voice_to": "here", "chat": rows(6)}, paused=True)["unheard_air_check"](NOW))
        self.assertIsNone(_ns({"on": True, "voice_to": "box", "chat": rows(6)})["unheard_air_check"](NOW))

    def test_stings_and_a_short_stretch_are_not_a_fault(self):
        self.assertIsNone(_ns({"on": True, "voice_to": "here", "chat": rows(6, who="board")})["unheard_air_check"](NOW))
        short = [{"who": "dj", "aired": "published", "air_at": NOW - 60 + i * 10} for i in range(4)]
        self.assertIsNone(_ns({"on": True, "voice_to": "here", "chat": short})["unheard_air_check"](NOW))


class Wiring(unittest.TestCase):
    def test_the_watch_runs_and_lifts_the_rest(self):
        self.assertIn('radio_worker_start("unheard", unheard_air_watch)', SRC)
        self.assertIn("_OWNER_DEAF.pop(_owner_deaf_key(live), None)", SRC)
        self.assertIn("NOBODY IS HEARING THE SHOW", SRC)


if __name__ == "__main__":
    unittest.main()
