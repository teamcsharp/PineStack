"""Focused Gazette media checks: bounded work, durable recovery and scene identity."""
import asyncio
import copy
import json
from pathlib import Path
import tempfile
import unittest

import gazette_media


class GazetteMediaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().set_debug(False)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = 10000.0
        self.submits = []
        self.attachments = []
        self.records = {}
        self.hold = None
        self.fail_image = False
        self.rolled = []
        self.manager = self.make_manager()
        self.edition = "2026-10-04-12"
        self.publish(self.edition)

    def publish(self, edition):
        folder = self.root / edition
        folder.mkdir()
        (folder / "edition.json").write_text("{}", encoding="utf-8")

    def article(self, filename="01-city.md", headline="Mayor defends secret contract"):
        return {
            "file": filename,
            "meta": {"headline": headline, "section": "gallery",
                     "editorial": {"id": "city-arc-123", "fictional": True, "format": "hidden_camera",
                                   "topic": {"id": "roads", "text": "road repairs"},
                                   "cast": ["Mayor Ada"], "reaction": "doubles down",
                                   "emotion": "indignant",
                                   "media": {
                                       "image_prompt": "Fictional Mayor Ada in a secret road-contract meeting.",
                                       "video_prompt": "Mayor Ada becomes indignant defending the same road contract.",
                                   }}},
            "body": "The mayor defended the contract in the fictional city.",
        }

    async def image(self, prompt, context):
        self.submits.append(("image", prompt, context))
        if self.fail_image:
            raise RuntimeError("GPU busy")
        if self.hold is not None:
            await self.hold.wait()
        self.records["picture-ticket"] = {"status": "done", "files": ["mayor.png"]}
        return {"prompt_id": "picture-ticket", "model": "comfy"}

    async def video(self, payload):
        self.submits.append(("video", payload))
        self.records["reaction-ticket"] = {"status": "done", "files": ["mayor.mp4"]}
        return {"prompt_id": "reaction-ticket", "model": "h3"}

    async def attach(self, edition, article, kind, url, receipt):
        self.attachments.append((edition, article, kind, url, copy.deepcopy(receipt)))

    def pick(self, key, labels, weights, label):
        self.rolled.append((key, labels, weights))
        return len(labels) - 1

    async def advance(self, seconds):
        self.now += seconds
        await asyncio.sleep(0)

    def make_manager(self, overrides=None):
        return gazette_media.GazetteMedia(
            lambda edition: self.root / edition, self.image, self.video,
            lambda ticket: self.records.get(ticket), self.attach,
            lambda file, kind: "/api/generations/" + ("image/" if kind == "image" else "media/") + file + "?t=signed",
            lambda file: file in ("mayor.png", "mayor.mp4"), self.pick,
            policy={"deadline_s": 1, "poll_s": 0.1, **(overrides or {})},
            clock=lambda: self.now, sleep=self.advance,
        )

    def receipt(self, edition=None):
        return json.loads((self.root / (edition or self.edition) / "media.json").read_text(encoding="utf-8"))

    async def test_scene_identity_and_video_follow_generated_image(self):
        self.assertTrue((await self.manager.run(self.edition, [self.article()]))["started"])
        await self.manager.idle()
        self.assertEqual([row[0] for row in self.submits], ["image", "video"])
        payload = self.submits[-1][1]
        self.assertEqual(payload["mode"], "frame")
        self.assertEqual(payload["source"], "mayor.png")
        self.assertEqual(payload["source_type"], "generation")
        self.assertEqual(payload["purpose"], "gazette_reaction")
        self.assertFalse(payload["air_it"])
        receipt = self.receipt()
        self.assertEqual(receipt["status"], "ready")
        self.assertEqual(receipt["video"]["file"], "mayor.mp4")
        self.assertEqual(receipt["reaction"], "doubles down")
        self.assertEqual(receipt["editorial_id"], "city-arc-123")
        self.assertEqual([a[2] for a in self.attachments if a[3]], ["image", "video"])

    async def test_roulette_selects_article_with_own_prompt(self):
        articles = [self.article("01-city.md", "First scandal"),
                    self.article("02-city.md", "Second scandal")]
        articles[1]["meta"]["editorial"]["media"]["image_prompt"] = "The second scandal only."
        await self.manager.run(self.edition, articles)
        await self.manager.idle()
        self.assertEqual(self.receipt()["article"], "02-city.md")
        self.assertEqual(self.submits[0][1], "The second scandal only.")
        self.assertEqual(self.rolled[0][0], "gazette.media.story")

    async def test_caps_and_repeat_edition_prevent_duplicate_submissions(self):
        manager = self.make_manager({"videos": 0})
        await manager.run(self.edition, [self.article()])
        await manager.idle()
        self.assertEqual([s[0] for s in self.submits], ["image"])
        result = await manager.run(self.edition, [self.article()])
        self.assertFalse(result["started"])
        self.assertEqual(len(self.submits), 1)

    async def test_worker_and_hour_interval_bound_extra_editions(self):
        self.hold = asyncio.Event()
        await self.manager.run(self.edition, [self.article()])
        newer = "2026-10-04-12x1230"
        self.publish(newer)
        while not self.submits:
            await asyncio.sleep(0)
        result = await self.manager.run(newer, [self.article()])
        self.assertIn("already being followed", result["reason"])
        self.hold.set()
        await self.manager.idle()
        result = await self.manager.run(newer, [self.article()])
        self.assertIn("between intervals", result["reason"])
        self.assertEqual(len(self.submits), 2)
        restarted = self.make_manager()
        result = await restarted.run(newer, [self.article()])
        self.assertIn("between intervals", result["reason"])

    async def test_gate_refusal_has_receipt_and_does_not_retry(self):
        self.fail_image = True
        await self.manager.run(self.edition, [self.article()])
        await self.manager.idle()
        receipt = self.receipt()
        self.assertEqual(receipt["image"]["status"], "refused")
        self.assertIn("GPU busy", receipt["image"]["reason"])
        self.assertEqual(receipt["video"]["status"], "ready")
        self.assertEqual(self.submits[-1][1]["mode"], "text")
        self.assertFalse((await self.manager.recover([self.edition]))["started"])
        self.assertEqual(len(self.submits), 2)

    async def test_pending_ticket_recovers_without_repeating_submission(self):
        async def pending_image(prompt, context):
            self.submits.append(("image", prompt, context))
            self.records["pending"] = {"status": "queued", "files": []}
            return {"prompt_id": "pending", "model": "comfy"}
        self.manager.submit_image = pending_image
        await self.manager.run(self.edition, [self.article()])
        await self.manager.idle()
        self.assertEqual(self.receipt()["status"], "deferred")
        self.records["pending"] = {"status": "done", "files": ["mayor.png"]}
        recovered = self.make_manager()
        self.assertTrue((await recovered.recover([self.edition]))["started"])
        await recovered.idle()
        self.assertEqual(len(self.submits), 1)
        self.assertEqual(self.receipt()["image"]["status"], "ready")
        self.assertTrue(any(a[2] == "image" for a in self.attachments))

    async def test_finished_wrong_media_or_missing_output_is_not_evidence(self):
        self.manager.exists = lambda filename: False
        await self.manager.run(self.edition, [self.article()])
        await self.manager.idle()
        self.assertEqual(self.receipt()["status"], "failed")
        self.assertFalse(any(a[3] for a in self.attachments))
        self.assertEqual(gazette_media.render(self.receipt()), "")

    async def test_only_explicit_fiction_can_request_media(self):
        article = self.article()
        article["meta"]["editorial"]["fictional"] = False
        result = await self.manager.run(self.edition, [article])
        self.assertFalse(result["started"])
        self.assertFalse(self.submits)
        article["meta"]["editorial"]["fictional"] = True
        article["file"] = "../outside.md"
        self.assertFalse(gazette_media.candidates([article]))

    async def test_recovery_never_retries_ambiguous_ticketless_submission(self):
        receipt = {
            "edition": self.edition, "article": "01-city.md", "status": "working",
            "image": {"status": "submitting", "attempted": True},
            "video": {"status": "disabled"},
        }
        (self.root / self.edition / "media.json").write_text(json.dumps(receipt))
        self.assertFalse((await self.manager.recover([self.edition]))["started"])
        self.assertEqual(self.receipt()["status"], "interrupted")
        self.assertFalse(self.submits)

    def test_render_uses_signed_local_assets_and_marks_fiction(self):
        media = {
            "image": {"status": "ready", "url": "/api/generations/image/mayor.png?t=signed"},
            "video": {"status": "ready", "url": "/api/generations/media/mayor.mp4?t=signed",
                      "caption": 'Fictional reaction scene: <Mayor "Ada">'},
        }
        markup = gazette_media.render(media)
        self.assertIn("<video controls playsinline", markup)
        self.assertIn('poster="/api/generations/image/mayor.png?t=signed"', markup)
        self.assertIn("&lt;Mayor &quot;Ada&quot;&gt;", markup)
        self.assertNotIn("<img", markup, "poster and image must not duplicate the same scene")
        self.assertGreater(gazette_media.estimate(media, 200), 112.5)
        media["video"]["url"] = "javascript:alert(1)"
        media["image"]["url"] = "https://unrelated.test/evidence.png"
        self.assertEqual(gazette_media.render(media), "")

    async def test_same_id_reprint_stops_old_worker_before_attaching_assets(self):
        self.hold = asyncio.Event()
        await self.manager.run(self.edition, [self.article()])
        while not self.submits:
            await asyncio.sleep(0)
        folder = self.root / self.edition
        (folder / "edition.json").write_text('{"at": 2}', encoding="utf-8")
        (folder / "media.json").unlink()
        self.hold.set()
        await self.manager.idle()
        self.assertFalse((folder / "media.json").exists())
        self.assertFalse(any(attachment[3] for attachment in self.attachments))


    async def test_disabled_policy_prevents_pending_recovery(self):
        receipt = {
            "edition": self.edition, "article": "01-city.md", "status": "deferred",
            "image": {"status": "queued", "prompt_id": "existing-ticket", "attempted": True},
            "video": {"status": "disabled"},
        }
        (self.root / self.edition / "media.json").write_text(json.dumps(receipt))
        disabled = self.make_manager({"enabled": False})
        self.assertFalse((await disabled.recover([self.edition]))["started"])
        self.assertFalse(self.submits)
        self.assertEqual(self.receipt()["status"], "deferred")

    async def test_lost_generation_finishes_without_polling_forever(self):
        async def lost_image(prompt, context):
            self.submits.append(("image", prompt, context))
            self.records["lost-ticket"] = {"status": "lost", "error": "Output archive lost"}
            return {"prompt_id": "lost-ticket"}
        manager = self.make_manager({"videos": 0})
        manager.submit_image = lost_image
        await manager.run(self.edition, [self.article()])
        await manager.idle()
        self.assertEqual(self.receipt()["status"], "failed")
        self.assertIn("Output archive lost", self.receipt()["image"]["reason"])
        self.assertEqual(self.now, 10000)

    def test_nonfinite_policies_keep_defaults(self):
        configured = gazette_media.policy({"interval_s": float("nan"),
                                           "deadline_s": float("inf"),
                                           "duration_s": float("-inf")})
        self.assertEqual(configured["interval_s"], gazette_media.DEFAULT_POLICY["interval_s"])
        self.assertEqual(configured["deadline_s"], gazette_media.DEFAULT_POLICY["deadline_s"])
        self.assertEqual(configured["duration_s"], gazette_media.DEFAULT_POLICY["duration_s"])


    def test_printable_poster_and_reaction_link_keep_real_scene_identity(self):
        media = {
            "image": {"status": "ready", "url": "/api/generations/image/mayor.png?t=signed",
                      "caption": "Fictional city scene of the road contract."},
            "video": {"status": "ready", "url": "/api/generations/media/mayor.mp4?t=signed",
                      "caption": "Fictional reaction scene of the same mayor."},
        }
        scene = gazette_media.printable(media)
        self.assertEqual(scene["image"], media["image"]["url"])
        self.assertEqual(scene["video"], media["video"]["url"])
        self.assertEqual(scene["caption"], media["video"]["caption"])
        self.assertIn("fictional", scene["link_label"])

    def test_malformed_or_pending_stages_do_not_break_static_exports(self):
        self.assertEqual(gazette_media.render({"image": "bad", "video": 5}), "")
        self.assertEqual(gazette_media.estimate({"image": "bad"}, 200), 0)
        scene = gazette_media.printable({"image": {"status": "queued", "url": "/api/generations/image/no.png"}})
        self.assertEqual(scene["image"], "")
        self.assertEqual(scene["video"], "")


    def test_policies_have_hard_caps(self):
        configured = gazette_media.policy({"images": 200, "videos": -2, "duration_s": 90,
                                           "deadline_s": 90000, "interval_s": 0})
        self.assertEqual(configured["images"], 1)
        self.assertEqual(configured["videos"], 0)
        self.assertEqual(configured["duration_s"], 8)
        self.assertEqual(configured["deadline_s"], 2400)
        self.assertEqual(configured["interval_s"], 60)


if __name__ == "__main__":
    unittest.main()
