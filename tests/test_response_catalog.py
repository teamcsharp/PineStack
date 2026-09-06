import asyncio
from contextlib import ExitStack
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

import app
from response_bank import ResponseBank, source_response


class ResponseCatalogueReviewTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.doc = self.root / "gardens.md"
        self.body = "Gardens need seeds protected during winter and the greenhouse shelters delicate plants."
        self.doc.write_text(self.body, encoding="utf-8")
        self.source = {"file": self.doc.name, "mind": "main", "text": self.body}
        self.entry = {"text": "How do gardens survive winter?",
                      "keywords": ["gardens", "winter", "seeds"], "source": self.source}
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(app, "mind_id", return_value="main"))
        self.stack.enter_context(mock.patch.object(app, "speakbox_files", return_value=[self.doc]))

    def test_import_requires_an_exact_passage_from_an_enabled_document(self):
        fake = dict(self.entry, source=dict(self.source, text="Gardens are secretly made of gold during winter."))
        outside = dict(self.entry, source=dict(self.source, file="../private.md"))
        accepted, rejected = app.response_catalog_validate([self.entry, fake, outside])
        self.assertEqual([row["text"] for row in accepted], [self.entry["text"]])
        self.assertEqual([row["index"] for row in rejected], [1, 2])
        self.assertEqual(accepted[0]["source"]["text"], self.body)

    async def test_review_retires_existing_audio_and_imports_without_reviving_it(self):
        bank = ResponseBank(self.root / "bank.json", self.root)
        clip = {"path": "/media/old.wav", "seconds": 1.0}
        (self.root / "old.wav").write_bytes(b"existing audio fixture")
        old = source_response(self.entry, self.source)
        bank.stage([old])
        bank.put("alice", "xtts", old["text"], "topic", clip, old)
        original_audio_store = bank.path.read_bytes()
        new_entry = dict(self.entry, text="What protects seeds during winter?")
        request = SimpleNamespace(json=mock.AsyncMock(return_value={
            "entries": [self.entry, new_entry],
            "retire": [{"text": old["text"], "reason": "Reviewed replacement"}]}))
        with (mock.patch.object(app, "_RESPONSES", bank),
              mock.patch.object(app, "_RESPONSE_WARM_LOCK", asyncio.Lock()),
              mock.patch.object(app, "dj_settings", return_value={"response_bank_target": 64}),
              mock.patch.object(app, "require_auth") as authorize):
            result = await app.response_catalog_update(request, authorization="test")
        authorize.assert_called_once_with("test")
        self.assertEqual(result["added"], 1)
        self.assertEqual(result["rejected"], [])
        self.assertEqual([row["text"] for row in bank.catalog()], [new_entry["text"]])
        self.assertEqual(bank.ready("alice", "xtts"), [])
        self.assertEqual(bank.path.read_bytes(), original_audio_store)
        self.assertEqual(bank.protected_files(), {"old.wav"})
        self.assertTrue((self.root / "old.wav").is_file())


if __name__ == "__main__":
    unittest.main()
