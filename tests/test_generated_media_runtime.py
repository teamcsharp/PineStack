import asyncio
import copy
import unittest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from generated_media_runtime import MediaEvents, completed_outputs, install


class GeneratedMediaTests(unittest.TestCase):
    def setUp(self):
        self.rows = [{"prompt_id": "old", "files": ["old.png"], "status": "done", "kind": "image", "model": "comfy"},
                     {"prompt_id": "slow", "files": [], "status": "queued", "kind": "video", "purpose": "parody_stinger"}]
        self.events = MediaEvents(lambda: copy.deepcopy(self.rows), lambda value: "signed:" + value)
        self.cursor = self.events.page()["cursor"]

    def test_old_archive_is_baseline(self):
        self.assertEqual(self.events.page()["events"], [])
        self.assertEqual(self.events.page(self.cursor)["events"], [])

    def test_older_queued_job_completing_after_new_jobs(self):
        self.rows.append({"prompt_id": "new", "status": "queued", "files": []})
        self.rows[1].update(status="done", files=["stinger.mp4"])
        page = self.events.page(self.cursor)
        self.assertEqual([r["file"] for r in page["events"]], ["stinger.mp4"])
        self.assertIn("media/stinger.mp4?t=signed%3Agen%3Astinger.mp4", page["events"][0]["url"])

    def test_every_type_and_output_in_batch(self):
        self.rows.append({"prompt_id": "all", "status": "done", "purpose": "ad", "kind": "video", "files": ["one.png", "two.mp4", "three.wav", "four.json"]})
        items = self.events.page(self.cursor)["events"]
        self.assertEqual([r["kind"] for r in items], ["image", "video", "audio", "file"])
        self.assertEqual(len({r["id"] for r in items}), 4)
        self.assertTrue(items[0]["poster"].endswith("&w=480"))
        self.assertEqual(items[1]["poster_request"], "/api/generations/poster-url/two.mp4")

    def test_ledger_mutations_do_not_reannounce(self):
        self.rows[1].update(status="done", files=["clip.mp4"])
        first = self.events.page(self.cursor)
        self.rows[1].update(analysis="New analysis", favorite=True)
        self.assertEqual(self.events.page(first["cursor"])["events"], [])
        self.rows[1]["files"].append("extra.png")
        self.assertEqual([r["file"] for r in self.events.page(first["cursor"])["events"]], ["extra.png"])

    def test_pagination_never_skips_events(self):
        self.rows.extend({"prompt_id": str(i), "status": "done", "files": [f"{i}.png"]} for i in range(350))
        seen = []
        cursor = self.cursor
        while True:
            page = self.events.page(cursor, 100)
            seen.extend(r["file"] for r in page["events"])
            cursor = page["cursor"]
            if not page["more"]:
                break
        self.assertEqual(len(seen), 350)
        self.assertEqual(len(set(seen)), 350)

    def test_reconnect_and_restart_no_archive_replay(self):
        self.rows[1].update(status="done", files=["clip.mp4"])
        self.assertEqual(len(self.events.page(self.cursor)["events"]), 1)
        # Same cursor can safely be retried by the client with stable identities.
        self.assertEqual(self.events.page(self.cursor)["events"][0]["id"], self.events.page(self.cursor)["events"][0]["id"])
        reset = MediaEvents(lambda: self.rows, lambda value: "s").page(self.cursor)
        self.assertTrue(reset["reset"])
        self.assertEqual(reset["events"], [])

    def test_non_comfy_and_invalid_files_are_not_notices(self):
        rows = [{"prompt_id": "p", "status": "done", "files": ["../escape.png", "a/b.png", "a\\b.png", "safe.webp"]},
                {"prompt_id": "news", "status": "done", "model": "gazette", "files": ["gazette.png"]},
                {"prompt_id": "notyet", "status": "failed", "files": ["failed.png"]}]
        self.assertEqual([r["file"] for r in completed_outputs(rows)], ["safe.webp"])

    def test_auth_and_selected_batch_output_analysis(self):
        analyzed = []
        async def look(row):
            analyzed.append(row["files"])
            return "Second frame description"
        def auth(token):
            if token != "Bearer test":
                raise HTTPException(401, "Unauthorized")
        self.rows[1].update(status="done", files=["first.mp4", "second.mp4"])
        app = FastAPI()
        install({"app": app, "_read_all_generations": lambda: self.rows, "media_sign": lambda s: "s",
                 "require_read_auth": auth, "require_auth": auth,
                 "workshop_generation": lambda pid: self.rows[1], "workshop_analyze_generation": look})
        client = TestClient(app)
        self.assertEqual(client.get("/api/generated-media/events").status_code, 401)
        identity = next(row["id"] for row in completed_outputs(self.rows) if row["file"] == "second.mp4")
        headers = {"Authorization": "Bearer test"}
        self.assertEqual(client.get("/api/generated-media/item/" + identity, headers=headers).json()["file"], "second.mp4")
        got = client.post("/api/generated-media/analyze/" + identity, headers=headers)
        self.assertEqual(got.status_code, 200)
        self.assertEqual(analyzed, [["second.mp4"]])
        self.assertEqual(self.rows[1]["files"], ["first.mp4", "second.mp4"])


if __name__ == "__main__":
    unittest.main()
