"""System 3 is wired into app.py exactly as tools/system3_patch_app.py
describes, and the panel script that carries its button still parses."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def patch_module():
    spec = importlib.util.spec_from_file_location("system3_patch_app", ROOT / "tools" / "system3_patch_app.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class WiringTests(unittest.TestCase):
    def test_every_hook_is_in_app_py(self):
        mod = patch_module()
        text = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")
        applied, missing = mod.check(text)
        self.assertEqual(missing, [])
        self.assertEqual(applied, len(mod.plan(text)), "every System 3 hook is present exactly once")

    def test_every_road_edit_is_in_app_py(self):
        # [s3-roads] every road names itself, the SFX Guy's node answers both
        # gates, the single-voice roads go through the line hook, and every
        # single line's origin reaches the ledger
        spec = importlib.util.spec_from_file_location("system3_roads_patch", ROOT / "tools" / "system3_roads_patch.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        text = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")
        applied, missing = mod.check(text)
        self.assertEqual(missing, [])
        self.assertEqual(applied, len(mod.plan(text)), "every road edit is present exactly once")
        for name in ("system3_direct_line", "system3_bind_line", "system3_sfxguy_direction",
                     "system3_sfxguy_chooser", "system3_sfxguy_spoke"):
            self.assertIn('globals().get("%s")' % name, text)

    def test_every_glass_edit_is_in_app_py(self):
        # [s3-glass] the length roll and the record link's bind
        spec = importlib.util.spec_from_file_location("system3_glass_patch", ROOT / "tools" / "system3_glass_patch.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        text = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")
        applied, missing = mod.check(text)
        self.assertEqual(missing, [])
        self.assertEqual(applied, len(mod.plan(text)), "every glass edit is present exactly once")

    def test_every_link_edit_is_in_app_py(self):
        # [s3-link] a ledger row finds its turn by its words
        spec = importlib.util.spec_from_file_location("system3_link_patch", ROOT / "tools" / "system3_link_patch.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        text = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")
        applied, missing = mod.check(text)
        self.assertEqual(missing, [])
        self.assertEqual(applied, len(mod.plan(text)))
        self.assertIn('globals().get("system3_turn_id_for")', text)

    def test_hooks_are_guarded(self):
        text = (ROOT / "app.py").read_bytes().decode("utf-8")
        for name in ("system3_door_roll", "system3_bind_entry", "system3_perf_state",
                     "system3_sfx_direction", "system3_observe_ledger"):
            self.assertIn('globals().get("%s")' % name, text)

    def test_messenger_chips_and_lines_open(self):
        # A chip opens its decision card; a line a speaker-box passage went
        # into opens in place with the passages above and below it.
        src = (ROOT / "frontend" / "system3.js").read_text(encoding="utf-8")
        self.assertIn("openDecision(conv, ev, t, v.api)", src)
        self.assertIn("open ? composeLine(conv, t, v.api) : body", src)
        self.assertIn("v.toggle = (t, node)", src)
        # a lost roll opens to its odds and the dials; its chip is gray and
        # says why; the Messenger is a live feed with SFX Guy in it
        for marker in ("function oddsPanel(", "function sbOutcome(", "'/api/dj/dial'", "v.buildRound = async",
                       "function sfxEntry(", "function sfxPlanRow(", "'/api/system3/events?'"):
            self.assertIn(marker, src)
        css = (ROOT / "frontend" / "system3.css").read_text(encoding="utf-8")
        for rule in (".s3.s3-modal-back", ".s3-compose", ".s3-sb-pre", ".s3-sb-app", ".s3-pieces",
                     ".s3-odds", ".s3-round-head", ".s3-sfxguy", ".s3-diamond.miss"):
            self.assertIn(rule, css)


    def test_a_roll_shows_its_document_and_line_and_the_cuts_say_why(self):
        src = (ROOT / "frontend" / "system3.js").read_text(encoding="utf-8")
        # after a speaker-box roll: the document it drew, then the line in
        # the lines the draw was cut from (GET /api/speakbox/{name}?lines=1)
        for marker in ("function docReels(", "function lineRoll(", "function docRoll(", "'?lines=1'",
                       "playReels(rolled, reels, 900)", "doc: (file, mind) => docLines(request, file, mind)"):
            self.assertIn(marker, src)
        # the dials fold shut under their heading until tapped
        self.assertIn("el('details', {class: 's3-odds-fold', open}", src)
        # an opened line never prints "null": append() turns a null into text
        self.assertIn("put(box, oddsPanel(conv, t, api), verdict, setup)", src)
        self.assertNotIn("box.append(oddsPanel(", src)
        # a line never heard says why, with the switch for the system that did it
        for marker in ("function cutNote(", "function openCutPanel(", "'/api/orchestrator/policy'",
                       "'/api/orchestrator/logic'", "cutNote(cutWhy, v)"):
            self.assertIn(marker, src)
        css = (ROOT / "frontend" / "system3.css").read_text(encoding="utf-8")
        for rule in (".s3-linereel", ".s3-rollcap", ".s3-odds-fold", ".s3-cutnote", ".s3-cutrow"):
            self.assertIn(rule, css)


    def test_topics_come_up_only_through_the_roulette(self):
        # [rng-topics] the station's own topic roads answer the switch, and the
        # passes that rewrite a System 3 round are skipped on its rounds
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        for marker in ('elif verb == "topics":', 'if orch_policy("topics_by_rng", True) is not False:\n        return {}',
                       "def _sfxguy_topics_rest(", "_s3_directed = bool(_s3 is not None",
                       "if _prepared and _dealt and not _s3_directed:",
                       '@app.post("/api/dj/topics/{topic_id}/edit")'):
            self.assertIn(marker, app)
        src = (ROOT / "frontend" / "system3.js").read_text(encoding="utf-8")
        for marker in ("TOPIC: 'var(--topic)'", "TOPIC: ['topics']", "if (fam === 'TOPIC')", "v.rebuildTurn = async",
                       "jumpToAir(lineId) { return jumpTo(lineId); }", "const THUMB = {stop: null};"):
            self.assertIn(marker, src)


if __name__ == "__main__":
    unittest.main()
