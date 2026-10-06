"""[pin-sampler] The sampler's draw sets honour the folder pin (2026-10-06).

Run from the repo root:  python3 tests/test_sfx_pin_sampler_2026_10_06.py
"""
import __future__
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")
SLASH = chr(92)


def function_source(name: str) -> str:
    start = APP.index("\ndef %s(" % name) + 1
    end = APP.index("\n\n\ndef ", start)
    return APP[start:end] + "\n"


def norm(p) -> str:
    return str(p).replace(SLASH, "/")


class PinnedSampler(unittest.TestCase):
    def setUp(self):
        self.pin = [""]
        self.cache = [Path("/samples/a/one.mp4"), Path("/samples/a/two.mp4"),
                      Path("/samples/b/three.mp4"), Path("/samples/b/sub/four.mp4")]
        self.ns = {"Any": Any, "Path": Path,
                   "_SFX_POOL_CACHE": self.cache, "_SFX_POOL_AT": [1.0],
                   "_STING_DRAW_MEMO": {"sig": None, "pool": [], "names": [], "fresh": set(), "unheard": set()},
                   "SFX_BANS_PATH": "bans", "SFX_WEIGHTS_PATH": "weights", "SFX_GLUE_PATH": "glue",
                   "_sfx_file_sig": lambda p: 7, "sfx_bans": lambda: set(), "sfx_superseded": lambda: set(),
                   "sfx_weights": lambda: {}, "sfx_id": lambda p: Path(str(p)).stem,
                   "sfx_fresh_paths": lambda pool: [p for p in pool if "two" in str(p)],
                   "sfx_plays": lambda: {"one": {"plays": 3}},
                   "sfx_pin_prefix": lambda: self.pin[0]}
        src = function_source("_sfx_pinned") + "\n\n" + function_source("_sting_draw_sets")
        exec(compile(src, "app.py", "exec", flags=__future__.annotations.compiler_flag, dont_inherit=True), self.ns)

    def draw(self):
        return self.ns["_sting_draw_sets"]()

    def test_no_pin_is_the_whole_pool(self):
        pool, names, fresh = self.draw()
        self.assertEqual(len(pool), 4)
        self.assertEqual(len(names), 4)

    def test_a_pin_narrows_every_set(self):
        self.pin[0] = "/samples/b/"
        pool, names, fresh = self.draw()
        self.assertEqual(sorted(norm(p) for p in pool), ["/samples/b/sub/four.mp4", "/samples/b/three.mp4"], "the pool is the pinned folder and its subfolders")
        self.assertTrue(all(norm(n).startswith("/samples/b/") for n in names), names)
        self.assertEqual(fresh, set(), "fresh is computed over the pinned pool")
        self.assertEqual({norm(n) for n in self.ns["_STING_DRAW_MEMO"]["unheard"]}, {"/samples/b/sub/four.mp4", "/samples/b/three.mp4"}, "unheard too")

    def test_a_new_pin_is_a_new_pool_at_once(self):
        pool, _names, _fresh = self.draw()
        self.assertEqual(len(pool), 4)
        self.pin[0] = "/samples/a/"
        pool, names, _fresh = self.draw()
        self.assertEqual(sorted(norm(p) for p in pool), ["/samples/a/one.mp4", "/samples/a/two.mp4"], "the memo did not serve the old pool")
        self.pin[0] = ""
        pool, _names, _fresh = self.draw()
        self.assertEqual(len(pool), 4, "clearing the pin widens the pool again")

    def test_an_empty_pinned_folder_falls_back_to_everything(self):
        self.pin[0] = "/samples/nothing-here/"
        pool, _names, _fresh = self.draw()
        self.assertEqual(len(pool), 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
