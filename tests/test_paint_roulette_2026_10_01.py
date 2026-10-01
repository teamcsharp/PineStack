"""[paint-roulette] the pair's attitude when selling a painting, and how a caller takes one."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import system3_tables as T  # noqa: E402

APP = (ROOT / "app.py").read_text(encoding="utf-8")


class Tables(unittest.TestCase):
    def test_resolve3_has_the_operators_reactions(self):
        t = next(x for x in T.default_tables() if x["id"] == "RESOLVE3")
        self.assertEqual(t["family"], "RESOLVE")
        for cat in t["categories"]:
            ids = {i["id"] for i in cat["items"]}
            for want in ("accepts", "loves", "hates", "insulted", "disturbed", "intimidated",
                         "claims_any_cost", "destroys_any_cost"):
                self.assertIn(want, ids)
            self.assertGreaterEqual(len(ids), 16, "heavily varied")
            for i in cat["items"]:
                self.assertIn(i["effect"], ("sold", "unsold", "claimed", "destroyed"))
        self.assertEqual({c["id"]: c["requires"] for c in t["categories"]}, {"painting": ["painting"], "pile": ["unsold"]})

    def test_new_fates_pass_through_and_leave_the_pile(self):
        s3 = (ROOT / "system3.py").read_text(encoding="utf-8")
        self.assertIn('"sold", "awarded", "burnt", "unsold", "claimed", "destroyed"', s3)
        self.assertIn('if effect in ("sold", "awarded", "burnt", "claimed", "destroyed"):', APP)
        self.assertIn("gallery_fate_note(effect, painting, cid)", APP)


class Attitudes(unittest.TestCase):
    def test_mostly_off_script(self):
        m = re.search(r"GALLERY_SELL_ATTITUDES = \((.*?)\n\)\n", APP, re.S)
        rows = re.findall(r'\("([a-z_]+)", ([0-9.]+),', m.group(1))
        w = {k: float(v) for k, v in rows}
        self.assertAlmostEqual(w["straight"] / sum(w.values()), 0.25, places=2)
        for k in ("disparage", "mock", "offended_painting", "offended_selling", "existential", "disturbing",
                  "speakerbox"):
            self.assertIn(k, w)

    def test_every_sale_rolls_it(self):
        self.assertEqual(APP.count('+ gallery_sell_attitude("'), 3)   # gallery round, sales floor, banter hawk
        self.assertIn('s3_weighted("gallery.sell_attitude"', APP)
        self.assertIn('s3_weighted("gallery.sell_sb_doc"', APP)


if __name__ == "__main__":
    unittest.main()
