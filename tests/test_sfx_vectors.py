"""The SFX Guy's vector section: the store on its own (schema, clips,
anchors, tags, dialogue, query, backup and restore with new roots) and the
station wiring (the keeper's tick against a stand-in clip book, the doors)."""
import asyncio
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import sfx_vectors
import sfx_vectors_runtime

CLIPS = [
    {"sid": "c1", "path": "/samples/tiktok/12 the cat dragged him into the sewer.mp4", "name": "12 the cat dragged him into the sewer",
     "folder": "tiktok", "video": 1, "seconds": 6.0, "said": "the cat dragged him straight into the sewer", "seen_desc": "cat, street, night"},
    {"sid": "c2", "path": "/samples/tiktok/40 i am so angry right now.mp3", "name": "40 i am so angry right now",
     "folder": "tiktok", "video": 0, "seconds": 3.0, "said": "i am so angry right now i could scream"},
    {"sid": "c3", "path": "/samples/iasip/07 lets dance at the party.mp4", "name": "07 lets dance at the party",
     "folder": "iasip", "video": 1, "seconds": 8.0, "said": "let's dance, it's a party, everybody dance", "seen_desc": "neon lights, crowd"},
    {"sid": "c4", "path": "/app/data/sfx/made/laugh-track.mp3", "name": "laugh track", "folder": "made", "video": 0, "seconds": 2.0,
     "said": "hahaha that is hilarious"},
    {"sid": "c5", "path": "/samples/tiktok/0301 clip-4.mp4", "name": "0301 clip-4", "folder": "tiktok", "video": 1, "seconds": 5.0},
]


def embed():
    return sfx_vectors.fake_embedder()


