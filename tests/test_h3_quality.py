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
        self.assertEqual(node["length"], 241, "double caps the clip at ten seconds")
        self.assertEqual(graph["8"]["inputs"]["steps"], 8)
        graph = cw.build_workflow("a test", mode="text", frames=361, steps=4, width=640, height=384, max_frames=361)
        self.assertEqual((graph["6"]["inputs"]["width"], graph["6"]["inputs"]["length"], graph["8"]["inputs"]["steps"]), (640, 361, 4))

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
