"""[h3-quality] The profile: presets snap, custom sizes round to the VAE's
stride, the graph renders at the profile, and a hot or full box steps the
doubled profile down. Pure: no station."""
import importlib.util
import unittest
from pathlib import Path

import comfy_workshop as cw

ROOT = Path(__file__).resolve().parents[1]


class H3Quality(unittest.TestCase):
    def setUp(self):
        cw.set_quality({"preset": "double"})

    def tearDown(self):
        cw.set_quality({"preset": "double"})

    def test_the_default_is_double(self):
        self.assertEqual(cw.QUALITY["preset"], "double")
        self.assertEqual((cw.QUALITY["steps"], cw.QUALITY["width"], cw.QUALITY["height"]), (8, 1280, 768))
        self.assertEqual(cw.PRESETS["standard"]["width"] * 2, cw.PRESETS["double"]["width"])

    def test_a_custom_size_rounds_to_the_stride_and_a_preset_is_recognised(self):
        got = cw.set_quality({"steps": 7, "width": 1000, "height": 600})
        self.assertEqual((got["steps"], got["width"], got["height"], got["preset"]), (6, 960, 576, "custom"))   # 7 snaps to the nearer-first 6
        got = cw.set_quality({"preset": "custom", "steps": 6, "width": 960, "height": 576, "max_frames": 289})
        self.assertEqual(got["preset"], "balanced")
        got = cw.set_quality({"preset": "standard"})
        self.assertEqual(got, cw.PRESETS["standard"])
        got = cw.set_quality({"width": 99999, "height": 1})
        self.assertEqual((got["width"], got["height"]), (cw.SIZE_MAX, cw.SIZE_MIN))

    def test_the_graph_renders_at_the_profile_and_caps_the_length(self):
        graph = cw.build_workflow("a test", mode="text", frames=361)
        node = graph["6"]["inputs"]
        self.assertEqual((node["width"], node["height"]), (1280, 768))
        self.assertEqual(node["length"], 243, "double caps the clip at ten seconds, on the lattice")
        self.assertEqual(graph["8"]["inputs"]["steps"], 8)
        graph = cw.build_workflow("a test", mode="text", frames=361, steps=4, width=640, height=384, max_frames=362)
        self.assertEqual((graph["6"]["inputs"]["width"], graph["6"]["inputs"]["length"], graph["8"]["inputs"]["steps"]), (640, 362, 4))

    def test_a_hot_or_full_box_steps_the_double_down(self):
        prof, note = cw.quality_for_box(66.0, 94.0, 90.0, 60.0)
        self.assertEqual((prof["preset"], note), ("double", ""))
        prof, note = cw.quality_for_box(85.0, 94.0, 90.0, 60.0)
        self.assertEqual(prof["preset"], "balanced")
        self.assertIn("85 C", note)
        prof, note = cw.quality_for_box(66.0, 70.0, 90.0, 60.0)
        self.assertEqual(prof["preset"], "balanced")
        self.assertIn("GB", note)
        cw.set_quality({"preset": "balanced"})
        prof, note = cw.quality_for_box(89.0, 50.0, 90.0, 60.0)
        self.assertEqual(prof["preset"], "standard")
        cw.set_quality({"preset": "standard"})
        prof, note = cw.quality_for_box(95.0, 10.0, 90.0, 60.0)
        self.assertEqual((prof["preset"], note), ("standard", ""), "the standard profile is the gate's business, not this one's")
        prof, note = cw.quality_for_box(None, None, 90.0, 60.0)
        self.assertEqual(note, "", "no reading is no reason to step down; the gate refuses a blind video render itself")

    def test_every_length_is_on_the_lattice(self):
        # H3 takes 17n+5 frames at 24 fps; 169/241/289/361 were snapped silently
        self.assertTrue(all(f % 17 == 5 for f in cw.FRAME_CHOICES), cw.FRAME_CHOICES)
        self.assertEqual(cw.lattice_frames(169), 175)
        self.assertEqual(cw.lattice_frames(241), 243)
        self.assertEqual(cw.lattice_frames(0), 5)
        self.assertTrue(all(p["max_frames"] in cw.FRAME_CHOICES for p in cw.PRESETS.values()))

    def test_the_brief_carries_timed_shots_sound_and_constraints(self):
        text = cw.compose_prompt("A host at the desk", "Pine Box FM, the sound of the valley.", "video", "reference", seconds=10.125)
        self.assertIn("[0 to 2.5 seconds]", text)
        self.assertIn("[8.1 to 10.125 seconds]", text)
        self.assertIn("<d>[English] Pine Box FM, the sound of the valley.</d>", text)
        self.assertEqual(text.count("<d>[English]"), 1, "the line is spoken once")
        self.assertIn("audio_direction:", text)
        self.assertIn("constraints:", text)
        self.assertIn("one style only", text)
        untimed = cw.compose_prompt("A host at the desk", "", "video", "reference")
        self.assertIn("[Shot 1]", untimed)
        self.assertNotIn("seconds]", untimed)
        plain = cw.compose_prompt("A station ident", "Pine Box FM.", "", "text", seconds=5.0)
        self.assertIn("shots:", plain)
        self.assertIn("[0 to 1.2 seconds]", plain)

    def test_easycache_shift_and_sampler_in_the_graph(self):
        g = cw.build_workflow("a test", mode="text")
        self.assertEqual(g["18"]["class_type"], "EasyCache")
        self.assertEqual(g["7"]["inputs"]["model"], ["18", 0])
        self.assertEqual(g["8"]["inputs"]["model"], ["18", 0])
        self.assertEqual(g["18"]["inputs"]["model"], ["5", 0])
        self.assertEqual(g["9"]["class_type"], "MiniMaxH3TurboSampler")
        self.assertEqual(g["8"]["inputs"]["scheduler"], "simple")
        g = cw.build_workflow("a test", mode="text", easycache=False)
        self.assertNotIn("18", g)
        self.assertEqual(g["7"]["inputs"]["model"], ["5", 0])
        g = cw.build_workflow("a test", mode="text", shift=[12, 3], sampler="euler", scheduler="beta")
        self.assertEqual(g["19"]["class_type"], "MiniMaxH3SigmaShift")
        self.assertEqual((g["19"]["inputs"]["shift_video"], g["19"]["inputs"]["shift_audio"]), (12.0, 3.0))
        self.assertEqual(g["18"]["inputs"]["model"], ["19", 0])
        self.assertEqual(g["9"], {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}})
        self.assertEqual(g["8"]["inputs"]["scheduler"], "beta")
        got = cw.set_quality({"preset": "double", "sampler": "nonesuch", "scheduler": "beta", "shift": [12, 3]})
        self.assertEqual((got["sampler"], got["scheduler"], got["shift"]), ("turbo", "beta", [12.0, 3.0]))
        cw.set_quality({"preset": "double"})
        self.assertNotIn("shift", cw.QUALITY)

    def test_the_door_times_the_brief(self):
        spec = importlib.util.spec_from_file_location("h3_prompt_patch", ROOT / "tools" / "h3_prompt_patch.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        text = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")
        applied, missing = mod.check(text)
        self.assertEqual(missing, [])
        self.assertEqual(applied, len(mod.plan(text)))

    def test_every_edit_is_in_app_py(self):
        spec = importlib.util.spec_from_file_location("h3_quality_patch", ROOT / "tools" / "h3_quality_patch.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        text = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")
        applied, missing = mod.check(text)
        self.assertEqual(missing, [])
        self.assertEqual(applied, len(mod.plan(text)))


if __name__ == "__main__":
    unittest.main()