def fill(store):
    store.upsert_clips(CLIPS)
    e = embed()
    todo = store.anchors_to_embed()
    store.put_anchor_vectors(todo, e([t[2] for t in todo]))
    batch = store.clips_to_embed(100)
    store.put_clip_vectors([r["sid"] for r in batch], e([store.clip_text(r) for r in batch]))
    store.tag_clips(limit=100, floor=0.0, per_facet=2)
    return e


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "section"
        self.store = sfx_vectors.Store(self.root, roots={"samples": "/samples", "made": "/app/data/sfx"})
        self.addCleanup(self.store.close)

    def test_paths_are_root_relative_and_resolve_here(self):
        self.store.upsert_clips(CLIPS)
        got = self.store.clip("c1")
        self.assertEqual(got["root"], "samples")
        self.assertEqual(got["rel_path"], "tiktok/12 the cat dragged him into the sewer.mp4")
        self.assertEqual(got["path"], "/samples/tiktok/12 the cat dragged him into the sewer.mp4")
        self.assertEqual(self.store.clip("c4")["root"], "made")
        self.assertEqual(self.store.clip("c4")["rel_path"], "made/laugh-track.mp3")
        self.assertEqual(self.store.split_path("/elsewhere/x.mp4"), ("other", "/elsewhere/x.mp4"))
        counts = self.store.counts()
        self.assertEqual(counts["clips"], 5)
        self.assertEqual(counts["clips_embedded"], 0)

    def test_anchors_tag_embedded_clips_and_a_change_retags(self):
        e = fill(self.store)
        counts = self.store.counts()
        self.assertEqual(counts["clips_embedded"], 5)
        self.assertEqual(counts["clips_tagged"], 5)
        self.assertGreater(counts["anchors"], 60)
        c3 = self.store.clip("c3")
        self.assertTrue(c3["facets"], "every facet has a closest anchor")
        for facet, tags in c3["facets"].items():
            self.assertIn(facet, sfx_vectors.ANCHOR_FACETS)
            self.assertLessEqual(len(tags), 2)
        # a changed transcript loses its vector and tags until the keeper returns
        self.store.upsert_clips([dict(CLIPS[2], said="quiet now, nobody dance")])
        self.assertFalse(self.store.clip("c3")["embedded"])
        self.assertEqual(self.store.clip("c3")["facets"], {})
        self.assertEqual(len(self.store.clips_to_embed(10)), 1)
        # editing the categorisation re-embeds only the changed anchors and re-tags all
        facets = dict(self.store.facets)
        facets["emotional"] = {"description": "x", "anchors": [("anger", "angry"), ("glee", "gleeful and laughing")]}
        self.store.save_facets(facets)
        self.store.refresh_anchors()
        self.store.retag_all()
        todo = self.store.anchors_to_embed()
        self.assertEqual({t[1] for t in todo if t[0] == "emotional"}, {"anger", "glee"})
        self.assertEqual(self.store.counts()["clips_tagged"], 0)

    def test_query_lexical_semantic_and_facets(self):
        e = fill(self.store)
        got = self.store.query("a cat in the sewer", embed=e, k=3)
        self.assertEqual(got["results"][0]["sid"], "c1")
        self.assertIn("lexical", got["results"][0]["why"])
        self.assertIn("semantic", got["results"][0]["why"])
        self.assertTrue(got["embedded"])
        self.assertEqual(got["results"][0]["path"], "/samples/tiktok/12 the cat dragged him into the sewer.mp4")
        only_audio = self.store.query("angry scream", embed=e, video=False, k=3)
        self.assertTrue(all(not r["video"] for r in only_audio["results"]))
        self.assertEqual(only_audio["results"][0]["sid"], "c2")
        # words alone, no embedder: lexical still answers
        plain = self.store.query("dance party", embed=None, k=3)
        self.assertEqual(plain["results"][0]["sid"], "c3")
        self.assertFalse(plain["embedded"])
        # a facet filter keeps only clips carrying an asked tag
        tag = self.store.clip("c2")["facets"]["emotional"][0][0]
        filtered = self.store.query("angry", embed=e, facets={"emotional": [tag]}, k=5)
        self.assertTrue(all(tag in [t for t, _w in r["facets"].get("emotional", [])] for r in filtered["results"]))
        # tags alone, no words
        tags_only = self.store.query("", embed=e, facets={"emotional": [tag]}, k=5)
        self.assertTrue(tags_only["results"])
        self.assertLessEqual(len(self.store.query("cat", embed=e, k=1, max_seconds=4.0)["results"]), 1)

    def test_dialogue_ties_to_its_audio_and_its_clip(self):
        self.store.upsert_clips(CLIPS)
        n = self.store.upsert_dialogue([
            {"id": "take:1", "kind": "take", "who": "drop", "voice": "vl_1", "text": "Well butter my butt and call me a biscuit.",
             "path": "/app/data/voice_media/abc.wav", "at": 1.0},
            {"id": "quip:1", "kind": "quip", "who": "drop", "text": "Do we need to do that every single time?", "clip_sid": "c1"}])
        self.assertEqual(n, 2)
        batch = self.store.dialogue_to_embed(10)
        self.assertEqual({r["id"] for r in batch}, {"take:1", "quip:1"})
        self.store.put_dialogue_vectors([r["id"] for r in batch], embed()([r["text"] for r in batch]))
        self.assertEqual(self.store.counts()["dialogue_embedded"], 2)
        self.assertEqual(self.store.clip("c1")["dialogue"][0]["id"], "quip:1")
        row = self.store.con.execute("select root, rel_path from dialogue where id='take:1'").fetchone()
        self.assertEqual(row, ("other", "/app/data/voice_media/abc.wav"))

    def test_backup_and_restore_elsewhere_with_new_roots(self):
        e = fill(self.store)
        self.store.upsert_dialogue([{"id": "quip:1", "kind": "quip", "who": "drop", "text": "hello there", "clip_sid": "c1"}])
        out = self.store.backup(Path(self.tmp.name) / "backups", label="quarantine",
                                extra_files={"crystals/doom.json": json.dumps({"crystal": "doom", "chunks": []}).encode()})
        self.assertTrue(out.name.startswith("sfx_vectors-quarantine-") and out.name.endswith(".tar.gz"))
        target = Path(self.tmp.name) / "elsewhere"
        other = sfx_vectors.Store.restore(out, target, roots={"samples": "D:/clips", "made": "D:/made"})
        self.addCleanup(other.close)
        self.assertEqual(other.counts(), self.store.counts())
        self.assertEqual(other.clip("c1")["path"], "D:/clips/tiktok/12 the cat dragged him into the sewer.mp4")
        self.assertEqual(other.clip("c4")["path"], "D:/made/made/laugh-track.mp3")
        self.assertEqual(other.manifest["restored_from"], out.name)
        self.assertTrue((target / "crystals" / "doom.json").is_file())
        got = other.query("cat sewer", embed=e, k=1)
        self.assertEqual(got["results"][0]["sid"], "c1")
        with self.assertRaises(ValueError):
            sfx_vectors.Store.restore(out, target)

    def test_cli_manifest_and_query(self):
        fill(self.store)
        self.store.close()
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            sfx_vectors.main(["--root", str(self.root), "--fake-embed", "manifest"])
        m = json.loads(buf.getvalue())
        self.assertEqual(m["roots"]["samples"], "/samples")
        self.assertEqual(m["counts"]["clips"], 5)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            sfx_vectors.main(["--root", str(self.root), "--fake-embed", "query", "cat sewer", "-k", "2", "--video", "yes"])
        self.assertEqual(json.loads(buf.getvalue())["results"][0]["sid"], "c1")


