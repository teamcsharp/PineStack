"""[h3-cast][h3-cinematic][h3-budget] The station's side is wired, and the host
trainer's pure pieces hold: captions carry the trigger and the silence, the
graphs are what ComfyUI expects, the dataset is one-frame images, and the
governor stops a job when asked. Pure: no station, no GPU."""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Wiring(unittest.TestCase):
    def test_every_edit_is_in_app_py(self):
        mod = _load("h3_cast_patch", "tools/h3_cast_patch.py")
        text = (ROOT / "app.py").read_bytes().decode("utf-8").replace("\r\n", "\n")
        applied, missing = mod.check(text)
        self.assertEqual(missing, [])
        self.assertEqual(applied, len(mod.plan(text)))
        for bit in ('@app.post("/api/h3/cast/train")', '@app.post("/api/h3/cast/stop")', "def h3_cast_status()",
                    'voice_ad_render(goal, hourly=True)', '"cast": dict(comfy_workshop.CAST)', "frames=frame_count)",
                    "the host's H3 LoRA is training on this box"):
            self.assertIn(bit, text)


class Trainer(unittest.TestCase):
    def setUp(self):
        self.t = _load("h3_cast_train", "tools/h3_cast_train.py")
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_captions_name_the_host_and_the_silence(self):
        c = self.t.caption("laughing, eyes creased")
        self.assertTrue(c.startswith("pinehost, the Pine Box host, laughing, eyes creased."))
        self.assertIn("sound: silence", c)
        self.assertGreaterEqual(len(self.t.VARIATIONS), 16, "enough pictures to learn a face from")

    def test_the_kontext_graph_keeps_the_picture_and_changes_one_thing(self):
        g = self.t.kontext_graph("h3_cast_canonical.png", "Make him smile.", 7)
        self.assertEqual(g["4"]["inputs"]["image"], "h3_cast_canonical.png")
        self.assertEqual(g["8"]["class_type"], "ReferenceLatent")
        self.assertEqual(g["11"]["inputs"]["latent_image"], ["6", 0], "the edit starts from the picture itself")
        self.assertEqual(g["1"]["inputs"]["unet_name"], "flux1-dev-kontext_fp8_scaled.safetensors")

    def test_the_dataset_is_one_frame_images(self):
        self.t.WORK = self.dir
        self.t.IMAGES = os.path.join(self.dir, "images")
        self.t.CACHE = os.path.join(self.dir, "cache")
        text = Path(self.t.write_dataset()).read_text(encoding="utf-8")
        self.assertIn("image_directory", text)
        self.assertIn("batch_size = 1", text)
        self.assertIn("resolution = [640, 640]", text)

    def test_the_newest_save_wins_and_the_final_one_most(self):
        self.t.OUT = self.dir
        for i, name in enumerate(("pinehost-step00000100.safetensors", "pinehost-step00000200.safetensors")):
            p = os.path.join(self.dir, name)
            open(p, "wb").close()
            os.utime(p, (1000 + i, 1000 + i))
        self.assertTrue(self.t.newest_save().endswith("00000200.safetensors"))
        open(os.path.join(self.dir, "pinehost.safetensors"), "wb").close()
        self.assertTrue(self.t.newest_save().endswith("pinehost.safetensors"))

    @unittest.skipUnless(hasattr(os, "killpg"), "the governor is POSIX")
    def test_the_governor_runs_a_cool_job_and_stops_one_on_request(self):
        t = self.t
        t.WORK, t.LOG, t.STATUS, t.STOP = self.dir, os.path.join(self.dir, "log"), os.path.join(self.dir, "s.json"), os.path.join(self.dir, "stop")
        t.hottest = lambda: 60.0
        t.mem_gb = lambda: 100.0
        t.comfy_busy = lambda: False
        seen = []
        code = t.governed([sys.executable, "-c", "print('3/5 [ avr_loss=0.25', flush=True)"], "training",
                          progress=lambda buf: seen.append(buf))
        self.assertEqual(code, 0)
        self.assertTrue(any("3/5 [" in b for b in seen))
        open(t.STOP, "w").close()
        code = t.governed([sys.executable, "-c", "import time; time.sleep(30)"], "training")
        self.assertEqual(code, -15, "a stop request ends the job")
        with open(t.STATUS, encoding="utf-8") as fh:
            self.assertIn("temp_c", json.load(fh))


if __name__ == "__main__":
    unittest.main()
