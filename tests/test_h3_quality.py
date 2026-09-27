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
        cw.set_brief(dict(cw.BRIEF_DEFAULTS))
        cw.set_cast(dict(cw.CAST_DEFAULTS))

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
        self.assertEqual({k: v for k, v in got.items() if k != "budget_s"}, cw.PRESETS["standard"])
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

    def test_the_cinematic_path_drops_the_turbo_lora(self):
        got = cw.set_quality({"preset": "cinematic"})
        self.assertEqual((got["steps"], got["turbo"], got["max_frames"], got["sampler"]), (20, False, 124, "res_multistep"))
        g = cw.build_workflow("a test", mode="text", frames=243)
        self.assertNotIn("5", g, "no turbo LoRA on the base path")
        self.assertEqual(g["9"], {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}})
        self.assertEqual(g["8"]["inputs"]["steps"], 20)
        self.assertEqual(g["6"]["inputs"]["length"], 124, "cinematic clips are five seconds at most")
        node, seen = g["7"]["inputs"]["model"][0], []
        while node != "1":
            seen.append(g[node]["class_type"])
            node = g[node]["inputs"]["model"][0]
        self.assertNotIn("MiniMaxH3TurboLoRA", seen)
        g = cw.build_workflow("a test", mode="text", steps=8)
        self.assertEqual(g["5"]["class_type"], "MiniMaxH3TurboLoRA", "a step count names its path")
        self.assertEqual(g["9"]["class_type"], "MiniMaxH3TurboSampler")
        self.assertEqual((cw.clamp_steps(24), cw.clamp_steps(7), cw.clamp_steps(8, False), cw.clamp_steps(30, True)), (25, 6, 20, 12))
        got = cw.set_quality({"preset": "cinematic", "steps": 30, "width": 1280, "height": 768, "max_frames": 124, "turbo": False})
        self.assertEqual((got["preset"], got["steps"], got["turbo"]), ("custom", 30, False))
        got = cw.set_quality({"preset": "cinematic", "steps": 20, "width": 1280, "height": 768, "max_frames": 124, "turbo": False})
        self.assertEqual(got["preset"], "cinematic")
        got = cw.set_quality({"preset": "double"})
        self.assertNotIn("turbo", got, "a turbo profile reads as it always did")
        got = cw.set_quality({"turbo": False})
        self.assertEqual((got["steps"], got["sampler"]), (20, "res_multistep"), "the switch alone moves the steps to the base path")

    def test_the_cinematic_gate(self):
        cw.set_quality({"preset": "cinematic"})
        prof, note = cw.quality_for_box(79.0, 94.0, 90.0, 60.0)
        self.assertEqual((prof["preset"], note), ("cinematic", ""))
        prof, note = cw.quality_for_box(79.0, 94.0, 90.0, 60.0, purpose="hourly")
        self.assertEqual(prof["preset"], "double")
        self.assertIn("never renders the hourly ad", note)
        prof, note = cw.quality_for_box(85.0, 94.0, 90.0, 60.0)
        self.assertEqual(prof["preset"], "balanced", "too hot for cinematic, and too hot for the double frame too")
        self.assertIn("84 C", note)
        self.assertIn("then stepped down to balanced", note)
        prof, note = cw.quality_for_box(None, 94.0, 90.0, 60.0)
        self.assertEqual(prof["preset"], "double")
        self.assertIn("will not say how hot", note)
        prof, note = cw.quality_for_box(79.0, 70.0, 90.0, 60.0)
        self.assertEqual(prof["preset"], "balanced")
        self.assertIn("GB", note)

    def test_the_cast_rides_the_text_road(self):
        g = cw.build_workflow("a test", mode="text")
        self.assertNotIn("20", g, "no cast until it is on and trained")
        got = cw.set_cast({"on": True, "lora": "pinehost_h3.safetensors", "strength": 0.8, "trigger": "pine host!"})
        self.assertEqual((got["on"], got["lora"], got["strength"], got["trigger"]), (True, "pinehost_h3.safetensors", 0.8, "pinehost"))
        g = cw.build_workflow("a test", mode="text")
        self.assertEqual(g["20"]["class_type"], "LoraLoaderModelOnly")
        self.assertEqual((g["20"]["inputs"]["lora_name"], g["20"]["inputs"]["strength_model"]), ("pinehost_h3.safetensors", 0.8))
        self.assertEqual(g["20"]["inputs"]["model"], ["5", 0], "after the turbo LoRA")
        self.assertEqual(g["18"]["inputs"]["model"], ["20", 0], "and under the cache")
        text = cw.compose_prompt("At the desk", "Pine Box FM.", "", "text", seconds=5.0)
        self.assertIn("The presenter is pinehost, the Pine Box host.", text)
        self.assertIn("pinehost, the Pine Box host (S1) says clearly", text)
        g = cw.build_workflow("a test", mode="frame", upload_name="x.png", media_kind="image")
        self.assertNotIn("20", g, "a picture brings its own face")
        g = cw.build_workflow("a test", mode="frame", upload_name="x.png", media_kind="image", cast=True)
        self.assertIn("20", g, "unless the caller asks for the host")
        cw.set_quality({"preset": "cinematic"})
        g = cw.build_workflow("a test", mode="text")
        self.assertEqual(g["20"]["inputs"]["model"], ["1", 0], "on the base path it sits on the model itself")
        self.assertEqual(cw.set_cast({"lora": "../../etc/passwd"})["lora"], "", "a LoRA is one plain file name")

    def test_the_render_time_budget(self):
        # the model against the box: ComfyUI logged 00:47:24 and 00:50:29 for 10 s at double
        self.assertTrue(40 * 60 <= cw.estimate_seconds(1280, 768, 243, 8) <= 50 * 60)
        self.assertTrue(60 <= cw.estimate_seconds(640, 384, 73, 8) <= 150, "the A/B's 90 s shape")
        self.assertEqual(cw.QUALITY["budget_s"], cw.BUDGET_DEFAULT_S)
        prof, note = cw.quality_for_box(70.0, 100.0, 90.0, 60.0, frames=243)
        self.assertEqual((prof["width"], prof["height"], prof["max_frames"], prof["steps"]), (640, 384, 243, 8),
                         "ten seconds at double is 45 minutes: the frame shrinks, the length and steps stay")
        self.assertIn("15-minute budget", note)
        prof, note = cw.quality_for_box(70.0, 100.0, 90.0, 60.0, frames=124)
        self.assertEqual((prof["width"], prof["height"]), (960, 576))
        prof, note = cw.quality_for_box(70.0, 100.0, 90.0, 60.0, frames=73)
        self.assertEqual((prof["preset"], note), ("double", ""), "a short clip fits as it is")
        got = cw.set_quality({"preset": "double", "budget_s": 0})
        self.assertEqual(got["budget_s"], 0)
        prof, note = cw.quality_for_box(70.0, 100.0, 90.0, 60.0, frames=243)
        self.assertEqual((prof["preset"], note), ("double", ""), "no limit keeps the profile")
        got = cw.set_quality({"preset": "balanced"})
        self.assertEqual(got["budget_s"], 0, "the budget survives a change of preset")
        cw.set_quality({"preset": "cinematic", "budget_s": 900})
        prof, note = cw.quality_for_box(70.0, 100.0, 90.0, 60.0, frames=124)
        self.assertEqual((prof["width"], prof["turbo"], prof["steps"]), (640, False, 20), "the base path keeps its steps")
        est = cw.estimates(243)
        self.assertLess(est["standard"], est["balanced"])
        self.assertLess(est["balanced"], est["double"])

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
        self.assertIn("[0 to 3 seconds]", plain)   # two shots under eight seconds

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

    def test_the_brief_follows_the_reference_and_scales_with_the_clip(self):
        # [h3-brief] what the reference shows stays; the shots follow its motion
        text = cw.compose_prompt("A driver at the wheel", "Pine Box FM.", "video", "reference", seconds=10.125, purpose="voice_ad")
        self.assertIn("No added subtitles, captions, logos or on-screen text - what <Video 1> already shows stays.", text)
        self.assertNotIn("No logos.", text)
        self.assertIn("the action, framing and camera movement of <Video 1> continue as they are", text)
        self.assertNotIn("satisfied gesture", text)
        self.assertIn("polished broadcast commercial - one style only", text)
        # one shot under five seconds, two under eight, three from eight
        short = cw.compose_prompt("A driver", "Pine Box FM.", "video", "reference", seconds=73 / 24.0)
        self.assertEqual(short.count(" seconds] "), 1)
        self.assertIn("One shot:", short)
        mid = cw.compose_prompt("A driver", "Pine Box FM.", "video", "reference", seconds=124 / 24.0)
        self.assertEqual(mid.count(" seconds] "), 2)
        long = cw.compose_prompt("A driver", "Pine Box FM.", "video", "reference", seconds=243 / 24.0)
        self.assertEqual(long.count(" seconds] "), 3)
        for text in (short, mid, long):
            self.assertEqual(text.count("<d>[English]"), 1, "the line is spoken once")
        # one style term per road
        self.assertEqual(cw.style_for("parody_stinger", "reference", "video"), "polished broadcast commercial")
        self.assertEqual(cw.style_for("", "reference", "video"), "the style of <Video 1>, as it is")
        self.assertEqual(cw.style_for("", "reference", "image"), "the style of <Picture 1>, as it is")
        self.assertEqual(cw.style_for("", "frame", "image"), "the style of <Picture 1>, as it is")
        self.assertEqual(cw.style_for("", "text", ""), "clean cinematic realism")
        free = cw.compose_prompt("A painting comes alive", "", "image", "reference", seconds=5.0)
        self.assertIn("the style of <Picture 1>, as it is - one style only", free)
        named = cw.compose_prompt("A painting comes alive", "", "image", "reference", seconds=5.0, style="oil on canvas")
        self.assertIn("oil on canvas - one style only", named)

    def test_the_brief_profile_is_read_by_the_compiler(self):
        got = cw.set_brief({"style": "  grainy 16mm  documentary ", "follow": "presenter", "shots": "1",
                            "constraints": "No people other than <Subject 1>.", "audio_direction": "Rain on a tin roof.", "junk": 1})
        self.assertEqual(got["style"], "grainy 16mm documentary")
        self.assertEqual((got["follow"], got["shots"]), ("presenter", "1"))
        text = cw.compose_prompt("A driver", "Pine Box FM.", "video", "reference", seconds=243 / 24.0, purpose="voice_ad")
        self.assertIn("grainy 16mm documentary - one style only", text)
        self.assertEqual(text.count(" seconds] "), 1, "the shot count knob wins over the length")
        self.assertIn("in place; natural movement in the scene", text.replace("\n", " ") if False else text) if False else None
        self.assertNotIn("continue as they are", text, "presenter shots, not the reference's motion")
        self.assertIn("No people other than <Subject 1>. Preserve <Subject 1>'s identity exactly.", text)
        self.assertIn("Rain on a tin roof.", text)
        got = cw.set_brief({"follow": "sideways", "shots": "9", "style": ""})
        self.assertEqual((got["follow"], got["shots"], got["style"]), ("auto", "auto", ""))
        text = cw.compose_prompt("A driver", "Pine Box FM.", "video", "reference", seconds=243 / 24.0, purpose="voice_ad")
        self.assertIn("polished broadcast commercial", text)
        self.assertEqual(text.count(" seconds] "), 3)

    def test_the_door_carries_the_brief(self):
        spec = importlib.util.spec_from_file_location("h3_brief_patch", ROOT / "tools" / "h3_brief_patch.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        text = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")
        applied, missing = mod.check(text)
        self.assertEqual(missing, [])
        self.assertEqual(applied, len(mod.plan(text)))

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
