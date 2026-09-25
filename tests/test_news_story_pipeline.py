"""A chosen headline must constrain planning and reach the recorded script."""

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import app
from system2 import System2Store


STORY = {"title": "Council approves new transit plan",
         "url": "https://example.org/news/transit-plan"}


class NewsStoryPipelineTests(unittest.IsolatedAsyncioTestCase):
    def test_selected_url_is_a_planning_constraint(self):
        slot = {"id": "hour-1:news", "kind": "news", "require_slot_binding": True,
                "require_news_source": True, "required_news_url": STORY["url"]}
        candidate = {"id": "take-1", "kind": "news", "slot_id": slot["id"],
                     "source": {"prep_news_stories": [STORY]}}
        self.assertTrue(System2Store._slot_matches(candidate, slot))
        candidate["source"]["prep_news_stories"] = [{"title": "Other",
                                                        "url": "https://example.org/other"}]
        self.assertFalse(System2Store._slot_matches(candidate, slot))
        candidate["source"]["prep_news_stories"] = []
        self.assertFalse(System2Store._slot_matches(candidate, slot))

    async def test_selection_is_persisted_and_forces_future_replan(self):
        with tempfile.TemporaryDirectory() as directory:
            slot_id = "hour-1:news"
            slot = {"id": slot_id, "kind": "news", "start": time.time() + 500,
                    "deadline": time.time() + 700}
            runtime = mock.Mock(_plans=[{"slots": [slot]}])
            runtime.refresh = mock.AsyncMock()
            request = mock.Mock()
            request.json = mock.AsyncMock(return_value={"slot_id": slot_id,
                                                         "url": STORY["url"]})
            dossier = {"title": STORY["title"], "url": STORY["url"],
                       "availability": "excerpt", "method": "search_index",
                       "excerpt": "Verified search excerpt"}
            with (mock.patch.object(app, "NEWS_STORY_CHOICES_PATH", Path(directory) / "choices.json"),
                  mock.patch.object(app, "_system2", return_value=runtime),
                  mock.patch.object(app, "drudge_headlines", new=mock.AsyncMock(return_value=[STORY])),
                  mock.patch.object(app, "news_story_dossier", new=mock.AsyncMock(return_value=dossier)),
                  mock.patch.object(app, "require_auth"),
                  mock.patch.object(app, "pipeline_log")):
                result = await app.api_news_choice(request)
                self.assertTrue(result["ok"])
                self.assertEqual(app.news_story_choice(slot_id)["url"], STORY["url"])
                runtime.refresh.assert_any_await(force=True, want_status=False)

    async def test_script_receives_dossier_and_carries_provenance(self):
        pile = []
        angles = []

        async def writer(_track, *, angle, bank_to, **_kwargs):
            angles.append(angle)
            bank_to.append({"script": "HOST: The council approved a transit plan."})
            return []

        dossier = {"title": STORY["title"], "url": STORY["url"],
                   "source_url": STORY["url"], "availability": "excerpt",
                   "method": "search_index", "article_text": "",
                   "excerpt": "The council voted 7-2 on Thursday.",
                   "evidence_links": [STORY["url"]]}
        with (mock.patch.object(app, "drudge_headlines", new=mock.AsyncMock(return_value=[])),
              mock.patch.object(app, "news_story_dossier", new=mock.AsyncMock(return_value=dossier)),
              mock.patch.object(app, "dj_banter", side_effect=writer),
              mock.patch.object(app, "airlog_news_summary")):
            await app.dj_news(bank_to=pile, selected=STORY)
        self.assertIn("The council voted 7-2", angles[0])
        self.assertIn("An excerpt or metadata is not a full article", angles[0])
        self.assertEqual(pile[0]["prep_news_stories"][0]["url"], STORY["url"])
        self.assertEqual(pile[0]["prep_news_stories"][0]["availability"], "excerpt")


if __name__ == "__main__":
    unittest.main()