class FakeStation(dict):
    def __init__(self, root):
        super().__init__()
        self.root = Path(root)
        (self.root / "data").mkdir()
        book = self.root / "data" / "sfx_clips.db"
        con = sqlite3.connect(str(book))
        con.execute("""create table clips(path text primary key, sid text, name text, folder text, video integer not null default 0,
                       bytes integer, mtime real, seconds real, playable integer not null default 0, seen_at real, said text,
                       said_at real, seen_desc text, seen_desc_at real, deck_cycle integer not null default 0)""")
        for c in CLIPS:
            con.execute("insert into clips(path, sid, name, folder, video, mtime, seconds, playable, said, seen_desc) values(?,?,?,?,?,?,?,?,?,?)",
                        (c["path"], c["sid"], c["name"], c["folder"], c["video"], 1.0, c["seconds"], 1, c.get("said"), c.get("seen_desc")))
        con.commit()
        con.close()
        hist = self.root / "data" / "sfx_history.jsonl"
        hist.write_text(json.dumps({"ts": 1790500000, "id": "c1", "name": "x", "who": "board"}) + "\n"
                        + json.dumps({"ts": 1790500100, "id": "c1", "name": "x", "who": "board"}) + "\n")
        (self.root / "data" / "sfxguy_speech.json").write_text(json.dumps({
            "k1": {"id": "k1", "text": "I'm listening, keep the flow.", "who": "drop", "voice": "vl_1",
                   "clip": {"path": "/media/abc.wav", "seconds": 2.0}, "at": 1.0}}))
        self.logged = []
        fake = sfx_vectors.fake_embedder()

        async def _embed_texts(texts):
            await asyncio.sleep(0)
            return fake(list(texts))

        def require_auth(authorization):
            if authorization != "Bearer k":
                raise HTTPException(401, "no")

        self.update(data_path=lambda *p: self.root.joinpath("data", *p), VOICE_MEDIA_DIR=self.root / "data" / "voice_media",
                    EMBED_MODEL="nomic-embed-text", _embed_texts=_embed_texts, _OLLAMA_GATE=asyncio.Lock(),
                    SFX_DB_PATH=book, SFX_HISTORY_ARCHIVE_PATH=hist, sfxguy_quips=lambda voice="": ["Well butter my butt."],
                    require_auth=require_auth, require_read_auth=lambda a: None,
                    pipeline_log=lambda kind, text, extra="": self.logged.append((kind, text)),
                    crystals_read=lambda: {"doom": {"name": "DOOM", "tint": "t", "minds": ["doom"]}},
                    _load_vectors=lambda rid: {"chunks": [{"file": "a.md", "text": "hello", "vec": [1.0, 0.0]}]},
                    mind_id=lambda rid: rid, votes_read=lambda: {}, chunk_key=lambda f, t: f + "|" + t)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.station = FakeStation(self.tmp.name)
        self.app = FastAPI()
        self.rt = sfx_vectors_runtime.install(self.app, self.station)
        self.addCleanup(self.rt.store.close)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def test_the_keeper_scans_airs_speaks_embeds_and_tags(self):
        asyncio.run(self.rt.tick())
        st = self.client.get("/api/sfx/vectors/status").json()
        self.assertEqual(st["counts"]["clips"], 5)
        self.assertEqual(st["counts"]["clips_embedded"], 5)
        self.assertEqual(st["counts"]["clips_tagged"], 5)
        self.assertGreaterEqual(st["counts"]["dialogue"], 2)
        self.assertEqual(st["metrics"]["failures"], 0, st["metrics"]["last_failure"])
        clip = self.client.get("/api/sfx/vectors/clip/c1").json()
        self.assertEqual(clip["aired"], 2)
        self.assertEqual(clip["path"], "/samples/tiktok/12 the cat dragged him into the sewer.mp4")
        # a second tick finds nothing new and stays cheap
        asyncio.run(self.rt.tick())
        self.assertEqual(self.client.get("/api/sfx/vectors/status").json()["metrics"]["ticks"], 2)

    def test_the_keeper_yields_the_model_to_the_writing_desk(self):
        async def held():
            async with self.station["_OLLAMA_GATE"]:
                await self.rt.tick()
        asyncio.run(held())
        st = self.client.get("/api/sfx/vectors/status").json()
        self.assertEqual(st["counts"]["clips"], 5)
        self.assertEqual(st["counts"]["clips_embedded"], 0)
        self.assertEqual(st["metrics"]["embed_skipped_busy"], 1)

    def test_the_doors(self):
        asyncio.run(self.rt.tick())
        got = self.client.get("/api/sfx/vectors/query", params={"q": "the cat in the sewer", "k": 2, "video": "yes"}).json()
        self.assertEqual(got["results"][0]["sid"], "c1")
        self.assertTrue(got["results"][0]["why"].get("lexical"))
        facets = self.client.get("/api/sfx/vectors/facets").json()
        self.assertIn("emotional", facets["facets"])
        r = self.client.put("/api/sfx/vectors/facets/emotional", headers={"Authorization": "Bearer k"},
                            json={"anchors": [["anger", "angry and shouting"], ["joy", "happy"]]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.client.get("/api/sfx/vectors/status").json()["counts"]["clips_tagged"], 0)
        b = self.client.post("/api/sfx/vectors/backup", headers={"Authorization": "Bearer k"}, json={"label": "quarantine"}).json()
        self.assertTrue(b["file"].startswith("sfx_vectors-quarantine-"))
        self.assertEqual(b["crystals"], 1)
        lst = self.client.get("/api/sfx/vectors/backups").json()
        self.assertEqual(lst["backups"][0]["file"], b["file"])
        dl = self.client.get("/api/sfx/vectors/backup/" + b["file"])
        self.assertEqual(dl.status_code, 200)
        self.assertGreater(len(dl.content), 1000)
        r = self.client.post("/api/sfx/vectors/restore", headers={"Authorization": "Bearer k"},
                             json={"file": b["file"], "into": "restored-test", "roots": {"samples": "E:/clips"}})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["roots"]["samples"], "E:/clips")
        self.assertEqual(r.json()["counts"]["clips"], 5)
        self.assertEqual(self.client.post("/api/sfx/vectors/backup", json={}).status_code, 401)
        self.assertEqual(self.client.get("/api/sfx/vectors/backup/../etc").status_code, 404)


if __name__ == "__main__":
    unittest.main()
