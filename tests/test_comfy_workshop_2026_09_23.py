from pathlib import Path
import unittest

import comfy_workshop as workshop


ROOT = Path(__file__).resolve().parents[1]


class WorkflowTests(unittest.TestCase):
    def test_video_render_interval_defaults_and_clamps_to_one_or_two_minutes(self):
        self.assertEqual(workshop.render_interval_seconds(), 90.0)
        self.assertEqual(workshop.render_interval_seconds("90"), 90.0)
        self.assertEqual(workshop.render_interval_seconds(1), 60.0)
        self.assertEqual(workshop.render_interval_seconds(500), 120.0)
        self.assertEqual(workshop.render_interval_seconds("not-a-number"), 90.0)

    def test_text_graph_is_h3_av_and_clamped(self):
        graph = workshop.build_workflow("late-night station ident", frames=99,
                                        steps=99)
        self.assertEqual(graph["1"]["inputs"]["unet_name"], workshop.FL2VA_MODEL)
        self.assertEqual(graph["6"]["class_type"], "MiniMaxH3ImageToVideo")
        self.assertNotIn("first_frame", graph["6"]["inputs"])
        self.assertIn(graph["6"]["inputs"]["length"], workshop.FRAME_CHOICES)
        self.assertEqual(graph["8"]["inputs"]["steps"], 6)
        self.assertEqual(graph["14"]["inputs"]["audio"], ["13", 0])

    def test_frame_graph_loads_first_frame(self):
        graph = workshop.build_workflow(
            "move slowly", mode="frame", upload_name="pine/frame.jpg",
            media_kind="image")
        self.assertEqual(graph["16"]["class_type"], "LoadImage")
        self.assertEqual(graph["6"]["inputs"]["first_frame"], ["16", 0])

    def test_reference_video_uses_dotted_autogrow_paths(self):
        graph = workshop.build_workflow(
            "speak to camera", mode="reference", upload_name="pine/ref.mp4",
            media_kind="video")
        inputs = graph["6"]["inputs"]
        self.assertEqual(graph["1"]["inputs"]["unet_name"], workshop.REF2VA_MODEL)
        self.assertEqual(graph["16"]["class_type"], "LoadVideo")
        self.assertEqual(graph["17"]["class_type"], "GetVideoComponents")
        self.assertEqual(inputs["ref_videos.ref_video_0"], ["17", 0])
        self.assertEqual(inputs["ref_video_audios.ref_video_audio_0"], ["17", 1])
        self.assertNotIn("ref_video_0", inputs)

    def test_reference_still_and_audio_use_their_own_sockets(self):
        still = workshop.build_workflow(
            "portrait", mode="reference", upload_name="face.png",
            media_kind="image")
        audio = workshop.build_workflow(
            "voice texture", mode="reference", upload_name="voice.wav",
            media_kind="audio")
        self.assertEqual(still["6"]["inputs"]["ref_images.ref_image_0"], ["16", 0])
        self.assertEqual(audio["16"]["class_type"], "LoadAudio")
        self.assertEqual(audio["6"]["inputs"]["ref_audios.ref_audio_0"], ["16", 0])

    def test_prompt_names_reference_and_exact_dialogue(self):
        prompt = workshop.compose_prompt(
            "A calm close-up", "This is the line.", "video", "reference")
        self.assertIn("<Video 1>", prompt)
        self.assertIn('says exactly: "This is the line."', prompt)

    def test_quoted_copy_becomes_exact_ad_speech(self):
        self.assertEqual(
            workshop.quoted_speech(
                'Move toward camera and say "Welcome to the Pine Box".'),
            "Welcome to the Pine Box")
        self.assertEqual(
            workshop.quoted_speech('First “Stay tuned” then "Right here".'),
            "Stay tuned Right here")

    def test_media_modes_require_compatible_source(self):
        with self.assertRaises(ValueError):
            workshop.build_workflow("x", mode="frame", media_kind="audio",
                                    upload_name="x.wav")
        with self.assertRaises(ValueError):
            workshop.build_workflow("x", mode="reference")

    def test_variants_get_fresh_seeds_and_explicit_seeds_repeat(self):
        first = workshop.build_workflow("take one")
        second = workshop.build_workflow("take two")
        self.assertNotEqual(first["10"]["inputs"]["noise_seed"],
                            second["10"]["inputs"]["noise_seed"])
        fixed = workshop.build_workflow("repeatable", seed=8675309)
        self.assertEqual(fixed["10"]["inputs"]["noise_seed"], 8675309)


class IntegrationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = (ROOT / "app.py").read_text(encoding="utf-8")
        cls.js = (ROOT / "frontend" / "comfy-workshop.js").read_text(encoding="utf-8")
        cls.css = (ROOT / "frontend" / "comfy-workshop.css").read_text(encoding="utf-8")

    def test_workshop_routes_are_authenticated_and_registered(self):
        self.assertIn('@app.get("/api/comfy/workshop")', self.app)
        self.assertIn('@app.post("/api/comfy/workshop")', self.app)
        self.assertIn('@app.post("/api/comfy/workshop/variant")', self.app)
        self.assertIn('@app.get("/api/comfy/workshop/reference/{prompt_id}")', self.app)
        self.assertIn("require_read_auth(authorization)", self.app)
        self.assertIn("require_auth(authorization)", self.app)
        self.assertIn('{key: "comfyworkshop"', self.app)
        self.assertIn('/comfy-workshop/comfy-workshop.js?v=1', self.app)

    def test_tracking_preserves_video_and_air_metadata(self):
        self.assertIn('str(gen.get("kind") or "image")', self.app)
        self.assertIn('bool(gen.get("air_it"))', self.app)
        self.assertIn("workshop_publish_files, files, prompt_id", self.app)
        self.assertIn('render_admission(kind)', self.app)
        self.assertIn('purpose == "image_ad"', self.app)
        self.assertIn('speech = comfy_workshop.quoted_speech(prompt)', self.app)
        self.assertIn('"source_generation": str(', self.app)

    def test_panel_is_bounded_and_has_no_horizontal_scroll(self):
        self.assertIn("overflow-x:hidden", self.css)
        self.assertIn("minmax(0,1fr)", self.css)
        self.assertIn("92dvh", self.css)
        self.assertIn('source_type:selected ? selected.sourceType : ""', self.js)
        self.assertIn("previewMedia.currentTime / previewMedia.duration", self.js)

    def test_gallery_compares_reference_and_preserves_variant_lineage(self):
        self.assertIn('id="lbWipe"', self.app)
        self.assertIn('id="lbCompareMode"', self.app)
        self.assertIn("syncLightboxReference", self.app)
        self.assertIn('"variant_of": str(parent.get("prompt_id")', self.app)
        self.assertIn('source_type = "generation"', self.app)
        self.assertIn('PineWallTransition.cover(video', self.app)

    def test_video_interval_keeps_thermal_and_memory_admission_gates(self):
        self.assertIn(
            'VIDEO_RENDER_INTERVAL_S = comfy_workshop.render_interval_seconds(',
            self.app)
        self.assertIn('os.getenv("VIDEO_RENDER_INTERVAL_S"', self.app)
        admission = self.app[self.app.index('def render_admission(kind: str)'):
                             self.app.index('async def _submit_generation',
                                            self.app.index('def render_admission(kind: str)'))]
        self.assertLess(admission.index('hot >= RENDER_TEMP_CEILING_C'),
                        admission.index('since < VIDEO_RENDER_INTERVAL_S'))
        self.assertLess(admission.index('since < VIDEO_RENDER_INTERVAL_S'),
                        admission.index('if avail < floor'))
        self.assertIn('render_admission(kind)', self.app)
        self.assertIn('"video_render_interval_seconds":', self.app)

    def test_reference_endpoint_explains_unresolvable_sources(self):
        view = self.app[self.app.index('def workshop_reference_view('):
                        self.app.index('@app.get("/api/comfy/workshop/reference/',
                                       self.app.index('def workshop_reference_view('))]
        self.assertIn('"reason": "This generation did not record', view)
        self.assertIn('"reason": str(exc)', view)

    def test_public_listener_wake_cannot_clear_operator_pause(self):
        route = self.app[self.app.index('async def radio_unpause_listener_api('):
                         self.app.index('@app.post("/api/radio/tune")',
                                        self.app.index(
                                            'async def radio_unpause_listener_api('))]
        self.assertIn('was = radio_paused()', route)
        self.assertIn('"paused": radio_paused()', route)
        self.assertIn('listener play cannot resume it', route)
        self.assertNotIn('radio_pause_set(', route)
        self.assertNotIn('dj_start(', route)
        self.assertNotIn('sfx_video_mode_on()', route)


if __name__ == "__main__":
    unittest.main()
