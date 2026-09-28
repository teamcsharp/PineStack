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

    def test_every_single_line_has_a_road(self):
        # [s3-lines] the strict gate withholds a line whose road System 3 does not know
        spec = importlib.util.spec_from_file_location("system3_lines_patch", ROOT / "tools" / "system3_lines_patch.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        text = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")
        applied, missing = mod.check(text)
        self.assertEqual(missing, [])
        self.assertEqual(applied, len(mod.plan(text)))
        self.assertNotIn('"single_line")', text)

    def test_the_script_pin_edits_are_in_app_py(self):
        # [#1314][#1315] a withdrawn row leaves the spine; a heard row keeps its first slot
        spec = importlib.util.spec_from_file_location("script_pin_patch", ROOT / "tools" / "script_pin_patch.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        text = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")
        applied, missing = mod.check(text)
        self.assertEqual(missing, [])
        self.assertEqual(applied, len(mod.plan(text)))

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


    def test_the_tapped_line_has_timing_and_parameters(self):
        # [s3-timing] [s3-params] the clocks and a profiler snapshot of the
        # station while the line was made; every parameter, folded, with its
        # control - and the strip that opens them
        src = (ROOT / "frontend" / "system3.js").read_text(encoding="utf-8")
        for marker in ("async function paintTiming(host)", "async function paintParams(host)",
                       "timing: paintTiming, params: paintParams", "/api/pulse?since=", "function paramFold("):
            self.assertIn(marker, src)
        page = (ROOT / "desktop" / "renderer" / "script-page.js").read_text(encoding="utf-8")
        self.assertIn("['timing', 'Timing'], ['params', 'Parameters']", page)
        app = (ROOT / "app.py").read_bytes().decode("utf-8")
        self.assertIn("def pulse_report(window: float = 600.0, since: float | None = None,", app)
        css = (ROOT / "frontend" / "system3.css").read_text(encoding="utf-8")
        for rule in (".s3-timeline", ".s3-param", ".s3-prof"):
            self.assertIn(rule, css)


    def test_the_rewrite_passes_are_rolls(self):
        # [s3-rewrite] TINT per turn, REPAIR and ROOM per round, read by the
        # station's passes and shown by the Messenger
        app = (ROOT / "app.py").read_bytes().decode("utf-8")
        for marker in ("only_turns: Any = None) -> dict[str, Any]:   # [s3-rewrite]", "_s3_repair = (globals()[\"system3_repair_roll\"](_s3)",
                       "system3_room_allowed", "system3_tint_turns_entry", "_s3_repair is not True and _radio_draft_review"):
            self.assertIn(marker, app)
        eng = (ROOT / "system3.py").read_text(encoding="utf-8")
        for marker in ("def _tint_decision(", "def _rewrite_rolls(", '"TINT", "REPAIR", "ROOM"'):
            self.assertIn(marker, eng)
        src = (ROOT / "frontend" / "system3.js").read_text(encoding="utf-8")
        for marker in ("if (fam === 'TINT' || fam === 'REPAIR' || fam === 'ROOM')", "function roundRolls(conv)", "TINT: ['tint'], REPAIR: ['repair'], ROOM: ['room']"):
            self.assertIn(marker, src)

    def test_the_rounds_edits_are_in_app_py_and_the_editor(self):
        # [s3-rounds] the harvest yields, a deferred or empty writer withholds the
        # round (never the seed alone), beats drop spoken lines, the four prompt
        # randoms stand down under System 3, the panel imports v5
        spec = importlib.util.spec_from_file_location("system3_rounds_patch", ROOT / "tools" / "system3_rounds_patch.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        text = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")
        applied, missing = mod.check(text)
        self.assertEqual(missing, [])
        self.assertEqual(applied, len(mod.plan(text)))
        for marker in ('globals().get("system3_withhold")', "async def _harvest_yields(", "async def _live_round_waits(",
                       "def _beat_fresh_only(", "def harvest_unrepaired(", 'mark={"kind": "harvest"}',
                       "HARVEST_PAUSE_AFTER = 5", '_HARVEST_BAD["__pause_until__"]'):
            self.assertIn(marker, text)
        # the panel's module version moves with every batch (v5 rounds, v6 wave A);
        # what matters is that it moved past the pre-rounds v4
        self.assertRegex(text, r'system3\.js\?v=([5-9]|[1-9][0-9])"')
        self.assertNotIn('system3.js?v=4', text)
        src = (ROOT / "frontend" / "system3.js").read_text(encoding="utf-8")
        for marker in ("TEMPER: ['Temper (TEMPER1)'", "CARRY: ['Carry", "WITHHELD: ['Withheld'", "const versionsCard = () =>",
                       "const saved = (what, res) =>", "SHOCK: ['shock_beat']"):
            self.assertIn(marker, src)
        css = (ROOT / "frontend" / "system3.css").read_text(encoding="utf-8")
        self.assertIn(".s3-ok", css)

    def test_the_cast_and_hygiene_edits_are_in_app_py(self):
        # [s3-cast] the Mind desk's notes and the thumbs-up are System 3 tables
        # (FAV1, DIRECTIVE1) - nothing is stapled to a prompt any more;
        # [s3-hygiene] the record-talk and prompt-hygiene hunks another session
        # left uncommitted, assimilated and recorded
        text = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")
        for tool in ("system3_cast_patch", "system3_hygiene_patch"):
            spec = importlib.util.spec_from_file_location(tool, ROOT / "tools" / (tool + ".py"))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            applied, missing = mod.check(text)
            self.assertEqual(missing, [], tool)
            self.assertEqual(applied, len(mod.plan(text)), tool)
        self.assertNotIn("mind_adjustment_prompt(", text)
        self.assertNotIn("LIVE MIND ADJUSTMENTS", text)
        self.assertNotIn('"it, and you may repeat it."', text)
        self.assertIn('globals().get("system3_favorite")', text)
        src = (ROOT / "frontend" / "system3.js").read_text(encoding="utf-8")
        for marker in ("FAV: ['Favourite (FAV1)'", "DIRECTIVE: [\"Operator's directive (DIRECTIVE1)\"", "function poolFields(item)",
                       "const TABLE_FAMILIES = ['CTS', 'ES', 'RS', 'IRS', 'FL', 'TEMPER', 'SHOCK', 'INTERJECT', 'SPEAKERBOX', 'FAV', 'DIRECTIVE'",
                       "startTab.includes(':')"):
            self.assertIn(marker, src)

    def test_a_call_the_roulette_ends_keeps_its_ending(self):
        # [s3-events] the call contract waives the sign-off and the landing for a
        # call System 3's EVENT roll ended, at every gate that grades a call
        spec = importlib.util.spec_from_file_location("system3_events_patch", ROOT / "tools" / "system3_events_patch.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        text = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")
        applied, missing = mod.check(text)
        self.assertEqual(missing, [])
        self.assertEqual(applied, len(mod.plan(text)))
        self.assertEqual(text.count('ended=str('), 5)
        src = (ROOT / "frontend" / "system3.js").read_text(encoding="utf-8")
        for marker in ("function eventFields(cat)", "EVENT: ['Happening (CALLEVENT1", "'EVENT'"):
            self.assertIn(marker, src)

    def test_every_road_rolls_system3s_dice_and_every_prompt_block_is_a_node(self):
        # [s3-dice-door] the banter, speakbox, SFX Guy and segment roads' rolls;
        # [s3-blocks] the writer's door and the marks on every prompt block
        text = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")
        for tool in ("system3_dice_banter_patch", "system3_dice_speakbox_patch", "system3_dice_sfx_patch",
                     "system3_dice_segments_patch", "system3_blocks_patch"):
            spec = importlib.util.spec_from_file_location(tool, ROOT / "tools" / (tool + ".py"))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            applied, missing = mod.check(text)
            self.assertEqual(missing, [], tool)
            self.assertEqual(applied, len(mod.plan(text)), tool)
        import re
        import system3_tables
        marked = set(re.findall(r"""_pb\(\s*['"]([a-z_]+)['"]""", text)) | {"persona", "cohost", "third"}
        self.assertEqual(sorted(n for n in marked if n not in system3_tables.DEFAULT_BLOCKS), [],
                         "every block the station marks has a node (else it is stripped as a wedge)")
        src = (ROOT / "frontend" / "system3.js").read_text(encoding="utf-8")
        for marker in ("function promptBlocksBox(request, userText)", "section('blocks',",
                       "function segTableCats(fam)", "class: 'txt s3-after'", "who opens the round "):   # [s3-flow]
            self.assertIn(marker, src)

    def test_the_stations_own_dice_are_system3s(self):
        # [s3-dice-door] the call, manager and ad roads roll through System 3's
        # dice door; every roll a desk row (STATION1 / POOLS1)
        spec = importlib.util.spec_from_file_location("system3_dice_patch", ROOT / "tools" / "system3_dice_patch.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        text = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")
        applied, missing = mod.check(text)
        self.assertEqual(missing, [])
        self.assertEqual(applied, len(mod.plan(text)))
        for marker in ("def s3_chance(", "def s3_pool(", "class _S3Dice:", "def s3_weighted(", "def s3_roll("):
            self.assertIn(marker, text)
        src = (ROOT / "frontend" / "system3.js").read_text(encoding="utf-8")
        for marker in ("STATION: ['Station roll (STATION1 / POOLS1)'", "'CHANCE', 'POOL'", "follows the station's own value"):
            self.assertIn(marker, src)


if __name__ == "__main__":
    unittest.main()
